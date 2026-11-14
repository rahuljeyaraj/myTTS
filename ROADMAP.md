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

Known limits: if the output device disappears mid-sentence, playback recovers only on the next play or resume. The model is not downloaded from the window yet (M3); a missing model is reported in the status bar.

### M3: Hotkey, selection capture, tray and settings (next)

- Global hotkey: call `RegisterHotKey` on a dedicated thread with its own `GetMessageW` loop, using `MOD_NOREPEAT`, and emit a Qt signal. To re-register, use `PostThreadMessageW`. The default is Ctrl+Alt+Space, and it can be changed.
- Capture the selection: wait up to about 1 s for the modifier keys to be released (`GetAsyncKeyState`), save the current text on the clipboard, record `GetClipboardSequenceNumber`, send Ctrl+C with `SendInput`, then poll up to about 600 ms for the sequence number to change.
  - If it changed, read `CF_UNICODETEXT` and restore the previous text on the clipboard.
  - If it did not change, nothing was selected: just show the window.
  - Known limit: Windows (UIPI) blocks sending Ctrl+C to apps running as administrator.
- Tray icon (`QSystemTrayIcon`) with Show, Read selection, Pause/Resume, Stop, Settings and Quit. Closing the window hides it to the tray.
- `ReaderWindow.closeEvent` currently quits the app (M2). Change it to hide to the tray.
- Single instance with `QLocalServer`: a second launch tells the running app to show its window.
- Settings saved to `%APPDATA%\mytts\settings.json`: voice, speed, theme, font size, hotkey, always on top, start with Windows (HKCU `...\Run`), restore clipboard, and window geometry.
- First run: if the model is missing, the window shows download progress using `models.ensure_all(progress, cancel)`.

### M4: Install and polish

- `install.ps1`: creates the venv, installs dependencies, downloads the model, and adds a Start Menu shortcut (`pythonw -m mytts`) with an icon. It can also add the app to Windows startup. Add `uninstall.ps1`.
- Draw the app icon with QPainter and export it to `.ico` for shortcuts.
- README: screenshots and usage. Tag `v0.1.0`.

## Dev environment notes

- Use `py -3.10 -m venv .venv`. kokoro-onnx requires Python below 3.14, and the default `python` on the dev machine belongs to PlatformIO, so don't use it.
- Run the tests with `.venv\Scripts\python -m pytest -q`.
