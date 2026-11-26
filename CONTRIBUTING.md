# Contributing to myTTS

Thanks for your interest in myTTS! Bug reports, ideas and pull requests are all welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in every issue, pull request and discussion.

## Reporting a bug

[Open a bug report](https://github.com/rahuljeyaraj/myTTS/issues/new?template=bug_report.yml). The form asks for:

- the myTTS version (Settings > About, or `myTTS.exe --version`),
- your Windows version (run `winver`),
- the app you were reading from, and what happened,
- the end of the log file, `%LOCALAPPDATA%\mytts\logs\mytts.log`. It records what the app did, never the text you read. Have a look before you paste it anyway.

A security problem goes through a private report instead: see [SECURITY.md](SECURITY.md).

## Suggesting a feature

[Open a feature request](https://github.com/rahuljeyaraj/myTTS/issues/new?template=feature_request.yml) and describe what you want to do, not only the feature. myTTS tries to stay small and calm: a feature that needs a new setting has to be worth it for most people.

## Setting up the code

You need Windows 10 or 11 and 64-bit [Python 3.10](https://www.python.org/downloads/windows/) (the version releases are built with; 3.11 to 3.13 also work for development).

```powershell
git clone https://github.com/rahuljeyaraj/myTTS.git
cd myTTS
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r packaging\requirements-lock.txt
.venv\Scripts\python -m mytts download      # the voice model, 354 MB, once
.venv\Scripts\python -m mytts               # run from the source folder
```

`packaging\requirements-lock.txt` holds the exact versions a release is built with. `requirements.txt` gives the ranges the app supports.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

The tests need no audio device and no voice model: they use fake engines and Qt's offscreen platform. Please add a test for each bug you fix and each feature you add. CI runs the tests on Python 3.10 with the locked versions and on Python 3.13 with the newest allowed versions.

To try a change in the real app, run it from the source folder as above. The installed copy keeps running independently if it uses a different hotkey; otherwise quit it first (`myTTS.exe quit`).

To build `myTTS.exe` and the installer, see [Development](README.md#development) in the README.

## Pull requests

1. For anything larger than a small fix, open an issue first, so we can agree on the approach before you spend time on it.
2. Keep a pull request to one change. Match the style of the code around it: type hints, short docstrings that say why, and comments only where the code can't say it.
3. Update the README if what people see changes, and add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
4. Make sure `python -m pytest -q` passes.
5. The PowerShell scripts (`install.ps1`, `uninstall.ps1`, `packaging\build.ps1`) must stay ASCII: Windows PowerShell 5.1 reads a file without a byte order mark in the ANSI code page. A test checks this.

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE), like the rest of the source code.

## How the code is organised

| Path | What it is |
| --- | --- |
| `mytts/engine.py`, `models.py` | Kokoro through ONNX Runtime, and the voice model download |
| `mytts/text.py` | Splitting text into sentences |
| `mytts/player.py`, `audio.py`, `audiodevice.py` | Synthesis ahead of playback, audio output, following the default speaker |
| `mytts/capture.py`, `hotkey.py` | Copying the selection from other apps, and the global hotkeys |
| `mytts/ui/` | The reader window, settings, tray icon, themes, the single-instance channel |
| `packaging/` | The PyInstaller spec, the Inno Setup script, license notices, release assets |
| `tools/` | Scripts that make the README images and the demo |

[ROADMAP.md](ROADMAP.md) records how the app was built, milestone by milestone, with measurements and known limits.
