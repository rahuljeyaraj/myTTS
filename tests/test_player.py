import time

import numpy as np
import pytest

from mytts.engine import SAMPLE_RATE, Voice
from mytts.player import (
    PARAGRAPH_GAP_S,
    SENTENCE_GAP_S,
    Playback,
    State,
    resample,
    segment_gaps,
)
from mytts.text import normalize, segment

BLOCK = 480  # 20 ms at 24 kHz
CLIP = 2400  # every fake sentence lasts 0.1 s


class FakeEngine:
    voices = [Voice("af_heart", "Heart", "en-us", "English (US)", "female")]

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice_id="af_heart", speed=1.0):
        self.calls.append((text, voice_id, speed))
        # A constant level per sentence lets the tests tell sentences apart.
        return np.full(CLIP, 0.1 + 0.01 * len(self.calls), dtype=np.float32)


class FakeStream:
    def __init__(self):
        self.starts = 0
        self.closed = False

    def start(self):
        self.starts += 1

    def abort(self):
        pass

    def close(self):
        self.closed = True


class Rig:
    """A Playback whose synthesis and audio callback are driven by the test."""

    def __init__(self, text="One. Two. Three."):
        self.events = []
        self.engine = FakeEngine()
        self.streams = []
        self.p = Playback(
            lambda kind, value: self.events.append((kind, value)),
            engine_factory=lambda: self.engine,
            stream_factory=self._stream,
        )
        assert self.p._init_engine()
        self.engine.calls.clear()  # drop the warm-up
        self.text = normalize(text)
        self.segments = segment(self.text)
        self.p.load(self.text, self.segments)
        self.events.clear()

    def _stream(self, callback):
        self.streams.append(FakeStream())
        return self.streams[-1], SAMPLE_RATE

    def pump(self, blocks=1, synth=True):
        """Run synthesis, then `blocks` audio callbacks. Returns (audio, stopped)."""
        out, stopped = [], False
        for _ in range(blocks):
            if synth:
                self.p._drain_jobs()
            buf = np.full((BLOCK, 1), 9.0, dtype=np.float32)  # garbage the callback must overwrite
            try:
                self.p._callback(buf, BLOCK, None, None)
            except BaseException as e:
                if type(e).__name__ != "CallbackStop" and type(e).__name__ != "_CallbackStop":
                    raise
                stopped = True
            out.append(buf[:, 0].copy())
            if stopped:
                break
        return np.concatenate(out), stopped

    def of(self, kind):
        return [v for k, v in self.events if k == kind]


def test_plays_all_segments_in_order_with_gaps_then_finishes():
    r = Rig()
    r.p.play()
    audio, stopped = r.pump(40)
    assert stopped
    assert r.of("segment") == [0, 1, 2]
    assert r.of("finished") == [None]
    assert r.p.state == State.STOPPED
    gap = int(SENTENCE_GAP_S * SAMPLE_RATE)
    assert np.count_nonzero(audio) == CLIP * 3
    assert len(audio) >= CLIP * 3 + gap * 2
    assert not np.any(audio == 9.0)
    # The sentence gap really sits between the first two sentences.
    first_silence = np.flatnonzero(audio == 0)[0]
    assert first_silence == CLIP
    assert np.all(audio[CLIP : CLIP + gap] == 0)


def test_only_the_first_segment_is_synthesized_until_play():
    r = Rig()
    r.p._drain_jobs()
    assert [c[0] for c in r.engine.calls] == ["One."]
    r.p.play()
    r.p._drain_jobs()
    assert [c[0] for c in r.engine.calls] == ["One.", "Two.", "Three."]


def test_waits_in_loading_state_until_audio_is_ready():
    r = Rig()
    r.p.play()
    assert r.p.state == State.LOADING
    audio, _ = r.pump(2, synth=False)
    assert not audio.any()
    assert r.p.state == State.LOADING
    r.pump(1)
    assert r.p.state == State.PLAYING


def test_pause_fades_out_stops_the_stream_and_resume_continues():
    r = Rig()
    r.p.play()
    a, _ = r.pump(2)  # 960 of 2400 frames of the first sentence played
    assert np.count_nonzero(a) == 2 * BLOCK
    r.p.pause()
    assert r.p.state == State.PAUSED
    tail, stopped = r.pump(1)
    assert stopped
    fade = int(0.008 * SAMPLE_RATE)
    assert np.count_nonzero(tail) == fade - 1  # linear ramp ends at exactly zero
    assert np.all(np.diff(tail[:fade]) <= 0)
    assert np.all(tail[fade:] == 0)

    r.p.resume()
    assert r.streams[0].starts == 2  # restarted the same stream
    a, _ = r.pump(1)
    assert a[0] < a[100]  # fades back in
    assert r.p.state == State.PLAYING
    assert r.of("segment") == [0]


def test_jump_while_playing_and_next_prev_while_paused():
    r = Rig("Alpha. Beta. Gamma. Delta.")
    r.p.play()
    r.pump(1)
    r.p.jump(2)
    r.pump(2)
    assert r.of("segment") == [0, 2]
    r.p.pause()
    r.pump(1)
    r.p.next()
    assert r.p.current == 3 and r.p.state == State.PAUSED
    r.p.next()  # already at the last segment
    assert r.p.current == 3
    r.p.prev()
    r.p.prev()
    assert r.p.current == 1 and r.p.state == State.PAUSED
    assert r.of("segment") == [0, 2, 3, 2, 1]


def test_voice_and_speed_changes_restart_the_current_segment():
    r = Rig()
    r.p.play()
    r.pump(3)
    calls = len(r.engine.calls)
    r.p.set_speed(1.5)
    r.pump(2)
    assert r.engine.calls[calls] == ("One.", "af_heart", 1.5)
    assert r.p.current == 0
    r.p.set_voice("bf_emma")
    r.pump(1)
    assert ("One.", "bf_emma", 1.5) in r.engine.calls
    assert all(k[1:] == ("bf_emma", 1.5) for k in r.p._cache)
    r.p.set_speed(7)
    assert r.p.speed == 2.0


def test_stop_and_load_discard_late_results():
    r = Rig()
    r.p.play()
    with r.p._lock:
        job = r.p._next_job()
    r.p.load(normalize("New text here."), segment(normalize("New text here.")))
    r.p._do_job(job)  # finishes after the document changed
    assert r.p._cache == {}
    r.p.stop()
    assert r.p.state == State.STOPPED and r.p.current == 0


def test_play_after_finish_opens_a_fresh_stream():
    r = Rig("Only one.")
    r.p.play()
    r.pump(20)
    assert r.p.state == State.STOPPED
    r.p.play()
    assert len(r.streams) == 2 and r.streams[0].closed


def test_engine_failure_is_reported_and_play_refused():
    events = []

    def broken():
        raise FileNotFoundError("Voice model not found")

    p = Playback(lambda k, v: events.append((k, v)), engine_factory=broken, stream_factory=None)
    assert not p._init_engine()
    p.load("Hi.", segment("Hi."))
    p.play()
    assert p.state == State.STOPPED
    assert [v for k, v in events if k == "error"] == ["Voice model not found"] * 2


def test_segment_gaps_follow_paragraphs():
    text = normalize("One. Two.\n\nNew paragraph.\n- item")
    gaps = segment_gaps(text, segment(text))
    assert gaps == [SENTENCE_GAP_S, PARAGRAPH_GAP_S, PARAGRAPH_GAP_S, 0.0]


@pytest.mark.parametrize("dst", [44_100, 48_000])
def test_resample_keeps_pitch_and_length(dst):
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    out = resample(tone, SAMPLE_RATE, dst)
    assert abs(len(out) - dst) <= 1
    peak = np.argmax(np.abs(np.fft.rfft(out))) * dst / len(out)
    assert abs(peak - 440) < 2


# ----------------------------------------------------------- default device changes


def test_device_change_while_playing_moves_to_a_new_stream_without_losing_the_place():
    r = Rig()
    r.p.play()
    r.pump(3)  # 1440 frames of the first sentence handed to the device
    r.streams[0].latency = 0.01  # 240 frames were still waiting in the old device's buffer
    r.p.device_changed()
    assert len(r.streams) == 2 and r.streams[0].closed and r.streams[1].starts == 1
    assert r.p.state == State.PLAYING
    a, _ = r.pump(3)
    assert 0 < a[0] < a[100]  # fades in on the new device
    # The rest of sentence one plays from just before where the old device stopped.
    rest = CLIP - 1440 + 240
    assert np.all(a[:rest] != 0) and np.all(a[rest : rest + 100] == 0)
    assert r.of("segment") == [0]


def test_device_change_while_paused_reopens_on_resume():
    r = Rig()
    r.p.play()
    r.pump(2)
    r.p.pause()
    r.pump(1)
    r.p.device_changed()
    assert len(r.streams) == 1  # nothing to move while paused
    r.p.resume()
    assert len(r.streams) == 2 and r.streams[0].closed
    a, _ = r.pump(1)
    assert a.any() and r.p.state == State.PLAYING
    r.p.pause()
    r.pump(1)
    r.p.resume()
    assert len(r.streams) == 2 and r.streams[1].starts == 2  # back to restarting the same stream


def test_device_change_before_any_playback_does_nothing():
    r = Rig()
    r.p.device_changed()
    assert r.streams == []
    r.p.play()
    assert len(r.streams) == 1


def test_failed_switch_pauses_with_an_error_and_resume_retries():
    r = Rig()
    r.p.play()
    r.pump(2)
    good = r.p._stream_factory

    def broken(cb):
        raise OSError("device unavailable")

    r.p._stream_factory = broken
    r.p.device_changed()
    assert r.p.state == State.PAUSED
    assert r.of("error") == ["Could not switch to the new audio device: device unavailable"]
    r.p._stream_factory = good
    r.p.resume()
    a, _ = r.pump(1)
    assert a.any() and r.p.state == State.PLAYING and r.p.current == 0


def test_device_watcher_reports_a_stable_new_default_once():
    from mytts.audiodevice import DeviceWatcher

    seen = iter(["usb", "usb", "bt", "usb", "bt", "bt", "bt", None, None, "usb", "usb"])
    changes = []
    w = DeviceWatcher(lambda: changes.append(1), probe=lambda: lambda: next(seen, None), interval=0)
    w.start()
    deadline = time.monotonic() + 2
    while len(changes) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    w.stop()
    # "bt" once it holds for two polls; the single "bt" flap and the gap with no device are ignored.
    assert len(changes) == 2
