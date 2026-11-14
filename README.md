# mytts

An offline, minimalist read-aloud app for Windows. Select text in any window, press a hotkey, and a small reader window opens and starts speaking. The sentence being read is highlighted, and clicking any sentence jumps there.

> **Status:** early development. The voice engine, reader window, global hotkey, tray icon and settings work. An installer is next. See [ROADMAP.md](ROADMAP.md).

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
.venv\Scripts\python -m mytts download   # optional: the window offers the download on first start
```

## Read from any app

Start mytts, select text in any app and press **Ctrl+Alt+Space**. The reader window comes to the front and starts reading.

mytts copies the selection by sending the app Ctrl+C, then puts back whatever was on the clipboard before (text, images and files alike). In terminals (Windows Terminal, the classic console, Git Bash, PuTTY, ConEmu) it sends Ctrl+Insert instead, because Ctrl+C there would stop the running program. If nothing is selected, the window just comes to the front.

Windows does not let a normal app send keys to an app running as administrator, so selections in elevated windows can't be read.

## Reader window

```powershell
.venv\Scripts\pythonw -m mytts                         # start mytts and open the reader window
.venv\Scripts\pythonw -m mytts --tray                  # start it hidden in the tray
.venv\Scripts\python -m mytts open "Text to read now."  # open it and start reading
.venv\Scripts\python -m mytts quit                      # close the running app
```

Only one copy runs at a time: starting mytts again brings the running window to the front (and hands it the text, if any).

Closing the window pauses reading and hides it in the notification area. Click the tray icon to bring it back, middle-click it to play or pause, or right-click it for Read selection, Pause/Resume, Stop, Settings and Quit.

Paste text with **Ctrl+V** and it is read from the start. The sentence being spoken is highlighted; click any sentence to continue from there.

| Key | Action |
| --- | --- |
| Space | Play / pause |
| Esc | Stop |
| Left / Right | Previous / next sentence |
| Ctrl+V | Paste and read |
| Ctrl+= / Ctrl+- / Ctrl+0, Ctrl+wheel | Text size |

The bottom bar has the voice list, a speed slider (0.5× to 2×; double-click the value to reset), a dark/sepia theme switch, a pin button that keeps the window on top, and the settings button.

## Settings

- **Read selection hotkey:** click it and press a new combination (it needs Ctrl, Alt or Win). If another app already uses it, the settings window says so.
- **Restore the clipboard:** turn it off to keep the copied selection on the clipboard.
- **Keep the reader on top:** the same as the pin button.
- **Start with Windows:** starts mytts in the tray when you sign in (a `mytts` entry under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

The voice, speed, theme, text size and window position are remembered too. Settings are saved in `%APPDATA%\mytts\settings.json`.

## Command line

```powershell
.venv\Scripts\python -m mytts voices                       # list voices
.venv\Scripts\python -m mytts say "Hello there."           # read aloud
.venv\Scripts\python -m mytts say "Hello." -v bf_emma -s 1.2
Get-Clipboard | .venv\Scripts\python -m mytts say          # read stdin
.venv\Scripts\python -m mytts say "Hello." -o hello.wav    # save as WAV
```

Model files live in `%LOCALAPPDATA%\mytts\models` (override with the `MYTTS_MODELS_DIR` environment variable). If they are missing, the reader window offers to download them; an interrupted download resumes where it stopped.

## Credits

- Kokoro-82M by hexgrad, Apache-2.0.
- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) by thewh1teagle, MIT; the ONNX model files are downloaded from its releases.
- Pronunciation by [eSpeak NG](https://github.com/espeak-ng/espeak-ng) through `espeakng-loader` and `phonemizer`, GPL-3.0.

## License

MIT
