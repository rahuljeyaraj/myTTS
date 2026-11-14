"""Playback: synthesize a few sentences ahead and play them through PortAudio.

`Playback` holds the logic and does not depend on Qt. It runs two kinds of work
off the GUI thread:

- a synthesis worker thread that loads the voice engine, warms it up, and keeps
  the next few segments rendered in a cache;
- the PortAudio callback, which copies cached audio to the sound card and moves
  the playhead from segment to segment.

Commands (play, pause, jump, voice change...) only change shared state under a
lock, so the callback reacts within one audio block. Interrupted audio gets a
short fade-out instead of a click.

`Player` wraps `Playback` in a QObject and turns its events into Qt signals that
are delivered on the GUI thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from enum import Enum

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal

from .engine import DEFAULT_VOICE, SAMPLE_RATE, Engine, Voice
from .text import Segment

LOOKAHEAD = 2  # segments synthesized ahead of the one playing
KEEP_BEHIND = 2  # segments kept behind it, so "previous" starts instantly
SENTENCE_GAP_S = 0.12
PARAGRAPH_GAP_S = 0.35
FADE_S = 0.008
WARMUP_TEXT = "Ready."
MIN_SPEED, MAX_SPEED = 0.5, 2.0


class State(str, Enum):
    STOPPED = "stopped"
    LOADING = "loading"  # playing, but waiting for the voice engine
    PLAYING = "playing"
    PAUSED = "paused"


# on_event(kind, value), kind is one of:
#   "ready" (list[Voice]), "segment" (int), "state" (State), "finished" (None), "error" (str)
EventSink = Callable[[str, object], None]


class _CallbackStop(Exception):
    """Stand-in for sounddevice.CallbackStop when a fake stream is used."""


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """FFT resampling; only needed when the sound card refuses 24 kHz."""
    if src == dst or len(audio) == 0:
        return audio
    pad = 256  # keeps the FFT's wrap-around away from the real signal
    x = np.concatenate([np.zeros(pad, np.float32), audio, np.zeros(pad, np.float32)])
    n_out = int(round(len(x) * dst / src))
    spec = np.fft.rfft(x)
    out_spec = np.zeros(n_out // 2 + 1, dtype=spec.dtype)
    m = min(len(spec), len(out_spec))
    out_spec[:m] = spec[:m]
    y = np.fft.irfft(out_spec, n_out) * (n_out / len(x))
    cut = int(round(pad * dst / src))
    return y[cut : n_out - cut].astype(np.float32)


def segment_gaps(text: str, segments: Sequence[Segment]) -> list[float]:
    """Silence after each segment: longer where a new line or paragraph starts."""
    gaps = [
        PARAGRAPH_GAP_S if "\n" in text[a.end : b.start] else SENTENCE_GAP_S
        for a, b in zip(segments, segments[1:])
    ]
    return gaps + [0.0] if segments else []


def _open_device_stream(callback) -> tuple[object, int]:
    import sounddevice as sd

    # PortAudio lists devices once, at initialization. Re-initializing (about
    # 30 ms) makes a new session follow the current default output device.
    sd._terminate()
    sd._initialize()
    rate = SAMPLE_RATE
    try:
        sd.check_output_settings(samplerate=rate, channels=1, dtype="float32")
    except Exception:
        rate = int(sd.query_devices(kind="output")["default_samplerate"])
    stream = sd.OutputStream(
        samplerate=rate, channels=1, dtype="float32", latency="low", callback=callback
    )
    return stream, rate


def _callback_stop() -> type[BaseException]:
    try:
        import sounddevice as sd

        return sd.CallbackStop
    except Exception:  # pragma: no cover - PortAudio missing
        return _CallbackStop


class Playback:
    """Player logic without Qt. All public methods are meant for one (GUI) thread."""

    def __init__(
        self,
        on_event: EventSink,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        engine_factory: Callable[[], Engine] = Engine,
        stream_factory: Callable[..., tuple[object, int]] = _open_device_stream,
    ):
        self._emit = on_event
        self._engine_factory = engine_factory
        self._stream_factory = stream_factory
        self._stop_exc = _callback_stop()

        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._quit = False
        self._thread: threading.Thread | None = None
        self._engine: Engine | None = None
        self._engine_error: str | None = None

        # Document and voice settings
        self._texts: list[str] = []
        self._gaps: list[float] = []
        self._doc = 0  # bumped whenever the text changes; late synthesis results are dropped
        self._voice = voice
        self._speed = _clamp_speed(speed)
        self._cache: dict[tuple[int, str, float], np.ndarray] = {}

        # Playhead
        self._state = State.STOPPED
        self._cur = 0
        self._clip: np.ndarray | None = None  # audio of segment _cur, trailing gap included
        self._pos = 0
        self._fade_out: np.ndarray | None = None  # tail of interrupted audio, faded
        self._fade_in = 0  # frames of fade-in still to apply after a resume

        # Output
        self._stream = None
        self._rate = SAMPLE_RATE
        self._stream_idle = True  # True once the callback has asked PortAudio to stop

    # ----------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Load the voice engine on the worker thread and start serving synthesis."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="mytts-synth", daemon=True)
            self._thread.start()

    def close(self) -> None:
        with self._lock:
            self._quit = True
            self._state = State.STOPPED
            self._wake.notify_all()
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.close()
        if self._thread is not None:
            self._thread.join(timeout=3)

    # ------------------------------------------------------------------ queries

    @property
    def state(self) -> State:
        return self._state

    @property
    def current(self) -> int:
        return self._cur

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def count(self) -> int:
        return len(self._texts)

    @property
    def engine_error(self) -> str | None:
        """Why the voice engine could not be loaded, if it failed."""
        return self._engine_error

    # ----------------------------------------------------------------- commands

    def load(self, text: str, segments: Sequence[Segment]) -> None:
        """Replace the document and stop. Synthesis of the first segment starts right away."""
        with self._locked() as ev:
            self._interrupt()
            self._doc += 1
            self._texts = [s.speech for s in segments]
            self._gaps = segment_gaps(text, segments)
            self._cache.clear()
            self._cur, self._clip, self._pos = 0, None, 0
            self._set_state(State.STOPPED, ev)
            self._wake.notify()

    def play(self, index: int = 0) -> None:
        """Play from segment `index`, whatever the current state."""
        with self._locked() as ev:
            if not self._texts:
                return
            if self._engine_error:
                ev.append(("error", self._engine_error))
                return
            fresh = self._state == State.STOPPED
            self._interrupt()
            self._move_to(max(0, min(index, len(self._texts) - 1)), ev)
            ready = self._key(self._cur) in self._cache
            self._set_state(State.PLAYING if ready else State.LOADING, ev)
            restart = self._claim_stream()
        if restart:
            self._run_stream(fresh)

    def pause(self) -> None:
        with self._locked() as ev:
            if self._state in (State.PLAYING, State.LOADING):
                self._interrupt()
                self._set_state(State.PAUSED, ev)

    def resume(self) -> None:
        with self._locked() as ev:
            if self._state != State.PAUSED:
                return
            if self._clip is not None and self._pos > 0:
                self._fade_in = self._fade_frames()
            ready = self._clip is not None or self._key(self._cur) in self._cache
            self._set_state(State.PLAYING if ready else State.LOADING, ev)
            restart = self._claim_stream()
        if restart:
            self._run_stream(fresh=False)

    def toggle(self) -> None:
        """Play/pause button: pause, resume, or start from the beginning."""
        state = self._state
        if state in (State.PLAYING, State.LOADING):
            self.pause()
        elif state == State.PAUSED:
            self.resume()
        else:
            self.play(0)

    def stop(self) -> None:
        with self._locked() as ev:
            if self._state == State.STOPPED:
                return
            self._interrupt()
            self._cur, self._clip, self._pos = 0, None, 0
            self._set_state(State.STOPPED, ev)
            self._wake.notify()

    def jump(self, index: int) -> None:
        """Move to a segment. Playing continues from there; a paused player stays paused."""
        with self._locked() as ev:
            if not self._texts or self._state == State.STOPPED:
                return
            index = max(0, min(index, len(self._texts) - 1))
            if self._state == State.PAUSED:
                self._move_to(index, ev)
                return
        self.play(index)

    def next(self) -> None:
        if self._cur + 1 < len(self._texts):
            self.jump(self._cur + 1)

    def prev(self) -> None:
        self.jump(max(0, self._cur - 1))

    def set_voice(self, voice_id: str) -> None:
        with self._locked():
            if voice_id != self._voice:
                self._voice = voice_id
                self._restart_segment()

    def set_speed(self, speed: float) -> None:
        speed = _clamp_speed(speed)
        with self._locked():
            if speed != self._speed:
                self._speed = speed
                self._restart_segment()

    # ---------------------------------------------------------------- internals
    # Methods below that touch shared state expect self._lock to be held.

    @contextmanager
    def _locked(self):
        events: list[tuple[str, object]] = []
        with self._lock:
            yield events
        for kind, value in events:
            self._emit(kind, value)

    def _key(self, i: int) -> tuple[int, str, float]:
        return (i, self._voice, self._speed)

    def _fade_frames(self) -> int:
        return max(1, int(FADE_S * self._rate))

    def _set_state(self, state: State, ev: list) -> None:
        if state != self._state:
            self._state = state
            ev.append(("state", state))

    def _move_to(self, index: int, ev: list) -> None:
        self._cur, self._clip, self._pos, self._fade_in = index, None, 0, 0
        ev.append(("segment", index))
        self._wake.notify()

    def _interrupt(self) -> None:
        """Fade out whatever is audible right now instead of cutting it off."""
        if self._state == State.PLAYING and self._clip is not None and not self._stream_idle:
            n = self._fade_frames()
            tail = self._clip[self._pos : self._pos + n]
            if self._fade_in:  # resumed a moment ago: don't jump back to full volume
                tail = tail * min(1.0, 1 - self._fade_in / n)
            self._fade_out = tail * np.linspace(1.0, 0.0, len(tail), dtype=np.float32)
        self._fade_in = 0

    def _restart_segment(self) -> None:
        """After a voice or speed change, say the current segment again with the new settings."""
        self._cache = {k: v for k, v in self._cache.items() if k[1:] == (self._voice, self._speed)}
        if self._state in (State.PLAYING, State.LOADING, State.PAUSED):
            self._interrupt()
            self._clip, self._pos = None, 0
        self._wake.notify()

    def _claim_stream(self) -> bool:
        """True if the output stream has to be (re)started for the state just set."""
        idle, self._stream_idle = self._stream_idle, False
        return idle

    def _run_stream(self, fresh: bool) -> None:
        """Start audio output. Called without the lock held (PortAudio may call back)."""
        try:
            if fresh or self._stream is None:
                self._open_stream()
            else:
                try:
                    self._stream.abort()  # the callback has stopped it; reset before start
                    self._stream.start()
                except Exception:  # device went away while paused
                    self._open_stream()
        except Exception as e:
            with self._locked() as ev:
                self._stream_idle = True
                self._clip, self._pos = None, 0
                self._set_state(State.STOPPED, ev)
                ev.append(("error", f"Could not open the audio device: {e}"))

    def _open_stream(self) -> None:
        old, self._stream = self._stream, None
        if old is not None:
            old.close()
        stream, rate = self._stream_factory(self._callback)
        with self._lock:
            if rate != self._rate:  # cached audio is stored at the device rate
                self._rate = rate
                self._cache.clear()
                self._clip, self._pos, self._fade_out = None, 0, None
                self._wake.notify()
        self._stream = stream
        stream.start()

    # --------------------------------------------------------- audio callback

    def _callback(self, outdata, frames, time_info, status) -> None:
        out = outdata[:, 0]
        with self._locked() as ev:
            n = 0
            if self._fade_out is not None:
                n = min(frames, len(self._fade_out))
                out[:n] = self._fade_out[:n]
                self._fade_out = self._fade_out[n:] if n < len(self._fade_out) else None
            if self._state in (State.PLAYING, State.LOADING):
                n = self._fill(out, n, ev)
            out[n:] = 0
            stop = self._state in (State.STOPPED, State.PAUSED) and self._fade_out is None
            if stop:
                self._stream_idle = True
        if stop:
            raise self._stop_exc

    def _fill(self, out: np.ndarray, n: int, ev: list) -> int:
        frames = len(out)
        while n < frames:
            if self._clip is None:
                clip = self._cache.get(self._key(self._cur))
                if clip is None:
                    self._set_state(State.LOADING, ev)
                    self._wake.notify()
                    return n
                self._clip, self._pos = clip, 0
                self._set_state(State.PLAYING, ev)
            k = min(frames - n, len(self._clip) - self._pos)
            out[n : n + k] = self._clip[self._pos : self._pos + k]
            if self._fade_in:
                total = self._fade_frames()
                m = min(k, self._fade_in)
                done = total - self._fade_in
                out[n : n + m] *= np.arange(done + 1, done + m + 1, dtype=np.float32) / total
                self._fade_in -= m
            self._pos += k
            n += k
            if self._pos >= len(self._clip):
                if self._cur + 1 >= len(self._texts):
                    self._cur, self._clip, self._pos = 0, None, 0
                    self._set_state(State.STOPPED, ev)
                    ev.append(("finished", None))
                    return n
                self._move_to(self._cur + 1, ev)
        return n

    # --------------------------------------------------------- synthesis worker

    def _run(self) -> None:
        if not self._init_engine():
            return
        while True:
            with self._lock:
                job = self._next_job()
                while job is None and not self._quit:
                    self._wake.wait()
                    job = self._next_job()
                if self._quit:
                    return
            self._do_job(job)

    def _init_engine(self) -> bool:
        try:
            engine = self._engine_factory()
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            with self._locked() as ev:
                self._engine_error = msg
                if self._state != State.STOPPED:
                    self._set_state(State.STOPPED, ev)
                ev.append(("error", msg))
            return False
        with self._lock:
            self._engine = engine
            pending = self._next_job() is not None
        self._emit("ready", list(engine.voices))
        if not pending:  # the first real sentence would warm it up anyway
            try:
                engine.synthesize(WARMUP_TEXT, self._voice, 1.0)
            except Exception:
                pass
        return True

    def _next_job(self) -> tuple | None:
        if self._engine is None or not self._texts or self._quit:
            return None
        ahead = 0 if self._state == State.STOPPED else LOOKAHEAD
        for i in range(self._cur, min(len(self._texts), self._cur + ahead + 1)):
            if self._key(i) not in self._cache:
                return (self._doc, i, self._texts[i], self._voice, self._speed, self._gaps[i], self._rate)
        return None

    def _do_job(self, job: tuple) -> None:
        doc, i, text, voice, speed, gap, rate = job
        error = None
        try:
            audio = self._engine.synthesize(text, voice, speed)
        except Exception as e:  # skip a segment the engine cannot say
            audio = np.zeros(0, dtype=np.float32)
            error = f"Could not read sentence {i + 1}: {e}"
        audio = resample(audio, SAMPLE_RATE, rate)
        audio = np.concatenate([audio, np.zeros(int(gap * rate), dtype=np.float32)])
        with self._locked() as ev:
            if doc == self._doc and rate == self._rate:
                self._cache[(i, voice, speed)] = audio
                self._prune()
            if error:
                ev.append(("error", error))

    def _prune(self) -> None:
        lo, hi = self._cur - KEEP_BEHIND, self._cur + LOOKAHEAD + 1
        self._cache = {
            k: v
            for k, v in self._cache.items()
            if k[1:] == (self._voice, self._speed) and lo <= k[0] <= hi
        }

    def _drain_jobs(self) -> None:
        """Run pending synthesis on the calling thread (for tests)."""
        while True:
            with self._lock:
                job = self._next_job()
            if job is None:
                return
            self._do_job(job)


def _clamp_speed(speed: float) -> float:
    return round(min(MAX_SPEED, max(MIN_SPEED, float(speed))), 2)


class Player(QObject):
    """Qt face of `Playback`: same commands, events arrive as signals on the GUI thread."""

    ready = Signal(list)  # list[Voice]
    segment_started = Signal(int)
    state_changed = Signal(object)  # State
    finished = Signal()
    error = Signal(str)

    _event = Signal(str, object)

    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = 1.0, parent: QObject | None = None, **kw):
        super().__init__(parent)
        self._event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        self._core = Playback(self._event.emit, voice, speed, **kw)
        self.voices: list[Voice] = []

    def _dispatch(self, kind: str, value: object) -> None:
        if kind == "segment":
            self.segment_started.emit(value)
        elif kind == "state":
            self.state_changed.emit(value)
        elif kind == "finished":
            self.finished.emit()
        elif kind == "error":
            self.error.emit(value)
        elif kind == "ready":
            self.voices = value
            self.ready.emit(value)

    # Delegated commands and queries
    def start(self) -> None:
        self._core.start()

    def close(self) -> None:
        self._core.close()

    def load(self, text: str, segments: Sequence[Segment]) -> None:
        self._core.load(text, segments)

    def play(self, index: int = 0) -> None:
        self._core.play(index)

    def pause(self) -> None:
        self._core.pause()

    def resume(self) -> None:
        self._core.resume()

    def toggle(self) -> None:
        self._core.toggle()

    def stop(self) -> None:
        self._core.stop()

    def jump(self, index: int) -> None:
        self._core.jump(index)

    def next(self) -> None:
        self._core.next()

    def prev(self) -> None:
        self._core.prev()

    def set_voice(self, voice_id: str) -> None:
        self._core.set_voice(voice_id)

    def set_speed(self, speed: float) -> None:
        self._core.set_speed(speed)

    @property
    def state(self) -> State:
        return self._core.state

    @property
    def current(self) -> int:
        return self._core.current

    @property
    def count(self) -> int:
        return self._core.count

    @property
    def voice(self) -> str:
        return self._core.voice

    @property
    def speed(self) -> float:
        return self._core.speed

    @property
    def engine_error(self) -> str | None:
        return self._core.engine_error
