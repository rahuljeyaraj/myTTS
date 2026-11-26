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
4. **The comparison with FluentVoice Pro (open):** see M9. The user may add more issues they noticed. Each one is checked against the current version first.

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

### M7: Windows installer

- Inno Setup 6 (free; VS Code uses it). One script, `packaging/mytts.iss`.
- Installs per user with no administrator rights (`PrivilegesRequired=lowest`) to `%LOCALAPPDATA%\Programs\mytts`. It creates the Start menu shortcut with the AppUserModelID `mytts.app` (Inno supports this natively), an entry in Settings > Apps, and optional tasks for a desktop shortcut and "Start with Windows". Setup ends with "Launch mytts".
- The model goes to the existing `%LOCALAPPDATA%\mytts\models`, so an existing download is reused. How it gets there depends on decision 1.
- It packages `dist\myTTS` from `packaging\build.ps1` and runs `myTTS.exe quit` before replacing files. The app re-points an enabled Run entry at whichever copy starts, so a dev build run on a machine with the installed app moves it; consider ignoring builds outside the install folder there.
- Upgrades: installing a newer version closes the running copy (`mytts.exe quit`) and keeps the model and settings. If an install from `install.ps1` is found, it is removed first, keeping the model and settings.
- Uninstall: closes the app, removes the program, the shortcuts and the Run entry. It asks whether to remove the voice model too (354 MB); settings are kept.
- License compliance, because the installer bundles third-party code:
  - A `licenses\` folder in the install with the MIT license, Apache-2.0 (Kokoro), GPL-3.0 (eSpeak NG), LGPL-3.0 (Qt / PySide6), and `THIRD_PARTY_NOTICES.md` generated from the frozen build's packages.
  - eSpeak NG is GPL-3.0, so the installer as a whole is distributed under GPL-3.0 terms. The mytts source stays MIT (which is compatible with the GPL). Each release carries the source of the exact eSpeak NG version it bundles, and the README says this plainly.
  - The Qt DLLs stay as separate, replaceable files (LGPL).
- Test in Windows Sandbox: a fresh install, an upgrade over the previous build, an upgrade over an `install.ps1` install, and uninstalling with and without the model. Also the M6 checks of the exe itself (start, read a selection, hotkeys, tray, start with Windows), which ran on the dev machine because Sandbox was not enabled.
- `install.ps1` stays, documented as "install from source" for developers.

### M8: CI and release pipeline (GitHub Actions)

- `ci.yml`: on every push and pull request, run the tests on `windows-latest` with Python 3.10 and 3.13.
- `release.yml`: on a `v*` tag, run the tests, build the exe, run `--self-test` against a cached model, build the installer, write `SHA256SUMS.txt`, attach the eSpeak NG source, and create a **draft** release with notes from `CHANGELOG.md`. Nothing is published automatically.
- Pin actions to commit SHAs. Add Dependabot for pip and GitHub Actions.
- Releases are unsigned at first; Windows SmartScreen will show "Windows protected your PC". The README explains this (More info > Run anyway) and gives the SHA-256. Free signing comes after launch (M11).

### M9: A professional repo

- README, rewritten from the user's point of view:
  - At the top: the icon, the name, a one-line tagline, badges (latest release, downloads, CI, license, Windows 10/11), a demo GIF, and a big **Download for Windows** link to the latest installer.
  - Then: features, screenshots, hotkeys, settings, and an FAQ (the SmartScreen warning, privacy and offline use, languages, system requirements, where files live, how to uninstall).
  - **Background / Inspiration**: mytts was inspired by [FluentVoice Pro](https://github.com/nickotmazgin/fluentvoice-pro) by Nick Otmazgin, and its voice goal by Google's voices in the "Read Aloud" Chrome extension. Credit them warmly, and link them.
  - **What mytts does differently**, as a factual table, not a list of complaints. Each row is checked by hand against the current FluentVoice Pro (v1.6.7 on 2026-11-26) in Windows Sandbox, and the table says which version was compared. What its README shows today:
    - Highlighting the sentence being read, and clicking a sentence to jump there: its README does not mention either. This is the main difference.
    - A status while audio is being prepared: its README now describes one ("Connecting… → Speaking — voice • part 2/7 • 1:05 / 3:10"). If the user saw no such status, that was likely an older version. Leave this row out unless the check shows a real difference.
    - Offline voices: it now has Kokoro and Piper as well, but it uses online Microsoft voices first. mytts is offline only, with no network use after the model download.
    - Rows the user wants to add go through the same check. Claims about another person's project must be accurate and polite: it is free software and its author may read the page.
  - Credits and licenses, building from source, contributing.
- New files: `CHANGELOG.md` (Keep a Changelog), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant), `SECURITY.md` (private vulnerability reporting), `THIRD_PARTY_NOTICES.md`, `.github/ISSUE_TEMPLATE/` (bug report with version, Windows build and log location; feature request), a pull request template, `.editorconfig`, `.gitattributes`.
- A demo GIF for the README (select text in a browser, press the hotkey, watch the highlight move). Also an MP4 with sound for LinkedIn. A social preview image (1280×640) in the icon's style.
- Repo settings through the REST API: description, topics (`text-to-speech`, `tts`, `windows`, `offline`, `kokoro`, `read-aloud`, `accessibility`, `pyside6`), homepage set to the latest release, Issues on, Wiki and Projects off. The social preview image is uploaded by hand in Settings, because there is no API for it.

### M10: Pre-launch review (then stop for the user)

- Build `v1.0.0` through the release pipeline, as a draft release.
- In Windows Sandbox, download the installer from the draft release and run through the full test list.
- Run the M5 scan again over everything committed since.
- Check every README link, image and badge.
- Write a short review summary for the user: what will become public, the draft release, the screenshots, the comparison table, and known limits.
- **Stop here.** Nothing becomes public until the user says so.

### M11: Go public (only when the user says so)

- Make the repo public through the REST API. Publish the draft release. Check the README, release and download from a logged-out browser.
- Turn on the features that are free for public repos: secret scanning with push protection, Dependabot alerts, private vulnerability reporting. Add a ruleset on `main` that blocks force pushes and deletion.
- After launch, each step only with the user's go-ahead:
  - A LinkedIn post (draft written for review) with the MP4.
  - Posts on Show HN and Reddit (r/software, r/windows, r/opensource).
  - A winget manifest pull request to `microsoft/winget-pkgs`, so `winget install mytts` works.
  - An application to the SignPath Foundation for free code signing for open source projects, to remove the SmartScreen warning.
  - Later: the Microsoft Store, which accepts Win32 installers (check the current terms for individual developers).

## Dev environment notes

- Use `py -3.10 -m venv .venv`. kokoro-onnx requires Python below 3.14, and the default `python` on the dev machine belongs to PlatformIO, so don't use it.
- Run the tests with `.venv\Scripts\python -m pytest -q`.
- Processes started from the Claude Code shell ignore Ctrl+C (Windows passes that flag to child processes). To test Ctrl+C in a console program, call `SetConsoleCtrlHandler(None, False)` in it first.
- `conhost.exe <command>` opens a classic console window even when Windows Terminal is the default terminal; `wt.exe -w new <command>` opens a separate Windows Terminal window.
- `QTest.qWait` keeps the GIL while it waits, which starves Python worker threads: with the real engine, `ready` never arrived within 15 s. With `QEventLoop` + `QTimer.singleShot`, it arrives in 1.2 s. Tests with fake engines are not affected; use the event loop when a real worker thread must run (see `tools/screenshots.py`).
- Windows PowerShell 5.1 quirks the install scripts work around: it reads a script without a BOM in the ANSI code page (keep the scripts ASCII; a test checks this); it strips `"` inside arguments passed to native programs (use `'` in `python -c` code); and it passes `$null` to a P/Invoke string parameter as `""` (use `[NullString]::Value`).
- To test the install scripts without touching real data, run them in a child process with `LOCALAPPDATA` and `APPDATA` pointed at scratch folders.
