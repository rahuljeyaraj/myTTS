# Changelog

All notable changes to myTTS are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and myTTS uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A Windows installer, `myTTS-setup-<version>.exe`, that needs no Python or administrator rights. It downloads the voice model during setup, updates in place and replaces a copy installed with `install.ps1`.
- A self-contained `myTTS.exe`, with a log file, a `--self-test` command and an About section in Settings.
- The read hotkey pauses and resumes; new hotkeys for the next and previous sentence.
- Playback follows the Windows default speaker when it changes, for example when Bluetooth headphones connect.

### Changed

- The app is now called myTTS wherever its name is shown.

## [0.1.0] - 2026-11-14

### Added

- The first version: offline Kokoro voices, the reader window with sentence highlighting, the read-selection hotkey, the tray icon, settings and `install.ps1`.

[Unreleased]: https://github.com/rahuljeyaraj/myTTS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rahuljeyaraj/myTTS/releases/tag/v0.1.0
