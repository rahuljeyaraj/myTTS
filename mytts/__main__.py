"""Command line: `python -m mytts [command]`. Without a command, the reader window opens."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__, models

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

    text = sys.stdin.read() if args.text == "-" else args.text
    return run(text)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="mytts", description="Offline text-to-speech reader.")
    parser.add_argument("--version", action="version", version=f"mytts {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("open", help="open the reader window (the default), optionally reading TEXT")
    p.add_argument("text", nargs="?", help="text to read right away; '-' reads stdin")
    p.set_defaults(func=_cmd_open)

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
    if not getattr(args, "func", None):
        args = parser.parse_args(["open"])
    try:
        return args.func(args)
    except (FileNotFoundError, models.DownloadError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
