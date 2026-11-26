"""Command line: `python -m mytts [command]`. Without a command, the reader window opens."""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import DISPLAY_NAME, __version__, models, paths

SENTENCE_GAP_S = 0.12


def _cmd_download(args: argparse.Namespace) -> int:
    todo = models.missing()
    if not todo:
        print(f"Voice model already installed in {models.MODEL.path.parent}")
    for f in todo:
        print(f"Downloading {f.name} ({f.size / 1e6:.0f} MB)")
        last = [0.0]

        def progress(_f, done, total):
            now = time.monotonic()
            if now - last[0] > 0.5 or done == total:
                last[0] = now
                print(f"\r  {done / total:6.1%}  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)

        models.download(f, progress)
        print("\n  verified and saved")
    if args.verify:
        for f in models.REQUIRED:
            print(f"{f.name}: {'OK' if models.verify(f) else 'CHECKSUM MISMATCH'}")
    return 0


def _cmd_voices(_args: argparse.Namespace) -> int:
    from .engine import Engine

    for v in Engine().voices:
        print(f"{v.id:16} {v.label}")
    return 0


def _cmd_say(args: argparse.Namespace) -> int:
    import numpy as np

    from .audio import silence, write_wav
    from .engine import SAMPLE_RATE, Engine
    from .text import normalize, segment

    raw = sys.stdin.read() if args.text in (None, "-") else args.text
    segments = segment(normalize(raw))
    if not segments:
        print("Nothing to read.")
        return 1

    t0 = time.perf_counter()
    engine = Engine()
    print(f"Model loaded in {time.perf_counter() - t0:.1f}s; voice {engine.voice(args.voice).label}")

    def synth(i: int):
        start = time.perf_counter()
        audio = engine.synthesize(segments[i].speech, args.voice, args.speed)
        return audio, time.perf_counter() - start

    gap = silence(SENTENCE_GAP_S, SAMPLE_RATE)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(synth, 0)
        chunks = []
        for i, seg in enumerate(segments):
            audio, took = pending.result()
            if i + 1 < len(segments):
                pending = pool.submit(synth, i + 1)  # synthesize ahead while this one plays
            rtf = took / max(len(audio) / SAMPLE_RATE, 1e-6)
            print(f"[{i + 1}/{len(segments)}] ({took:.2f}s, RTF {rtf:.2f}) {seg.speech}")
            if args.out:
                chunks += [audio, gap]
            else:
                import sounddevice as sd

                sd.play(audio, SAMPLE_RATE)
                sd.wait()
    if args.out:
        write_wav(args.out, np.concatenate(chunks), SAMPLE_RATE)
        print(f"Saved {args.out}")
    return 0


def _cmd_open(args: argparse.Namespace) -> int:
    from .ui.app import run

    text = sys.stdin.read() if getattr(args, "text", None) == "-" else getattr(args, "text", None)
    return run(text, tray=args.tray)


SELF_TEST_TEXT = "This is a short test of the offline voice."


def _cmd_self_test(_args: argparse.Namespace) -> int:
    """Load everything the app needs and synthesize one sentence without playing it (for CI)."""
    import logging

    log = logging.getLogger("mytts.selftest")
    t0 = time.perf_counter()

    def step(msg: str) -> None:
        print(f"[{time.perf_counter() - t0:5.2f}s] {msg}", flush=True)
        log.info(msg)

    step(f"{DISPLAY_NAME} {__version__} ({'exe' if paths.frozen() else 'source'}, Python {sys.version.split()[0]})")

    import sounddevice as sd  # loads the PortAudio DLL

    step(f"PortAudio {sd.get_portaudio_version()[1]}: {len(sd.query_devices())} audio devices")

    from PySide6.QtWidgets import QApplication  # loads the Qt DLLs and the platform plugin

    from .ui.icon import app_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    if app_icon().isNull():
        raise RuntimeError("the app icon could not be drawn")
    step(f"Qt {__import__('PySide6').__version__}, platform {app.platformName()}")

    import numpy as np

    from .engine import SAMPLE_RATE, Engine

    engine = Engine()
    step(f"Voice model loaded: {len(engine.voices)} voices")
    start = time.perf_counter()
    audio = engine.synthesize(SELF_TEST_TEXT)
    took = time.perf_counter() - start
    seconds = len(audio) / SAMPLE_RATE
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    step(f"Synthesized {seconds:.2f} s of audio in {took:.2f} s (peak {peak:.2f})")
    if seconds < 0.5 or peak < 0.01:
        print("Self-test FAILED: the audio is empty or silent.", file=sys.stderr)
        log.error("Self-test failed: %.2f s of audio, peak %.3f", seconds, peak)
        return 1
    step("Self-test passed")
    return 0


def _cmd_quit(_args: argparse.Namespace) -> int:
    from .ui.app import quit_running

    return quit_running()


# Arguments that print something and exit, so they need a console.
_CONSOLE_COMMANDS = {"-h", "--help", "--version", "--self-test", "quit", "download", "voices", "say"}


def _console_streams(argv: list[str]) -> None:
    """Give a windowed exe somewhere to print.

    myTTS.exe has no console, so sys.stdout and sys.stderr start as None. For the
    commands that print, use the console of the terminal it was started from.
    The reader window never attaches: closing that terminal would close the app.
    Without a console, output goes nowhere (and errors go to the log).
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    first = next((a for a in argv if a != "--tray"), "")
    if sys.platform == "win32" and first in _CONSOLE_COMMANDS:
        import ctypes

        ATTACH_PARENT_PROCESS = 0xFFFFFFFF
        if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            try:
                out = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                out.write("\n")  # the shell has already printed its prompt; start on a fresh line
            except OSError:
                out = None
            if out is not None:
                sys.stdout = sys.stdout or out
                sys.stderr = sys.stderr or out
    sys.stdout = sys.stdout or open(os.devnull, "w")
    sys.stderr = sys.stderr or open(os.devnull, "w")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _console_streams(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    from . import logs

    logs.setup()

    parser = argparse.ArgumentParser(prog="myTTS.exe" if paths.frozen() else "mytts",
                                     description=f"{DISPLAY_NAME}: offline text-to-speech reader.")
    parser.add_argument("--version", action="version", version=f"{DISPLAY_NAME} {__version__}")
    parser.add_argument("--tray", action="store_true", help="start hidden in the notification area")
    parser.add_argument("--self-test", action="store_true",
                        help="load the voice model and synthesize one sentence without playing it")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("open", help="open the reader window (the default), optionally reading TEXT")
    p.add_argument("text", nargs="?", help="text to read right away; '-' reads stdin")
    p.set_defaults(func=_cmd_open)

    p = sub.add_parser("quit", help="close the running app")
    p.set_defaults(func=_cmd_quit)

    p = sub.add_parser("download", help="download the offline voice model (~350 MB, once)")
    p.add_argument("--verify", action="store_true", help="re-check SHA-256 of installed files")
    p.set_defaults(func=_cmd_download)

    p = sub.add_parser("voices", help="list available voices")
    p.set_defaults(func=_cmd_voices)

    p = sub.add_parser("say", help="read text aloud (or save it as WAV)")
    p.add_argument("text", nargs="?", help="text to read; omit or '-' to read stdin")
    p.add_argument("-v", "--voice", default="af_heart", help="voice id (see `voices`)")
    p.add_argument("-s", "--speed", type=float, default=1.0, help="0.5 to 2.0")
    p.add_argument("-o", "--out", help="write a WAV file instead of playing")
    p.set_defaults(func=_cmd_say)

    args = parser.parse_args(argv)
    if args.self_test:
        args.func = _cmd_self_test
    elif not getattr(args, "func", None):
        args.func = _cmd_open
    command = "self-test" if args.self_test else args.command or "open"
    logs.log.info("%s %s (%s, Python %s): %s%s", DISPLAY_NAME, __version__, "exe" if paths.frozen() else "source",
                  sys.version.split()[0], command, " --tray" if args.tray else "")
    try:
        return args.func(args)
    except (FileNotFoundError, models.DownloadError) as e:
        print(f"error: {e}", file=sys.stderr)
        logs.log.error("%s", e)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
