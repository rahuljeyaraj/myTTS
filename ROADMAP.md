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

Known limits: if the output device disappears mid-sentence, playback recovers only on the next play or resume.

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

Other candidates:

- A self-contained build (PyInstaller or Nuitka) so Python isn't needed.
- Recovering when the output device disappears mid-sentence (M2 limit).

## Dev environment notes

- Use `py -3.10 -m venv .venv`. kokoro-onnx requires Python below 3.14, and the default `python` on the dev machine belongs to PlatformIO, so don't use it.
- Run the tests with `.venv\Scripts\python -m pytest -q`.
- Processes started from the Claude Code shell ignore Ctrl+C (Windows passes that flag to child processes). To test Ctrl+C in a console program, call `SetConsoleCtrlHandler(None, False)` in it first.
- `conhost.exe <command>` opens a classic console window even when Windows Terminal is the default terminal; `wt.exe -w new <command>` opens a separate Windows Terminal window.
- `QTest.qWait` keeps the GIL while it waits, which starves Python worker threads: with the real engine, `ready` never arrived within 15 s. With `QEventLoop` + `QTimer.singleShot`, it arrives in 1.2 s. Tests with fake engines are not affected; use the event loop when a real worker thread must run (see `tools/screenshots.py`).
- Windows PowerShell 5.1 quirks the install scripts work around: it reads a script without a BOM in the ANSI code page (keep the scripts ASCII; a test checks this); it strips `"` inside arguments passed to native programs (use `'` in `python -c` code); and it passes `$null` to a P/Invoke string parameter as `""` (use `[NullString]::Value`).
- To test the install scripts without touching real data, run them in a child process with `LOCALAPPDATA` and `APPDATA` pointed at scratch folders.
