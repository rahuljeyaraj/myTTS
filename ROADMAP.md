# Roadmap

Work is split into milestones. Each one is finished, tested, committed and pushed before the next starts, so a new session can pick up from this file alone.

## Goal

A Windows app like FluentVoice Pro, but with natural offline voices:

- Select text in any window, press a global hotkey: the reader window opens and starts reading.
- Play, pause and stop. The sentence being spoken is highlighted. Clicking a sentence jumps speech there.
- Voice picker and speed control in the same window. The window can stay on top.
- Minimalist design that is easy on the eyes.

## Milestones

### M1: Offline voice engine and repo (done)

- Kokoro-82M through `kokoro-onnx`. The user wanted Google's Read Aloud voices offline, but those run on Google's servers, so Kokoro is the closest offline equivalent.
- `mytts/models.py`: model registry with pinned sizes and SHA-256, plus a resumable, verified download to `%LOCALAPPDATA%\mytts\models`.
- `mytts/engine.py`: `Engine.synthesize(text, voice_id, speed)` returns 24 kHz mono float32 audio. It offers 41 voices; Japanese and Mandarin are excluded because they need the `misaki` G2P package.
- `mytts/text.py`: `normalize()` cleans text and unwraps hard-wrapped PDF/email lines. `segment()` splits it into sentences with character offsets into the normalized text (for highlighting) and a cleaned `speech` string. Sentences longer than 220 characters are split at clauses.
- CLI: `python -m mytts download | voices | say`.
- Tests: `tests/test_text.py`.

Measured on the dev machine: the model loads in about 1.3 s. The first synthesis call takes about 2 s (warm-up); after that it runs at about 0.25× real-time (1 s of compute for 4 s of audio).

### M2: Reader window and playback (done)

- `mytts/player.py`:
  - `Playback` holds the logic and does not use Qt, so tests drive it directly. `Player` is a QObject wrapper that turns its events into the signals `ready(voices)`, `segment_started(i)`, `state_changed(State)`, `finished` and `error(str)`, delivered on the GUI thread.
  - A worker thread loads the engine, warms it up with a throwaway phrase (skipped when a real sentence is already waiting), then keeps the current segment and the next 2 synthesized. It keeps 2 behind for an instant "previous". The cache key is (index, voice, speed). Results that arrive after the text changed are dropped. While stopped, only the first segment is pre-synthesized.
  - Audio goes through a PortAudio callback stream at 24 kHz (`latency="low"`). Commands only change state under a lock, so the callback acts on them within one block. Interrupted audio fades out over 8 ms, and resuming fades back in. When paused or stopped, the callback stops the stream (`CallbackStop`), so an idle app does not hold the audio device. Every fresh play re-initializes PortAudio (about 30 ms), so it follows the current default output device. If 24 kHz is refused, audio is FFT-resampled to the device rate.
  - States: stopped, loading (playing but waiting for synthesis), playing, paused. Clicking a sentence plays from there. Left and Right while paused move the highlight and stay paused. Stop goes back to the start. A voice or speed change restarts the current sentence. Gaps are 120 ms between sentences and 350 ms before a new line or paragraph.
- `mytts/ui/reader.py`:
  - `TextView` is a read-only `QTextEdit` with 160% line height, limited to about 72 characters per line and centered in wide windows.
  - The current sentence and the hover sentence are shown with `setExtraSelections`. Hit-testing uses `hitTest(..., ExactHit)`, so empty space is not clickable.
  - Python offsets are converted to Qt's UTF-16 positions, so emoji don't shift the highlight.
  - Auto-scroll is smooth and pauses for 3 s after the user scrolls.
  - `ReaderWindow` has the transport buttons, status ("3 / 12", "Preparing speech…", errors), voice combo with language separators, speed slider with a 300 ms debounce (double-click the value to reset), theme button and pin button.
  - `ReaderWindow.load_text(raw)` is the entry point M3 will use for captured selections.
- `mytts/ui/theme.py`: dark and sepia palettes, the stylesheet, the icon-font glyphs (Segoe Fluent Icons, then Segoe MDL2 Assets, then plain symbols), and the DWM title bar (dark mode attribute 20, plus caption, text and border colors on Windows 11). The Fusion style is used so the stylesheet looks the same on every Windows version. The combo box chevron is painted from the icon font, because stylesheets need an image file for it.
- Pin uses `SetWindowPos(HWND_TOPMOST)`, because changing Qt's window flag hides and re-shows the window.
- Keyboard: Space, Esc, Left/Right, Ctrl+V (paste and read), Ctrl+C (copy selection), Ctrl+= / Ctrl+- / Ctrl+0 and Ctrl+wheel (text size 9 to 28 pt).
- CLI: `python -m mytts` opens the window. `python -m mytts open [TEXT|-]` opens it and reads TEXT.
- Tests: `tests/test_player.py` (fake engine and stream, callback driven by hand) and `tests/test_reader.py` (offscreen Qt); 31 tests in total.

Measured on the dev machine (default device: USB speakers through MME, which accepts 24 kHz):

- The window appears at once. The engine is ready about 2.2 s later, imports included.
- With the first sentence pre-synthesized, the first audio block is produced about 0.16 s after `play()`, including the PortAudio re-init. The device adds about 93 ms of output latency.
- Callback blocks are 320 frames (13 ms). Pause and stop take effect in the next block.
- Jumping to a sentence that isn't cached takes about 0.8 s before audio starts; a speed change takes about 0.4 s.

Known limits: if the output device disappears mid-sentence, playback recovers only on the next play or resume. (Fixed later when Windows picks a new default; see "Follow the default speaker".)

### M3: Hotkey, selection capture, tray and settings (done)

- `mytts/hotkey.py`: hotkeys are written like Qt shortcuts ("Ctrl+Alt+Space"). `parse()` and `to_text()` convert them; a hotkey needs Ctrl, Alt or Win. `HotkeyThread` calls `RegisterHotKey` (with `MOD_NOREPEAT`) on its own thread with a `GetMessageW` loop; `set()` posts a thread message to re-register, and `set(None)` releases the hotkey. `GlobalHotkey` is the QObject wrapper with `activated` and `status(hotkey, error)` signals. A taken hotkey reports "… is already used by another app."
- `mytts/capture.py`: `capture_selection(restore)` returns the text, `""` if something without text was copied, or `None` if nothing was copied. The polling logic runs against a `ClipboardSystem` protocol, so tests use a fake.
  - It waits up to 1 s for the modifiers to be released. Modifiers still held after that are released (key-up events) while Ctrl is down.
  - It saves every memory-backed clipboard format, not only text: up to 64 MB in total. GDI-handle formats, the private range, and OLE's `DataObject` / `Ole Private Data` are skipped. CF_TEXT and CF_OEMTEXT are skipped when Unicode text exists, because Windows derives them again. Images survive through CF_DIB.
  - It sends Ctrl+C, or Ctrl+Insert in terminals (conhost, Windows Terminal, mintty, PuTTY, ConEmu), because Ctrl+C there interrupts the running program when nothing is selected. A test confirmed this: an injected Ctrl+C sends SIGINT to a console program, and Ctrl+Insert does not. Ctrl+Insert copies the selection in conhost and in Windows Terminal (tested in both).
  - It polls `GetClipboardSequenceNumber` for up to 600 ms, then reads `CF_UNICODETEXT` and restores the saved formats. The restore also sets `CanIncludeInClipboardHistory=0` and `CanUploadToCloudClipboard=0`, so it doesn't add a duplicate to Win+V history.
  - The clipboard owner is a message-only window, because SetClipboardData with a NULL owner is documented to fail. Restored data stays readable by other processes after that window is destroyed (tested).
- `mytts/settings.py`: `Settings` dataclass saved to `%APPDATA%\mytts\settings.json` with an atomic write. A damaged file, an unknown key or a value of the wrong type falls back to the default for that field. Start with Windows is not stored there: `mytts/autostart.py` reads and writes the HKCU Run value directly, so the two can't disagree. Outside an installed package, the Run command is `pythonw -c "…sys.path.insert(0, <checkout>)…" --tray`, because Run entries have no working directory. `refresh()` at startup rewrites it if the checkout or venv moved.
- `mytts/ui/app.py`: `App` owns the window, tray, hotkey, settings dialog and model download.
  - Captures run on a worker thread, one at a time.
  - Closing the window pauses and hides it to the tray. The first time, a tray balloon explains this.
  - Settings are saved 600 ms after a change and again on quit.
  - On Windows sign-out (`commitDataRequest`), the window stops hiding on close, so it never blocks sign-out.
  - If the model is missing, the window is shown even with `--tray`, and the download needs a click (354 MB).
- `mytts/ui/tray.py`: menu Show reader, Read selection (with the hotkey in the shortcut column), Play/Pause/Resume, Stop, Settings…, Quit, themed like the reader. Left click shows the reader; middle click plays or pauses. Read selection from the tray first gives the focus back to the app the user was in: `native.previous_app_window()` walks the Z-order and skips our windows, the shell, tool windows and cloaked windows. It then waits 150 ms before copying.
- `mytts/ui/instance.py`: a named mutex (`Local\mytts-<user hash>`) decides which process is first. That process listens with `QLocalServer` (user-only access). A later launch sends one JSON line (`show`, `open` + text, `tray`, `quit`) and waits for an `ok` reply.
- `mytts/ui/settings_dialog.py`: hotkey recorder (the global hotkey is released while recording, so the keys reach the dialog), plus switches for restore clipboard, keep on top and start with Windows. `Switch` is a painted toggle.
- `mytts/ui/native.py`: `bring_to_front()` uses `AttachThreadInput` when `SetForegroundWindow` alone is refused. `enabled()` is false under the offscreen test platform, so tests never touch real windows.
- `mytts/ui/icon.py`: the app icon, drawn with QPainter (sound-wave bars on an amber tile).
- Reader window: settings button, model-download strip (`ModelNotice`), `preferences_changed` and `closed_to_tray` signals. A saved voice that no longer exists falls back to the default.
- CLI: `--tray` starts hidden. `python -m mytts quit` closes the running copy.
- `pyproject.toml` now lists the `mytts.ui` package as well.
- Tests: 75 in total. They cover settings, hotkey parsing and registration conflicts, capture logic, single instance (the client runs in a subprocess, as a real second launch does), and app flows (capture, close to tray, tray menu, persistence, download, settings dialog, autostart Run key).

Measured on the dev machine:

- Capturing a selection from another app took 35 ms. From hotkey to text in the reader took 0.18 s, including the first show of the window; speech started at 0.57 s.
- With nothing selected, the window appears after the 600 ms copy timeout.
- Tray Read selection: 0.19 s to text, including the 150 ms focus settle.
- A second launch that hands over its request and exits takes 0.42 s, mostly Python and Qt startup.
- The model download reports progress every 100 ms. Cancel keeps the `.part` file for resuming.

Known limits:

- Apps running as administrator can't be read (UIPI).
- The copied selection goes into Win+V history, because the source app writes it.
- Clipboard formats that are GDI handles (metafiles, palettes) are not restored.
- The VS Code integrated terminal can't be told apart from the editor (both are `Chrome_WidgetWin_1`), so pressing the hotkey there with nothing selected sends Ctrl+C.
- An app that is not responding when the clipboard is saved (delayed rendering) blocks the capture thread.

### M4: Install and polish (done, tagged `v0.1.0`)

- `install.ps1` installs for the current user, with no administrator rights. It runs again to update an existing install.
  - The install lives in `%LOCALAPPDATA%\mytts`, next to `models`: `venv`, `mytts.ico` and a copy of `uninstall.ps1`. mytts is installed into the venv as a package (not editable), so edits in a source checkout can't break the installed copy.
  - Python: it uses the newest 64-bit, not free-threaded CPython 3.10 to 3.13 registered under PEP 514 (`HK{CU,LM}\Software\Python\PythonCore\*\InstallPath`). It looks on PATH only if none qualifies, because on the dev machine PATH has PlatformIO's Python first. `-Python <exe>` overrides the choice. An existing venv is reused while it still works.
  - Steps: it closes a running copy of the install, upgrades pip, installs `requirements.txt`, then installs mytts with `--no-deps --force-reinstall` (so unchanged version numbers still update). It installs from a temporary copy of `mytts\`, `pyproject.toml`, `README.md` and `LICENSE`. pip builds in place, so installing the source folder directly would leave `build\` and `*.egg-info` there, and setuptools packages leftover files from `build\lib` into later wheels. Then it runs `mytts download` (a failure only warns), writes the icon, creates the Start menu shortcut and the Settings > Apps entry, and launches the shortcut.
  - The shortcut runs `venv\Scripts\pythonw.exe -m mytts` with the working directory set to the install folder. It carries the AppUserModelID `mytts.app` (`native.APP_ID`), which the app also sets for its process before any window. WScript.Shell can't set that ID, so the script uses inline C# (`IShellLinkW` + `IPropertyStore`). Tested: without a shortcut that has this ID, the tray notification is labelled "Python"; with it, "mytts" with the app icon. Pinning to the taskbar should relaunch through the shortcut for the same reason, but that was not tried by hand.
  - Settings > Apps: `HKCU\...\Uninstall\mytts` with the version, icon, size, and `NoModify`/`NoRepair`. Its UninstallString runs the copied `uninstall.ps1`, so uninstalling doesn't need the source folder.
  - `-Startup` writes the Run entry through `autostart.set_enabled(True)`, so it matches what the app writes. Other options: `-NoModel` and `-NoLaunch`. From an elevated window it warns and doesn't launch (the app would run elevated).
- `uninstall.ps1` first closes the installed copy: `mytts quit`, then it waits for processes whose path is in the venv and kills them after 10 s. It then removes the Run entry (only if it points into the install), the shortcut, the Apps entry, the venv, the icon and the voice model. Settings stay unless `-RemoveSettings` is given; `-KeepModel` keeps the model. It changes the process's current directory to `%TEMP%` first, because Windows can't delete a folder that is a process's current directory.
- A venv's `pythonw.exe` is a launcher: the app runs in a child, the base `Python310\pythonw.exe`. Waiting on the launcher is enough, because it exits with its child.
- `mytts quit` now waits until the running copy has released its mutex (`instance.is_running()` / `wait_until_gone()`, using `OpenMutexW`), up to 10 s.
- `mytts/ui/icon.py` draws on a `QImage`, so no `QGuiApplication` is needed. `ico_bytes()` / `save_ico()` write a .ico with 9 sizes: 32-bit BMP with an AND mask below 256 px, PNG at 256 px. Checked with Win32 `LoadImage` at every size. .NET's `System.Drawing.Icon` skips PNG entries, so don't use it to check.
- `tools/screenshots.py` regenerates `docs/*.png`. It drives the real app on the desktop with a silent stream whose callback is pumped by hand, so the reader stays mid-sentence. It captures the DWM extended frame bounds with corner rounding turned off.
- `pyproject.toml`: the license is now the SPDX string `"MIT"` (setuptools>=77); the old table form printed deprecation warnings during install.
- README: install, update and uninstall instructions, and screenshots. Version `0.1.0`.
- Tests: 85 in total. New tests cover the .ico layout, AND mask and pixel round-trip; `is_running`; `quit` waiting for a server process; the scripts being ASCII and parsing in Windows PowerShell; and the installer's app ID and Python range matching the code. `test_register_conflict_and_release` used to fail about 1 run in 10, because releasing a hotkey happens on its own thread and reports nothing. The test now retries until the release has taken effect (60 of 60 runs passed).

Measured on the dev machine:

- First install with dependencies in pip's cache and the model already present: 70 to 76 s. Updating with the app running: 10 s, closing and relaunching included. The install is 757 MB, of which the model is 354 MB.
- The window is visible 0.64 s after the Start menu shortcut is clicked.
- `mytts quit` returns after 0.40 s, and the processes are gone 30 ms later. Uninstalling with the app running takes 4.5 s.
- Install, update, `-Startup`, uninstall with `-KeepModel`, and the default uninstall were all run for real. The default uninstall ran against sandboxed `LOCALAPPDATA`/`APPDATA` so the real model was kept.

Known limits:

- Installing needs internet access and an installed Python 3.10 to 3.13; nothing is bundled. Updates are manual (`git pull`, then run `install.ps1` again).
- The installed copy and a source checkout share the settings file and the single-instance lock, so only one of them runs at a time.

## After v0.1.0

### Hotkey pause and next/previous hotkeys (done)

- The read hotkey toggles: while playing or loading it pauses (without copying anything). While paused it copies the selection first: if it is missing or the same as the text in the reader (compared after `normalize()`), it resumes; if it is different text, that text is read from the start. When nothing is loaded or playback is stopped, it reads the selection as before.
- New global hotkeys: Next sentence (`Ctrl+Alt+Right`) and Previous sentence (`Ctrl+Alt+Left`), settings `next_hotkey` / `prev_hotkey`. They call `player.next()` / `prev()`, so while paused they move the highlight and stay paused, and while stopped they do nothing. They don't bring the window to the front.
- `HotkeyThread` now holds several named hotkeys (`set(name, hotkey)`, `suspend(on)`), each with its own `RegisterHotKey` id on the same thread. Signals carry the action name. Two actions with the same keys report "… is already used for Read selection."
- `settings.HOTKEYS` maps action name to settings field and label; the settings dialog has one recorder row per action. While any row is recording, every hotkey is released.
- Tests: 90 in total. Checked on the dev machine that `Ctrl+Alt+Right` and `Ctrl+Alt+Left` register and fire on real (injected) key presses.

### Follow the default speaker (done)

- Bug: after Bluetooth headphones connected, mytts kept playing on the old speaker until the user re-selected the default in Sound settings. PortAudio picks its default device at initialization and a stream stays on the device it was opened on. Only a fresh play from Stopped re-initialized it; resume and clicking a sentence while paused restarted the old stream.
- `mytts/audiodevice.py`: `DefaultOutput` reads the default render endpoint id (eRender, eConsole) through the MMDevice API with plain ctypes COM calls. `DeviceWatcher` polls it every 0.5 s on its own thread (COM in MTA) and calls back once a new id has been seen on two polls in a row. A one-poll flap is ignored, and so is having no output device at all; the device that comes back is reported.
- `Player` owns the watcher (only when it uses the real sound card stream) and passes the change to `Playback.device_changed()` on the GUI thread. While playing, the stream is closed and reopened on the new default (PortAudio re-init included). The playhead steps back by the old stream's output latency, since that audio was lost with the old device, and fades in. While paused, the stream is marked stale and the next resume opens a new one. If opening fails, playback pauses with "Could not switch to the new audio device: …", and resume tries again.
- This also covers a device that disappears mid-sentence, as long as Windows moves the default to another device.
- Tests: 95 in total (device switch while playing, while paused, before any playback, failed switch, watcher debounce).

Measured on the dev machine, switching the default between the USB speakers and a monitor's HDMI audio through `IPolicyConfig` while playing silence: the stream followed within one or two polls, and the switch itself took 77 ms. After a change made while paused, resume opened on the restored default. Reading the default endpoint takes about 4.5 ms of wall time and no measurable CPU in the process.

## Going public (plan)

Goal: release mytts for free on GitHub as a Windows installer (`mytts-setup-<version>.exe`) that needs no Python, in a repo that looks professional. The repo stays private until the user has reviewed everything (M10). It is made public only when the user says so (M11).

### Decisions

1. **The voice model (decided):** the installer downloads it during setup (354 MB, SHA-256 checked) and reuses it on updates, so the installer stays at about 70 to 100 MB. The reader window keeps its download button as a fallback.
2. **The name (decided): myTTS.** This is the display name everywhere people see it: the window title, tray, Start menu, Settings > Apps, installer, README and release names, and the GitHub repo name. Identifiers stay lowercase `mytts` so existing installs and data carry over: the Python package and `python -m mytts`, the `mytts` command, `%LOCALAPPDATA%\mytts` and `%APPDATA%\mytts`, the AppUserModelID `mytts.app`, and the mutex name. Windows file names are not case-sensitive, so the exe is `myTTS.exe` and the installer is `myTTS-setup-<version>.exe`. The display name change is done in M6.
3. **The version (decided): `1.0.0`** for the first public release.
4. **The comparison with FluentVoice Pro (checked in M10):** see M9 and M10. The user may add more issues they noticed. Each one is checked against the current version first.

### M5: Private data audit of the whole history (done)

Making the repo public publishes every commit, tag and file that ever existed, not only the current tree.

Result (2026-11-26): **nothing private was found, so no history rewrite was needed.** What was scanned, as of commit `43b885e`:

- **Refs:** 8 commits, one branch (`main`), one annotated tag (`v0.1.0`), no stashes. The remote has the same two refs and nothing else.
- **Identity:** every author, committer and the tagger is `rahuljeyaraj <19166091+rahuljeyaraj@users.noreply.github.com>`. The timestamps carry the `+0530` time zone, as all git commits do; that was accepted.
- **Paths:** `git log --all --name-only` lists only the 45 files in the current tree. No file was ever deleted, so there is no hidden history.
- **Secrets:** `gitleaks git --log-opts=--all` (gitleaks 8.30.1, installed with winget): 8 commits, no leaks. A `gitleaks dir` scan of the working folder found 9 false positives, all in third-party packages inside the ignored `.venv`.
- **Personal data:** `git grep` over every revision for the real email, `gmail`, the real name, any email domain, `C:\Users` and `/c/Users` paths, the short home path `RAHULJ~1`, the machine name, IPv4 addresses, phone-number shapes, `gho_`/`ghp_`/`github_pat_` tokens, `password`/`secret`/`token`/`api key`/private keys/`.env`/`credential`. The only hits are the public GitHub username (LICENSE, README clone URL), this roadmap's own wording, COM GUIDs in `install.ps1` and the word "token" in `text.py`.
- **Binaries:** the three `docs/*.png` (one version each in history) show only the app window with sample text. Their chunks are `IHDR`, `pHYs`, `IDAT` and `IEND`: no text, EXIF or time metadata, so nothing to strip.
- **Commit messages:** all 8 read in full. They describe the code only.
- **GitHub (REST API):** the repo is private. Releases, Actions runs and artifacts, issues, pull requests, commit comments, deploy keys, webhooks, environments, deployments, Actions/Dependabot/Codespaces secrets and variables are all empty. The wiki and Pages are off. The only collaborator is the owner, with no pending invitations.
- `*.code-workspace` is now in `.gitignore`.

M10 runs this scan again over the commits made after it. To repeat the scan: `gitleaks git . --log-opts=--all --redact`.

### M6: Self-contained build (done)

`packaging\build.ps1` builds `dist\myTTS\myTTS.exe`, which runs without Python. Result (2026-11-26):

- **PyInstaller 6.22.3, one-folder mode** (pinned in `packaging/requirements-build.txt`), spec `packaging/mytts.spec`, entry script `packaging/launcher.py` (PyInstaller needs a script; `mytts/__main__.py` uses relative imports). Defender (`MpCmdRun -Scan -ScanType 3`) found no threats in the build, so Nuitka was not needed.
- **What the spec adds by hand:** `espeak-ng.dll` (loaded by path with ctypes) and `espeak-ng-data`, `kokoro_onnx/config.json`, and the `kokoro-onnx` package metadata (it logs its own version through `importlib.metadata`). The contrib hooks already handle onnxruntime and sounddevice (PortAudio). phonemizer's `share` folder is for its festival and segments backends and is not needed. At run time phonemizer copies `espeak-ng.dll` to a temp folder per process, as it does under Python; the copy is removed when the app exits normally.
- **Left out:** all Qt plugins except `platforms/qwindows.dll`, the Qt translations, `opengl32sw.dll` and unused Qt DLLs, Qt's OpenSSL 3 (only its TLS plugin used it; Python's `_ssl`, used for the model download, links to OpenSSL 1.1, which stays), and `tkinter`, `sympy`, `mpmath`, `setuptools`, `pygments`, `coloredlogs` and the onnxruntime tool packages. Only `QtCore`, `QtGui`, `QtWidgets` and `QtNetwork` (for `QLocalServer`) remain.
- **The exe:** windowed, with the app icon (written by `save_ico` at build time) and version info: product name myTTS, file and product version from `mytts.__version__`, the copyright line from `LICENSE`, original file name `myTTS.exe`.
- **Display name myTTS** (decision 2): window title, settings title, tray tooltip and notification, the download notice, `--version`, the install scripts' messages, the Start menu shortcut `myTTS.lnk` (deleted first, so an old `mytts.lnk` takes the new case), the Settings > Apps name, and the README prose. `mytts.DISPLAY_NAME` and `mytts.PROJECT_URL` hold them. Identifiers stay `mytts`.
- **Code changes:**
  - `paths.frozen()`, `exe_path()`, `logs_dir()`, `licenses_dir()` (the `licenses` folder next to the exe, which M7 adds) and `download_command()`.
  - `autostart.command()` in the exe is `"<path>\myTTS.exe" --tray`. As before, starting any copy re-points an enabled Run entry at itself (`autostart.refresh()`).
  - `mytts/logs.py`: every start logs to `%LOCALAPPDATA%\mytts\logs\mytts.log` (1 MB, 2 backups; `crash.log` next to it receives faulthandler dumps of native crashes). It logs the version and command (never the text being read), app start, the selection length, player state changes, hotkey and download errors, errors shown in the reader, and Qt's own warnings (`qInstallMessageHandler`). phonemizer's per-sentence "words count mismatch" warning is silenced. An unhandled exception on the GUI thread is logged and shown in a dialog that names the log file (one at a time, never under the offscreen test platform); in other threads it is only logged. PyInstaller's own error dialog stays on for failures before logging starts.
  - Console output: a windowed exe has no stdout or stderr. For the commands that print (`--version`, `--help`, `--self-test`, `quit`, `download`, `voices`, `say`) it attaches to the console of the terminal it was started from (`AttachConsole`). The reader never attaches, because closing that terminal would then close the app. Redirected output works too: bash, `cmd /c` and `Start-Process -Wait -RedirectStandardOutput` all get the output and the exit code. Without a console, output goes to `os.devnull`.
  - `--self-test`: loads PortAudio, Qt (with the real platform plugin) and the voice model, synthesizes one sentence without playing it, and fails if the audio is shorter than 0.5 s or silent. It prints timed steps and logs them.
  - Settings has an About section: name and version, a tagline, and links to the project page, the MIT license, the third-party licenses (the local `licenses` folder when there is one, otherwise `THIRD_PARTY_NOTICES.md` in the repository, which M9 adds) and the log folder.
- Tests: 113 in total. New: frozen paths and Run command, the log file and both exception hooks, the error dialog skipped offscreen, console streams never left as `None`, `--self-test` passing, and failing on silent audio (fake engine), the About section, the spec compiling, and `build.ps1` being ASCII and parsing.

Measured on the dev machine:

| | Python install (`install.ps1`) | myTTS.exe |
|---|---|---|
| Size on disk, without the 354 MB model | 426 MB venv, plus an installed Python | 141 MB, 501 files |
| Window visible after launch (warm, 3 runs) | 0.66 to 0.79 s | 0.58 to 0.69 s |
| Launch with text to first speech (warm, source run for Python) | 2.8 s | 2.5 s |

With the app running, the hotkey over a Notepad selection started speech 0.99 s after the key press (the copy itself took 36 ms). The first launch of a fresh build took 1.97 s (cold disk cache and Defender's first scan). A build takes 65 to 75 s. `--self-test` takes 3.0 to 3.5 s warm (model load 1.7 s, first sentence 1.2 s).

How it was tested: **Windows Sandbox is not enabled on the dev machine** (turning on the Windows feature needs administrator rights and a restart), so the clean-machine test ran on the dev machine instead. The exe was started with `PATH` set to the Windows folders only and every `PYTHON*`, `QT_*` and `VIRTUAL_ENV` variable removed. None of the 148 modules it loaded came from outside the build folder and `C:\Windows`, except phonemizer's temp copy of the bundled `espeak-ng.dll`. Then, on the real desktop: the reader window opened; Ctrl+Shift+X over a Notepad selection (injected key presses) read it, Ctrl+Shift+Right moved on and Ctrl+Shift+X again paused, as the log shows; the tray icon was found through UI Automation in the hidden-icons flyout with the tooltip "myTTS · Ctrl+Shift+X reads the selection"; `myTTS.exe quit` closed it in about 1 s; and the Run entry the app wrote (`"...\myTTS.exe" --tray`), started from `C:\Windows\System32`, started it in the tray with no window. The Run entry and the settings were put back to the Python install afterwards.

Still to do, in M7: the same checks in Windows Sandbox, together with the installer tests. The user turns the feature on first (Turn Windows features on or off > Windows Sandbox, then restart).

### M7: Windows installer (done)

`packaging\build.ps1 -Installer` builds `dist\myTTS-setup-<version>.exe` with Inno Setup 6.7.3 (`winget install JRSoftware.InnoSetup`, per user). Result (2026-11-26):

- **Script:** `packaging/mytts.iss`. `packaging/installer_assets.py` writes `build\installer\defines.iss` (version, display name, app id, publisher, copyright line, default hotkey, and the model files' URL, size and SHA-256, all read from the Python code) plus the setup icon and the wizard images drawn from the app icon. The script stops with an error if `dist\myTTS\myTTS.exe` has a different version than `mytts.__version__`. `WizardStyle=modern dynamic` follows the Windows light or dark mode.
- **Install:** per user, no administrator rights, `%LOCALAPPDATA%\Programs\mytts` (`{autopf}` in non-admin mode). `AppId=mytts`, so the Settings > Apps key is `mytts_is1`, separate from install.ps1's `mytts`. The folder page shows on the first install only. `[InstallDelete]` empties `_internal` and `licenses` first, so files an older build had and a newer one doesn't can't linger and be loaded (checked with a planted file).
- **Shortcuts and tasks:** Start menu `myTTS.lnk` with the AppUserModelID `mytts.app` (read back through the shell: `System.AppUserModel.ID` is `mytts.app`). Tasks: desktop shortcut, and "Start myTTS when I sign in to Windows", which writes the same Run entry the app writes (`"<app>\myTTS.exe" --tray`; a test checks the format). `UsePreviousTasks=no`: each task starts ticked when it is set now (the Run entry or the desktop shortcut exists), and unticking one removes it. A silent install keeps what is set; `/TASKS=` can add to it. The finish page offers "Launch myTTS".
- **Voice model (decision 1):** on clicking Install, if `kokoro-v1.0.onnx` or `voices-v1.0.bin` is missing or has the wrong size (the app's own check), a download page fetches the missing files into setup's temp folder with Inno's SHA-256 check. They are moved into `%LOCALAPPDATA%\mytts\models` after the files are installed. When the download fails or is stopped, a dialog offers "Try again" or "Install without it"; a silent install continues without it. The app then shows its download button.
- **Updates:** before replacing files, setup runs `myTTS.exe quit` (which waits for the app to exit). After a silent update it starts myTTS again with `--tray` if it closed a running copy; an interactive update offers "Launch myTTS".
- **Replacing an install.ps1 copy:** if `HKCU\...\Uninstall\mytts` exists, setup runs that copy's `uninstall.ps1 -KeepModel` (hidden) in `PrepareToInstall`, and stops with a message if the key is still there afterwards. Whether "Start with Windows" was on is read when setup starts, so the setting carries over to the new exe. `install.ps1` now refuses to run while `mytts_is1` exists, and the README calls it "install from source (for developers)".
- **Uninstall:** `[UninstallRun]` runs `myTTS.exe quit`. It removes the program, the shortcuts, the Run entry (only when it starts this copy) and `%LOCALAPPDATA%\mytts\logs`. It asks "Also remove the voice model?" ("Remove the voice model" / "Keep it"); a silent uninstall keeps it. `%LOCALAPPDATA%\mytts` is removed when nothing is left in it. Settings are kept.
- **Run entry and dev builds:** `autostart.refresh()` now only re-points an enabled Run entry from an installed copy: myTTS.exe with an `unins*.exe` next to it (`paths.installed_by_setup()`), or mytts installed into a venv. A build in `dist\myTTS` or a source checkout leaves it alone. Turning the setting on from such a copy still points the entry at it.
- **Licenses:** `packaging/notices.py`, called from the spec after COLLECT, fills `dist\myTTS\licenses`: `myTTS-LICENSE.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt`, `Apache-2.0.txt` and `PortAudio.txt` (kept in `packaging/licenses/`), each bundled package's own license files (found by mapping the modules and files PyInstaller collected to their distributions), Python's `LICENSE.txt` (which covers OpenSSL, libffi, bzip2 and the rest), PyInstaller's `COPYING.txt` for the bootloader, and `THIRD_PARTY_NOTICES.md`. The same notices file is written to the repository root. Bundled: cffi, cloudpickle, dlinfo, espeakng-loader (its MIT license is vendored, because the wheel has none), joblib, kokoro-onnx, numpy, onnxruntime, phonemizer (GPL-3.0+), pyreadline3, PySide6 and shiboken6 (LGPL-3.0), sounddevice, typing_extensions, Python 3.10.11, Qt 6.12.0, eSpeak NG 1.52.0, PortAudio V19.7.0 and the PyInstaller 6.22.3 bootloader. The notices say the installer as a whole is distributed under GPL-3.0 terms, the source stays MIT, and the Qt DLLs are separate files in `_internal\PySide6`.
- **eSpeak NG source:** espeakng-loader 0.2.4's `espeak-ng.dll` reports 1.52.0. Its build workflow clones the upstream tag `1.52.0` (commit `4870adfa25b1a32b4361592f1be8a40337c58d6c`) and builds it with CMake, without patches. `notices.ESPEAK_SOURCE` maps the version to that tag and commit, and the build fails on a version it doesn't know, so a dependency update can't silently change what M8 must attach.
- **Smaller build:** the spec now keeps only `libportaudio64bit.dll` from sounddevice's PortAudio binaries (it also had the 32-bit, ARM64, ASIO and macOS builds). That also keeps the ASIO SDK out of the bundle.
- Tests: 120 in total. New: the assets and defines match the code (model URL, sizes, hashes, app id, version; image sizes), the Run entry's format and key, the script being ASCII and compiling (`ISCC /O-`, syntax only, about 0.1 s; skipped without Inno Setup or a build), the bundled-distribution mapping, the eSpeak NG version being known, every license file named in the notices existing, `installed_by_setup()`, and `refresh()` leaving the entry alone from a dev copy.

Measured on the dev machine:

- The installer is 40 MB (the build is 140 MB). Compiling it takes about 55 s (`lzma2/ultra64`, solid), after the 56 to 63 s PyInstaller build.
- Interactive upgrade over the install.ps1 copy: 10 s from Install to the finish page, removing the old copy included.
- Silent update over the installed copy while it ran: 5.1 s, and it was running again in the tray 4 s later. Silent uninstall with the app running in the tray: 4.1 s.
- Model download inside setup: 60 s for 354 MB (55 s and 5 s for the two files). `myTTS.exe download --verify` passed on the result, and `--self-test` of the installed exe passed (model load 2.1 s, first sentence 1.1 s).

How it was tested: **Windows Sandbox is still not enabled**, so every test ran on the dev machine, driven with UI Automation (`BM_CLICK` posted to the wizard's buttons, `PrintWindow` for screenshots). In order:

1. An interactive upgrade over the install.ps1 copy. The old shortcut, Apps entry and venv were removed; the model, settings and Start with Windows were kept, with the Run entry now on the exe.
2. The read hotkey on a Notepad selection with the installed copy: it read, then paused.
3. A silent upgrade with the app running and a planted stale file.
4. Starting through the Run entry's command (tray, no window), then a silent uninstall (model kept).
5. A fresh interactive install with no model: downloaded and verified.
6. An installer built with a broken model URL: "Download failed: 404 Not Found"; "Try again" failed again; "Install without it" installed, and the app offered the download.
7. An interactive uninstall choosing "Remove the voice model".
8. A fresh silent install, then a silent update that restarted the tray copy, and `install.ps1` refusing while the setup copy was installed.

Afterwards the machine was put back as it was: the install.ps1 copy with Start with Windows on, and the settings file restored.

Not tested: a real sign-in starting the Run entry, pinning to the taskbar, and the wizard in dark mode (the machine uses light mode). The clean-machine runs in Windows Sandbox (no Python) move to M10, which tests the draft release's installer there anyway. The user turns the feature on first (Turn Windows features on or off > Windows Sandbox, then restart).

Notes for later:

- PowerShell 5.1's `Start-Process -Wait` also waits for child processes, so it hangs after a silent update that restarts the tray app. Scripts and CI should wait on the setup process itself (`$p.WaitForExit()`).
- The installer is unsigned; M8 explains the SmartScreen warning in the README.

### M8: CI and release pipeline (GitHub Actions) (done)

Result (2026-11-26):

- **`.github/workflows/ci.yml`:** on every push to `main`, every pull request and by hand. Two jobs on `windows-latest`: Python 3.10 with the exact versions a release is built with (`packaging/requirements-lock.txt`), and Python 3.13 with the newest versions `requirements.txt` allows plus the pinned PyInstaller (one test imports it), so a breaking upstream release shows up there first. pip is cached. Each job takes 1 to 2 minutes.
- **`.github/workflows/release.yml`:** on a `v*` tag. The build job (`windows-2025`, Python from `packaging/.python-version`, no pip cache) checks that the tag is `v` + `mytts.__version__`, installs the lock file and runs `pip check` and the tests, restores the voice model from the Actions cache (key from the two SHA-256s; on a miss `python -m mytts download`; always `download --verify`), installs Inno Setup 6.7.3 from its GitHub release after checking a pinned SHA-256, runs `build.ps1 -SelfTest -Installer`, fails if the build changed `THIRD_PARTY_NOTICES.md` (the tagged source must already list what ships), runs `packaging/release.py assets` and uploads `dist/release` as an artifact. A separate `draft` job on `ubuntu-latest` is the only one with `contents: write`; it runs no repository code and calls `gh release create --draft --verify-tag`. Nothing is published automatically. Run by hand, the workflow builds the same files without a tag; with the `draft` input it also makes a draft on a throwaway tag name `test-<run number>` (a draft creates no tag) to delete afterwards.
- **`packaging/release.py`:** `check-tag`, and `assets`, which writes `assets/` (the installer, `espeak-ng-<version>.tar.gz`, the phonemizer sdist, `SHA256SUMS.txt` in `sha256sum -c` format) and `notes.md`. The eSpeak NG version is read from the bundled DLL and mapped through `notices.ESPEAK_SOURCE`; the source is fetched by tag, the fetched commit must equal the recorded one, and `git archive` packs it (the archive came out byte for byte the same on the runner as on the dev machine). The phonemizer sdist comes from PyPI and is checked against PyPI's SHA-256. The notes are the version's section of `CHANGELOG.md`, then install steps, the SmartScreen explanation (More info > Run anyway), `Get-FileHash` with a table of SHA-256s, and where the source is.
- **`CHANGELOG.md`** (Keep a Changelog) started, with `Unreleased` and `0.1.0`; M9 polishes it. A test requires a section for the current `__version__`, so a version bump needs its notes.
- **`packaging/requirements-lock.txt`:** exact pins of the app's dependencies and theirs, the build tools and pytest, as in the dev venv. Tests check that it satisfies `requirements.txt`, `pyproject.toml` and `requirements-build.txt`. `packaging/.python-version` (`3.10.11`) is the release's Python.
- **Actions pinned to commit SHAs** with a `# vX.Y.Z` comment (checkout 7.0.1, setup-python 7.1.0, cache 6.1.0, upload-artifact 7.0.2, download-artifact 8.0.2); a test checks this, that both workflows default to `contents: read`, and that the release only ever creates drafts. Checkouts don't keep the token (`persist-credentials: false`).
- **`.github/dependabot.yml`:** weekly, pip in `/packaging` only (the lock and the build pins; `requirements.txt` and `pyproject.toml` keep their ranges), minor and patch updates grouped, and GitHub Actions grouped.
- README: downloading from the latest release, the SmartScreen warning and `Get-FileHash`, and a Releases section for developers. The notices now say the phonemizer source is attached too.
- Tests: 133 in total.

How it was tested: CI on the pushed commits (the first run caught the missing PyInstaller on 3.13). Then the Release workflow by hand with `draft` on: everything passed in 3 min 47 s, including a cold model download (354 MB in about 3 s) and the self-test on the runner (no audio devices, Qt's real `windows` platform; first sentence synthesized in 2.0 s). The draft had the four files; they were downloaded through the API and `sha256sum -c SHA256SUMS.txt` passed, and both source archives unpack. The test draft was deleted and left no tag. `release.py assets` was also run on the dev machine against a local build.

Notes for later:

- **Python 3.10 reached end of life in October 2026**, and it holds the release back: numpy 2.3+ and onnxruntime 1.24+ need Python 3.11+, so the lock stays on numpy 2.2.6 and onnxruntime 1.23.2. Dependabot's first pull request (#1) proposed numpy 2.5.5 and onnxruntime 1.32.0 and failed CI on 3.10; `packaging/.python-version` now makes Dependabot skip versions that need a newer Python. #1 is still open with the old proposal: close it, or comment `@dependabot recreate` on it, and the next run proposes only versions that work on 3.10. **Decision for the user before 1.0.0:** move the build to Python 3.13 (supported until 2029). That means a new lock, a rebuilt and re-measured exe, `python313.dll` in the notices, and `install.ps1`'s range checked.
- The installer is still unsigned; free signing (SignPath) is in M11.
- Workflow runs on a private repo use Actions minutes (Windows counts double); a release run is about 4 minutes.

### M9: A professional repo (done)

Result (2026-11-26):

- **README** rewritten for people who use the app: the icon, name and tagline, badges (latest release, downloads, CI, license, Windows 10/11), the demo GIF and a **Download myTTS for Windows** link to the latest release at the top. Then features, screenshots, install, hotkeys, the reader window, settings, an FAQ (SmartScreen and checking the SHA-256, privacy, offline use, languages, elevated windows, system requirements, where files live, complete uninstall, the command line), Background, the comparison, Development, Credits and License. The command line section now uses the installed `myTTS.exe` (the `Get-Clipboard | open -` example was dropped: stdin of the windowed exe is not tested). Developer material (install.ps1, builds, releases) moved to Development.
- **Background:** credits FluentVoice Pro by Nick Otmazgin and the Read Aloud Chrome extension's Google voices, with links (both checked: HTTP 200).
- **Comparison table:** against FluentVoice Pro **1.6.7** (released 2026-11-08) **as its README describes it**, which the table says. Rows: following along (sentence highlight and click to jump vs. a status line with part and time), voices, network, hotkey, install channels, Windows on ARM. It says where FluentVoice Pro does more (languages, online voices, install channels, ARM64). The status-while-preparing row was left out, as planned: its README describes one. **Not done: the hands-on check in Windows Sandbox**, which is still not enabled. Running someone else's app on the dev machine was not an option. M10 does it.
- **New files:** `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, the official text fetched from its repository; the contact is GitHub's private reporting form, so no email address is published), `CONTRIBUTING.md`, `SECURITY.md` (private vulnerability reporting, scope, what is by design), `.github/ISSUE_TEMPLATE/` (a bug report form with version, `winver` build, install type and the log location; a feature request form; a link to private security reports), `.github/pull_request_template.md`, `.editorconfig` and `.gitattributes` (`* text=auto eol=lf`, media and model files binary; renormalizing changed no existing file). `CHANGELOG.md` and `THIRD_PARTY_NOTICES.md` already existed (M7, M8).
- **Images:** `tools/screenshots.py` regenerated the three screenshots (the old ones showed the name "mytts" and an older settings window). At 125 % scaling with several monitors, `QScreen.grabWindow` was off by a row or two and caught the window behind, so the tools now grab exact physical pixels with GDI (`tools/screengrab.py`). The screenshot tool also covers the screen with a plain window in the theme's colour and uses window sizes that are whole device pixels.
- **Demo:** `tools/demo.py` drives the real app: an Edge app window (fresh profile in a temp folder: no tabs, account or bookmarks) shows a sample page; the pointer drags across two paragraphs; Ctrl+Alt+Space is sent (key caps are shown on screen); the reader reads; a click on sentence 5 jumps there; the hotkey pauses. A copy of myTTS with default settings runs beside the installed one (which uses another hotkey). The player's output goes to a recorder that pulls it in real time, so the sound track is exactly what was played and lines up with the video; nothing is heard. 15 fps lossless capture with the real pointer drawn in, then ffmpeg: `docs/demo.gif` (1024x576, 12 fps, 27 s, 0.6 MB) and `docs/demo.mp4` (1600x900, H.264 and AAC, 27 s, 1.0 MB; for LinkedIn). ffmpeg came from `pip install imageio-ffmpeg` in a scratch venv; it is not a project dependency. The tool takes over the main monitor for about a minute.
- **Social preview:** `tools/social_preview.py` draws `docs/social-preview.png` (1280x640, the icon and dark theme) and `docs/icon.png` for the README.
- **Repo settings (REST API):** renamed `mytts` to **`myTTS`** (decision 2; GitHub redirects the old URL, and `origin` now uses the new one), the description, the eight topics, homepage `https://github.com/rahuljeyaraj/myTTS/releases/latest`, Issues on, Wiki and Projects off.
- Tests: 156 in total. New `tests/test_repo.py`: the community files exist, every local link, image and `#anchor` in the Markdown files resolves, media is binary in git, the issue forms have their keys, and the Code of Conduct has a contact.

Measured: the running app (install.ps1 copy, model loaded, idle) uses 760 MB working set and 1.5 GB committed memory; the README says "about 0.8 to 1.5 GB".

Left for the user:

- **Upload `docs/social-preview.png` by hand:** Settings > General > Social preview > Edit > Upload an image. There is no API for it.
- **Code of Conduct contact:** reports go through the private vulnerability reporting form, which M11 turns on. To use an email address instead, replace that sentence in `CODE_OF_CONDUCT.md`.
- Still open from M8: the Python 3.13 decision before 1.0.0. Dependabot #1 is closed; #2 (a pip group update) is open.

### M10: Pre-launch review (done)

Result (2026-11-26). **Nothing is public: the repo is private and the release is a draft.**

- **Python 3.13 (the user's decision):** releases are built with Python 3.13.17, the last 3.13 with Windows builds (setup-python has it; 3.13.18 has none). New lock: numpy 2.5.5, onnxruntime 1.32.0 (which no longer pulls in sympy, mpmath, coloredlogs, humanfriendly or pyreadline3), setuptools 84.2.1 (PyInstaller needs it on 3.12+). Source installs: Python 3.11 to 3.13 (`pyproject.toml`, `install.ps1`; an existing 3.10 venv is rebuilt). CI: the lock on 3.13, the newest allowed versions on 3.11; `test_python_ranges_agree` keeps them in step. The same sentence synthesized on both stacks: same length, correlation 0.997. Python 3.13's `_ssl` uses its own `libssl-3.dll`; the spec still drops PySide6's `libssl-3-x64.dll`. The dev `.venv` was rebuilt on 3.13.17 (see Dev environment notes).
- **Measured on the dev machine:** the build is 157 MB, 542 files (was 141 MB); the installer 42 MB; warm `--self-test` 2.0 to 2.1 s (was 3.0 to 3.5 s): model load about 1.0 s, first sentence 0.76 s. README: "about 520 MB of disk space: 160 MB for the app".
- **Version 1.0.0**, CHANGELOG section dated 2026-11-26 (change the date in M11 if it is published later).
- **Bugs found and fixed:**
  - Notices: a license file was listed twice when a wheel has it both in `.dist-info/licenses` and in the package (numpy), and files in `.dist-info/licenses` whose names don't start with LICENSE were missed (numpy's `dragon4_LICENSE.txt`).
  - Found in Sandbox: `myTTS.exe quit` (run by the uninstaller and by setup) said "not running" when a copy had been started less than about a second before and had not taken the mutex yet. An uninstall right after a silent update (which restarts the app) then deleted the files under the running copy, and the next setup hung on that broken exe (PyInstaller's error dialog, unseen in a silent install). `quit` now waits up to 5 s for a copy of the same exe that is still starting (`instance.other_processes`, `wait_for_start`).
  - Found in Sandbox: `/TASKS=startup` and `/TASKS=desktopicon` did nothing in a silent install. Inno calls `CurPageChanged` in silent mode too, and the code that shows the current state on the tasks page unticked them. It now skips silent installs. (M7's "/TASKS= can add to it" had not been tested.)
- **Draft release:** tag `v1.0.0` on `7436b3b` (the first draft, from `eeae249`, was deleted and the tag moved after the two Sandbox fixes; nothing was public). Release workflow green. The draft "myTTS 1.0.0" has `myTTS-setup-1.0.0.exe` (44,623,061 bytes, SHA-256 `167271adb313872ac87328aa4ffe884e7b1d69cce292bab82186c6e94b0d2de5`), `espeak-ng-1.52.0.tar.gz`, `phonemizer-3.6.0.tar.gz` and `SHA256SUMS.txt`; downloaded through the API, `sha256sum -c` passed. 159 tests.
- **Windows Sandbox (Windows 24H2 build 26100, no Python, no Visual C++ runtime), with the draft's installer:** hashes match; the installer is unsigned; silent install with the model download in 52 to 116 s; files, Apps entry "myTTS 1.0.0", Start menu shortcut, no desktop shortcut or Run entry by default; `--version`, `download --verify` and `--self-test` pass (model load 2.2 to 2.4 s, first sentence 0.9 to 1.2 s); starts in the tray in 1.9 to 2.3 s; 147 modules, none from outside the app folder and Windows (apart from phonemizer's temp copy of espeak-ng.dll); memory 480 MB working set and 1.0 GB private idle, 540 MB and 1.07 GB after reading; a silent update while running restarts it in the tray; an uninstall right after that removes everything and keeps the model; `/TASKS=desktopicon,startup` writes the Run entry and the desktop shortcut, a later silent update keeps them, and uninstall removes them. The hotkey step (Ctrl+Alt+Space over selected text read in 1.5 s, the reader highlighted the first sentence, Ctrl+Alt+Right then Ctrl+Alt+Space paused) passed with an installer built locally from the same commit; in the last run on the draft's installer it could not run because the dev machine's screen had locked, which stops the Sandbox from drawing.
- **Second Sandbox session, the draft's installer, with real clicks (`tools/sandbox/wizard.ps1`):** all checks pass.
  - The wizard with its defaults: folder page, tasks page (nothing ticked), Ready page (no extra tasks), model download, the finished page names Ctrl+Alt+Space, Finish starts myTTS with its reader window. No Run entry or desktop shortcut.
  - The hotkey on the draft's installer: read 1.2 s after the key press, and a second press pauses. Memory 479 MB working set and 998 MB private idle, 542 MB and 1.07 GB after reading.
  - The wizard as an update: no folder page and no download; ticking "Start myTTS when I sign in" lists only that task and writes the Run entry `"...\myTTS.exe" --tray`.
  - A restart inside the Sandbox: Explorer started myTTS with `--tray` 22 s after boot, one copy, in the tray.
  - The uninstaller's own window: it asks to confirm, then about the voice model ("Remove the voice model" / "Keep it"); with Remove, the app, the Apps entry, the Start menu shortcut, the Run entry, the model and `%LOCALAPPDATA%\mytts` are gone, and the settings in `%APPDATA%\mytts` are kept.
  - **Found:** in the wizard, the 28 MB `voices-v1.0.bin` download failed right after the model finished: WinINet 12152, "The server returned an invalid or unrecognized response" (once; every earlier setup download in Sandbox worked). The "could not be downloaded" dialog works, and "Try again" fetched only the missing file. Two weak spots: the dialog shows Inno's raw text ("Internal error: Worker thread terminated unexpectedly with exception: Error receiving data: (12152) ..."), and a silent install (as winget would run) does not retry and installs without the model, which the reader window then offers to download. See "Left for the user".
- **Tooling:** `tools/sandbox/` (README, `test.ps1`, `ui.ps1`, `textwin.ps1`, `agent.ps1`, `mytts.wsb`). This Windows has no `wsb` command line, so a job runner started at sign-in runs scripts dropped into a read-only mapped folder. Pitfalls are in its README.
- **FluentVoice Pro, hands-on:** still at 1.6.7 (released 2026-11-08), so the table's version is current. Its portable zip (SHA-256 checked) ran only in Sandbox. It asks once about starting with Windows and shortcuts; the read hotkey is Ctrl+Shift+Space and the stop hotkey is unset; the default voice is the online `en-US-AndrewMultilingualNeural`; a tray click speaks or stops; its update check lists the Microsoft Store and winget. That matches the Hotkey, Voices, Network and Install rows. The "Following along" row (the part and time status line) is in its Settings window, which opens only from the tray menu and was not reached; the table already says it compares with the README.
- **M5 scan again** (16 commits, refs `main`, `v0.1.0`, `v1.0.0`): gitleaks found no leaks; the personal-data grep over every revision since `43b885e` hit only the public username, this roadmap's own description of the scan, COM GUIDs and workflow wording; no file was ever deleted; the PNGs have only `IHDR`, `pHYs`, `IDAT`, `IEND`; the GIF only its `NETSCAPE2.0` loop block; the MP4 only the muxer tag `Lavf63.1.102` and the x264 settings (no creation time or paths); all commit messages read. GitHub: private; no secrets, keys, hooks, environments or Pages; one collaborator; Dependabot closed #1 and #2 itself; one Actions artifact (the M8 test build of 0.1.0, expires 2026-12-10). The commits after the scan (`7436b3b` and this one) are code, tests, tooling and this roadmap.
- **Links:** all 25 external links in the Markdown files return 200; the repo's own link targets exist (checked through the API). The release and downloads badges and the private reporting form (`security/advisories/new`) work only after M11 makes the repo public, publishes the release and turns on private vulnerability reporting.

Known limits at launch: the installer is unsigned (SmartScreen warning); no Windows on ARM build; 7 languages; the app needs about 1 GB of memory while it runs.

What happened next: 1.0.0 was published as it was, and the download retry ships as 1.0.1 (see M11).

### M11: Go public (done; post-launch steps wait for the user)

Done on 2026-11-26 (recorded on 2026-11-27, because the session that did it ended before updating this file):

- **Public:** the repo is public and renamed `myTTS` (the old `mytts` URLs redirect, and `origin` points at the new name), with a description, 8 topics and the latest release as its homepage. **1.0.0 published** at 11:26 UTC (tag `v1.0.0` on `7436b3b`). Logged out: the repo page, `releases/latest` and the installer download all return 200. Downloads by 2026-11-27: installer 3, `SHA256SUMS.txt` 3, each source archive 2.
- **Security:** secret scanning with push protection, Dependabot alerts and private vulnerability reporting are on. The ruleset "Protect main" (the default branch, no bypass) blocks deletion and force pushes. Dependabot security updates (automatic PRs) are off; they were not part of the plan.
- **Social preview:** the user uploaded `docs/social-preview.png` on 2026-11-27 (`usesCustomOpenGraphImage` is true).

**1.0.1, the voice model download retry** (the user's answer to M10):

- Setup tries a failed download twice more, after 3 s and then 6 s, with a countdown on the download page; silent installs retry too; files that already arrived are not fetched again; the dialog after the last try says what went wrong in plain words, with Inno's text under Details (`d8f8708`). `tools/sandbox/retry.ps1` serves the model from a local server that cuts off the downloads it is told to; all four scenarios pass in Sandbox: cut once (silent), always (silent; installs without the model), the wizard (countdown, plain dialog, "Try again" downloads), and Stop during the countdown.
- Version 1.0.1 (`3d3fe77`). Its first release run failed because `THIRD_PARTY_NOTICES.md` still named 1.0.0; a test now checks that line (`66b5200`). The draft "myTTS 1.0.1" from `66b5200`: `myTTS-setup-1.0.1.exe` 44,626,532 bytes, SHA-256 `2c4df263a2387877159a55c0c95f36c85f3bab1d778520daadfc18e02dbd09f0`; downloaded through the API, `sha256sum -c` passed.
- **The draft in Sandbox (2026-11-27):** the published 1.0.0 installed and running, then a silent update to 1.0.1 restarts it in the tray; all `checks` pass (Apps entry "myTTS 1.0.1", `--version`, `download --verify`, `--self-test`); the hotkey reads 124 characters and plays 2.1 s after the key press, and a second press pauses; the tasks step passes; a fresh install with the real model download takes 57 s and passes all checks.
- **Found: an uninstall right after a silent update** left `myTTS.exe` and the logs folder behind in 1 of 2 runs: the M10 fix had too little margin. Measured in Sandbox: after a silent update, the restarted copy takes the mutex 1.7, 2.5 and 5.0 s after it starts, and `quit` waited at most 5 s for it (the whole `quit` step took 5.3 to 5.8 s in the uninstall logs). `wait_for_start` now waits up to 30 s; it only waits while a copy of the exe exists that does not hold the mutex yet (`b8878d2`).
- Sandbox harness fixes: `test.ps1` finds the text window by its title (the PowerShell console that shows first was taken for it, so Ctrl+A selected nothing); `Wait-Log` only looks at lines written after a mark (a stale "Started in the tray" line gave "started in 0.0 s"); "reads the selection" needs at least 1 character. The README lists the pitfalls (`Start-Process -Wait` also waits for the app setup starts).

- **That was not the whole cause.** The draft rebuilt with `b8878d2` (the user said go ahead with moving the tag) still left the app behind, and this time the next setup hung. The copy that setup had just started (`--tray`) already held the mutex, so `quit` found it, but a copy answers messages only once its event loop runs, seconds after it takes the mutex. `send()` waited 2 s for the reply, `quit` said "did not respond" (exit 1, which the uninstaller ignores), and the uninstaller deleted the files under the copy (its log then shows `No module named 'onnxruntime.capi.onnxruntime_pybind11_state'`). The next setup's `quit` started the half-deleted exe, which stopped at PyInstaller's error dialog, and setup waited on it. Fixed in `fe2f63f`: `send()` waits for the reply until its own timeout, and `quit` gives it 30 s (`START_TIMEOUT`). A new test holds the mutex for 4 s before starting the event loop; it fails on the old code. 161 tests pass (1 skipped).
- **The final 1.0.1 draft:** tag `v1.0.1` moved twice, now on `fe2f63f` (both earlier drafts deleted; none was published). Release workflow green. `myTTS-setup-1.0.1.exe` 44,631,989 bytes, SHA-256 `641a391b322d4b2ece37d5306cda315fda896152c8ca8a945ca2e69714b87557`; `sha256sum -c` passed; the release notes list all three fixes.
- **The final draft in Sandbox (2026-11-27), 57 checks, none failed:** the published 1.0.0 installed and running, a silent update to 1.0.1 restarts it in the tray; `checks` (Apps entry "myTTS 1.0.1", `--version`, `download --verify`, `--self-test`); tray start 5.4 s; the hotkey plays 2.7 s after the key press and a second press pauses; update while running, uninstall right after it (everything removed, model kept), the tasks step; a fresh install with the real model download (75 s) passes all checks. `tools/sandbox/measure.ps1`: the restarted copy held the mutex 2.5 to 2.8 s after it started (3 updates), and 5 uninstalls right after a silent update left no files and no process. The uninstaller's `quit` step now takes 7.9 to 8.5 s, because it waits until the new copy answers.

- **1.0.1 published** on 2026-11-27 at 08:03 UTC (the user's go-ahead), marked latest; the CHANGELOG date is now 2026-11-27. Logged out: `releases/latest` goes to `v1.0.1`, and the installer downloaded from `releases/latest/download/` matches `SHA256SUMS.txt`.

Left: the post-launch steps below, each only with the user's go-ahead.

The original plan, for reference:

- Make the repo public through the REST API. Publish the draft release. Check the README, release and download from a logged-out browser.

- Make the repo public through the REST API. Publish the draft release. Check the README, release and download from a logged-out browser.
- The user uploads `docs/social-preview.png` by hand right after the repo is public (Settings > General > Social preview > Edit > Upload an image; there is no API, and the setting only appears on a public repository).
- Turn on the features that are free for public repos: secret scanning with push protection, Dependabot alerts, private vulnerability reporting. Add a ruleset on `main` that blocks force pushes and deletion.
- After launch, each step only with the user's go-ahead:
  - A LinkedIn post (draft written for review) with the MP4.
  - Posts on Show HN and Reddit (r/software, r/windows, r/opensource).
  - A winget manifest pull request to `microsoft/winget-pkgs`, so `winget install mytts` works.
  - An application to the SignPath Foundation for free code signing for open source projects, to remove the SmartScreen warning.
  - Later: the Microsoft Store, which accepts Win32 installers (check the current terms for individual developers).

## Dev environment notes

- The `.venv` uses Python 3.13.17 from the Python install manager (`pymanager install 3.13.17`; its python.exe is `%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe`). kokoro-onnx requires Python below 3.14, and the default `python` on the dev machine belongs to PlatformIO, so don't use it.
- Run the tests with `.venv\Scripts\python -m pytest -q`.
- Processes started from the Claude Code shell ignore Ctrl+C (Windows passes that flag to child processes). To test Ctrl+C in a console program, call `SetConsoleCtrlHandler(None, False)` in it first.
- `conhost.exe <command>` opens a classic console window even when Windows Terminal is the default terminal; `wt.exe -w new <command>` opens a separate Windows Terminal window.
- `QTest.qWait` keeps the GIL while it waits, which starves Python worker threads: with the real engine, `ready` never arrived within 15 s. With `QEventLoop` + `QTimer.singleShot`, it arrives in 1.2 s. Tests with fake engines are not affected; use the event loop when a real worker thread must run (see `tools/screenshots.py`).
- Windows PowerShell 5.1 quirks the install scripts work around: it reads a script without a BOM in the ANSI code page (keep the scripts ASCII; a test checks this); it strips `"` inside arguments passed to native programs (use `'` in `python -c` code); and it passes `$null` to a P/Invoke string parameter as `""` (use `[NullString]::Value`).
- To test the install scripts without touching real data, run them in a child process with `LOCALAPPDATA` and `APPDATA` pointed at scratch folders.
