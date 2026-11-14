# mytts

An offline, minimalist read-aloud app for Windows. Select text in any window, press a hotkey, and a small reader window opens and starts speaking. The sentence being read is highlighted, and clicking any sentence jumps there.

> **Status:** early development. The voice engine, command line and reader window work. The global hotkey, tray icon and installer are next. See [ROADMAP.md](ROADMAP.md).

## Voices

mytts uses [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an open neural text-to-speech model, running locally through ONNX Runtime. Nothing you read leaves your computer. The model is downloaded once (about 350 MB) and checked against a fixed SHA-256 checksum.

There are 41 voices in English (US and UK), Spanish, French, Hindi, Italian and Brazilian Portuguese. The default is **Heart** (`af_heart`), the highest-rated Kokoro voice.

## Setup (from source)

Requires Windows 10 or 11 and Python 3.10 to 3.13.

```powershell
git clone https://github.com/rahuljeyaraj/mytts.git
cd mytts
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m mytts download
```

## Reader window

```powershell
.venv\Scripts\pythonw -m mytts                         # open the reader window
.venv\Scripts\python -m mytts open "Text to read now."  # open it and start reading
```

Paste text with **Ctrl+V** and it is read from the start. The sentence being spoken is highlighted; click any sentence to continue from there.

| Key | Action |
| --- | --- |
| Space | Play / pause |
| Esc | Stop |
| Left / Right | Previous / next sentence |
| Ctrl+V | Paste and read |
| Ctrl+= / Ctrl+- / Ctrl+0, Ctrl+wheel | Text size |

The bottom bar has the voice list, a speed slider (0.5× to 2×; double-click the value to reset), a dark/sepia theme switch and a pin button that keeps the window on top.

## Command line

```powershell
.venv\Scripts\python -m mytts voices                       # list voices
.venv\Scripts\python -m mytts say "Hello there."           # read aloud
.venv\Scripts\python -m mytts say "Hello." -v bf_emma -s 1.2
Get-Clipboard | .venv\Scripts\python -m mytts say          # read stdin
.venv\Scripts\python -m mytts say "Hello." -o hello.wav    # save as WAV
```

Model files live in `%LOCALAPPDATA%\mytts\models` (override with the `MYTTS_MODELS_DIR` environment variable).

## Credits

- Kokoro-82M by hexgrad, Apache-2.0.
- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) by thewh1teagle, MIT; the ONNX model files are downloaded from its releases.
- Pronunciation by [eSpeak NG](https://github.com/espeak-ng/espeak-ng) through `espeakng-loader` and `phonemizer`, GPL-3.0.

## License

MIT
