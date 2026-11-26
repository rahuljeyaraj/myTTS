# Clean-machine test in Windows Sandbox

Tests a release installer on a fresh Windows with no Python and no Visual C++ runtime. Windows Sandbox must be turned on (Turn Windows features on or off > Windows Sandbox, then restart).

## Set up

1. Make `build\sandbox\in`, `build\sandbox\in\queue`, `build\sandbox\out` and `build\sandbox\extra` (`build` is ignored by git).
2. Copy `agent.ps1`, `test.ps1`, `wizard.ps1`, `retry.ps1`, `ui.ps1` and `textwin.ps1` to `build\sandbox\in`.
3. Put the release files (the installer and `SHA256SUMS.txt`) in a folder under `in`, for example `in\draft`.
4. Copy `mytts.wsb` to `build\sandbox` and replace `C:\path\to\myTTS` with the checkout's folder.

`in` and `extra` are read-only inside the Sandbox, and `out` is writable. `extra` is for other programs you want to try (for example an app to compare with), so they never run on your own machine.

## Run

Double-click `build\sandbox\mytts.wsb`. At sign-in the Sandbox starts `agent.ps1`, which runs each `in\queue\<name>.ps1` once and writes `out\<name>.txt`, then `out\<name>.done` when it ends. To run the whole test, put a one-line job in the queue:

```powershell
'& C:\in\test.ps1 -Setup C:\in\draft\myTTS-setup-1.0.0.exe' | Set-Content build\sandbox\in\queue\01-test.ps1
```

The results go to `out\results-<time>.txt`, one `PASS` or `FAIL` line per check. `-Steps` runs only some steps: `env`, `hashes`, `install` (silent, with the model download), `checks` (files, Apps entry, shortcuts, `--version`, `download --verify`, `--self-test`), `tray` (start, modules loaded from outside the app, memory), `hotkey`, `update` (silent, while running), `uninstall` (right after the update) and `tasks` (`/TASKS=desktopicon,startup`, then a plain silent update keeps them).

`wizard.ps1` goes through the setup wizard and the uninstaller with real clicks, in three parts. `-Part install` installs with the wizard's defaults (the folder page, the model download, Finish starts myTTS). `-Part update` runs the wizard again, ticks "Start myTTS when I sign in" and restarts the Sandbox. `-Part signin`, after the restart, checks that Explorer started myTTS with `--tray` from the Run entry, then uninstalls from the uninstaller's window and answers "Remove the voice model". A whole run, as one job:

```powershell
$s = 'C:\in\draft\myTTS-setup-1.0.0.exe'
if (-not (Test-Path C:\out\wizard-restarted.flag)) {
    & C:\in\wizard.ps1 -Part install -Setup $s
    & C:\in\test.ps1 -Steps checks,tray,hotkey -Setup $s
    & C:\in\wizard.ps1 -Part update -Setup $s
} else {
    try { $null = New-Item C:\out\wizard-signin.lock -ItemType File -ErrorAction Stop } catch { return }
    & C:\in\wizard.ps1 -Part signin -Setup $s
}
```

Its results go to `out\wizard-<part>-<time>.txt`, with a screenshot of each page. It does not handle the "could not be downloaded" dialog: if it shows, press a button on it with a job of its own (see below).

`retry.ps1` tests how setup retries a failed voice model download, with a small HTTP server inside the Sandbox that cuts off the downloads it is told to. It needs an installer that downloads from that server and the model files next to it:

```powershell
# On the host, from the checkout:
New-Item -ItemType Directory -Force build\retry-assets, build\sandbox\in\retry\models
(Get-Content build\installer\defines.iss) -replace '^#define ModelBaseUrl .*', '#define ModelBaseUrl "http://127.0.0.1:8765/m"' |
    Set-Content build\retry-assets\defines.iss
& ISCC.exe /Q "/DAssetsDir=$PWD\build\retry-assets" "/O$PWD\build\sandbox\in\retry" /FmyTTS-setup-localserver packaging\mytts.iss
Copy-Item $env:LOCALAPPDATA\mytts\models\* build\sandbox\in\retry\models
'& C:\in\retry.ps1' | Set-Content build\sandbox\in\queue\50-retry.ps1
```

It runs three scenarios (`-Scenarios once, always, wizard`): a silent install where one download is cut off once, a silent install where it always is, and the wizard, where it checks the countdown and the dialog and then presses "Try again". Results go to `out\retry-<time>.txt`.

For other checks, dot-source `ui.ps1` in a job. It lists windows and their controls, clicks buttons by their text and saves screenshots to `out`.

## Things to know

- Read the result files with a single read. Don't keep them open from the host (`tail -f`): through the mapped folder that makes writes inside the Sandbox fail.
- The `hotkey` step and screenshots need the Sandbox window to be drawn: keep it open and don't let your own screen lock.
- The Sandbox has no Notepad, so `textwin.ps1` shows the sample text and selects it itself.
- A new Sandbox runs every job in the queue again, so move old jobs out first.
- The agent starts every job in the queue at once. Put steps that must run in order in one job.
- A restart inside the Sandbox (`shutdown /r`) keeps its state, and the agent starts again and runs every job in the queue again. Guard jobs that must not run twice with a file in `out` (as above). `wizard.ps1 -Part update` also starts the agent from `RunOnce`, so two agents may run the same job: the lock file stops the second.
- The setup wizard's buttons say `Next` and `Back` (the modern style has no arrows). A message box or task dialog over the wizard does not disable its buttons for `BM_CLICK`, so look for dialogs (`#32770`) before clicking. Task dialog buttons are not windows: press them with `TDM_CLICK_BUTTON` and the button's ID (for example `IDYES`, `IDRETRY`).
