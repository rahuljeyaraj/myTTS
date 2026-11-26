# Security policy

## Supported versions

Only the latest release of myTTS gets security fixes. Please update before reporting, if you can.

## Reporting a vulnerability

Please **don't open a public issue** for a security problem. Report it privately instead:

1. Open the repository's [**Security** tab](https://github.com/rahuljeyaraj/myTTS/security).
2. Choose **Report a vulnerability** and fill in the form.

Only the maintainer can see the report. Please include:

- the myTTS version (Settings > About, or `myTTS.exe --version`) and your Windows version,
- what an attacker could do, and the steps to reproduce it,
- whether the problem is already public.

myTTS is maintained by one person in their spare time. You should get a first answer within a week. Once a fix is released, the report is published as a GitHub security advisory, with credit to you unless you prefer otherwise.

## What is in scope

- The app itself: reading the selection through the clipboard, the global hotkeys, the single-instance channel (a named pipe for the current user), the settings and log files.
- The installer and the update and uninstall steps.
- The voice model download: the files are fetched over HTTPS and checked against fixed sizes and SHA-256 hashes.
- The release pipeline in `.github/workflows`.

Problems in a bundled component (Qt, ONNX Runtime, eSpeak NG, Python and the others in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)) are welcome too. If the component's own project should fix it, please report it there as well.

## By design

- After the voice model is downloaded, myTTS makes no network connections. Nothing you read is sent anywhere, and there is no telemetry.
- The log file (`%LOCALAPPDATA%\mytts\logs\mytts.log`) records how long a selection was, never its text.
- The installer is not code-signed yet, so Windows SmartScreen warns about it. Each release lists the installer's SHA-256 so you can check your download.
