# Changelog

All notable changes to myTTS are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and myTTS uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1] - 2026-11-27

### Fixed

- Setup tries a failed voice model download twice more by itself, with a short countdown, before it asks what to do. Silent installs (such as winget) retry too, and files that already arrived are not downloaded again.
- When the download still fails, setup says what went wrong in plain words instead of an "Internal error: Worker thread terminated" message.
- Uninstalling right after a silent update (which starts myTTS again) could leave myTTS running from deleted files when it took more than a few seconds to start. The uninstaller now waits up to 30 s for it.

## [1.0.0] - 2026-11-26

The first public release.

### Added

- A Windows installer, `myTTS-setup-<version>.exe`, that needs no Python or administrator rights. It downloads the voice model during setup, updates in place and replaces a copy installed with `install.ps1`.
- A self-contained `myTTS.exe`, with a log file, a `--self-test` command and an About section in Settings.
- The read hotkey pauses and resumes; new hotkeys for the next and previous sentence.
- Playback follows the Windows default speaker when it changes, for example when Bluetooth headphones connect.

### Changed

- The app is now called myTTS wherever its name is shown.
- Built with Python 3.13 (3.10 has reached its end of life), numpy 2.5 and onnxruntime 1.32. Running from source needs Python 3.11 to 3.13.

## [0.1.0] - 2026-11-14

### Added

- The first version: offline Kokoro voices, the reader window with sentence highlighting, the read-selection hotkey, the tray icon, settings and `install.ps1`.

[Unreleased]: https://github.com/rahuljeyaraj/myTTS/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/rahuljeyaraj/myTTS/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/rahuljeyaraj/myTTS/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/rahuljeyaraj/myTTS/releases/tag/v0.1.0
