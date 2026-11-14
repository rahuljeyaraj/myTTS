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

### M2: Reader window and playback (next)

- `mytts/player.py`: a playback controller on a worker thread.
  - Synthesize ahead (2 to 3 segments) into a cache keyed by (segment index, voice, speed).
  - Play through a `sounddevice.OutputStream` at 24 kHz, writing small chunks so pause, stop and jump respond within about 50 ms. The default device reports 44.1 kHz; if the host API refuses 24 kHz, resample.
  - Commands: play(segments), pause, resume, stop, jump(i), next, prev. A voice or speed change clears the cache and restarts the current sentence; debounce the speed slider by about 300 ms.
  - Gaps: about 120 ms between sentences and about 350 ms between paragraphs.
  - Emit Qt signals: `segment_started(i)`, `state_changed`, `finished`, `error`.
  - Warm up the model at startup with a short throwaway phrase, so the first real sentence is fast.
- `mytts/ui/reader.py` (PySide6):
  - The text area is a read-only `QTextEdit` showing the normalized text, with a line height of about 160% and generous padding.
  - Highlight the current sentence with `setExtraSelections` and keep it scrolled into view. Show a fainter highlight on the sentence under the mouse, with a pointing-hand cursor.
  - Clicking a sentence jumps to it. A drag that selects text does not.
  - Bottom bar: previous, play/pause, stop and next buttons (Segoe Fluent Icons glyphs, falling back to Segoe MDL2 Assets), a voice combo box using `Voice.label`, a speed slider (0.5× to 2.0×, step 0.05) with a label, and a pin (always on top) toggle.
  - Keyboard: Space plays or pauses, Esc stops, Left and Right move by sentence, Ctrl+V pastes text and reads it.
  - Themes: dark by default, with sepia. Dark uses background `#1c1b19`, text `#d8d4cc`, highlight `#3a3326` and an amber accent `#d9a55b`. Sepia uses background `#f5efe3`, text `#3b362f` and highlight `#e8d9b5`. Make the title bar dark with `DwmSetWindowAttribute` (attribute 20).
  - `python -m mytts` with no arguments opens the window.

### M3: Hotkey, selection capture, tray and settings

- Global hotkey: call `RegisterHotKey` on a dedicated thread with its own `GetMessageW` loop, using `MOD_NOREPEAT`, and emit a Qt signal. To re-register, use `PostThreadMessageW`. The default is Ctrl+Alt+Space, and it can be changed.
- Capture the selection: wait up to about 1 s for the modifier keys to be released (`GetAsyncKeyState`), save the current text on the clipboard, record `GetClipboardSequenceNumber`, send Ctrl+C with `SendInput`, then poll up to about 600 ms for the sequence number to change.
  - If it changed, read `CF_UNICODETEXT` and restore the previous text on the clipboard.
  - If it did not change, nothing was selected: just show the window.
  - Known limit: Windows (UIPI) blocks sending Ctrl+C to apps running as administrator.
- Tray icon (`QSystemTrayIcon`) with Show, Read selection, Pause/Resume, Stop, Settings and Quit. Closing the window hides it to the tray.
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
