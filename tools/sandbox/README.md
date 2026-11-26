# Clean-machine test in Windows Sandbox

Tests a release installer on a fresh Windows with no Python and no Visual C++ runtime. Windows Sandbox must be turned on (Turn Windows features on or off > Windows Sandbox, then restart).

## Set up

1. Make `build\sandbox\in`, `build\sandbox\in\queue`, `build\sandbox\out` and `build\sandbox\extra` (`build` is ignored by git).
2. Copy `agent.ps1`, `test.ps1`, `ui.ps1` and `textwin.ps1` to `build\sandbox\in`.
3. Put the release files (the installer and `SHA256SUMS.txt`) in a folder under `in`, for example `in\draft`.
4. Copy `mytts.wsb` to `build\sandbox` and replace `C:\path\to\myTTS` with the checkout's folder.

`in` and `extra` are read-only inside the Sandbox, and `out` is writable. `extra` is for other programs you want to try (for example an app to compare with), so they never run on your own machine.

## Run

Double-click `build\sandbox\mytts.wsb`. At sign-in the Sandbox starts `agent.ps1`, which runs each `in\queue\<name>.ps1` once and writes `out\<name>.txt`, then `out\<name>.done` when it ends. To run the whole test, put a one-line job in the queue:

```powershell
'& C:\in\test.ps1 -Setup C:\in\draft\myTTS-setup-1.0.0.exe' | Set-Content build\sandbox\in\queue\01-test.ps1
```

The results go to `out\results-<time>.txt`, one `PASS` or `FAIL` line per check. `-Steps` runs only some steps: `env`, `hashes`, `install` (silent, with the model download), `checks` (files, Apps entry, shortcuts, `--version`, `download --verify`, `--self-test`), `tray` (start, modules loaded from outside the app, memory), `hotkey`, `update` (silent, while running), `uninstall` (right after the update) and `tasks` (`/TASKS=desktopicon,startup`, then a plain silent update keeps them).

For other checks, dot-source `ui.ps1` in a job. It lists windows and their controls, clicks buttons by their text and saves screenshots to `out`.

## Things to know

- Read the result files with a single read. Don't keep them open from the host (`tail -f`): through the mapped folder that makes writes inside the Sandbox fail.
- The `hotkey` step and screenshots need the Sandbox window to be drawn: keep it open and don't let your own screen lock.
- The Sandbox has no Notepad, so `textwin.ps1` shows the sample text and selects it itself.
- A new Sandbox runs every job in the queue again, so move old jobs out first.
