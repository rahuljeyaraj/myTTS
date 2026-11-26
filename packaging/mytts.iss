; Inno Setup 6 script for myTTS-setup-<version>.exe.
;
; Build it with: powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Installer
; That builds dist\myTTS (PyInstaller), writes build\installer (defines.iss, icon and wizard
; images, by packaging\installer_assets.py) and then compiles this script into dist\.
;
; What setup does:
; - Installs for the current user, without administrator rights, to %LOCALAPPDATA%\Programs\mytts.
; - Closes a running myTTS first (myTTS.exe quit). If myTTS was installed from source with
;   install.ps1, removes that copy (its uninstall.ps1 -KeepModel), keeping the model and settings.
; - Downloads the voice model to %LOCALAPPDATA%\mytts\models unless it is already there, and
;   checks its SHA-256. A failed download is tried twice more after a short wait; if it still
;   fails, the user can try again or install without it (a silent install goes on without it),
;   and the app offers the download.
; - Start menu shortcut (with the app's AppUserModelID), optional desktop shortcut, optional
;   "Start with Windows" (the same Run entry the app's setting writes).
; Uninstall closes the app, removes the program, shortcuts, Run entry and logs, and asks whether
; to remove the voice model too. Settings (%APPDATA%\mytts) are kept.

#ifndef AssetsDir
  #define AssetsDir AddBackslash(SourcePath) + "..\build\installer"
#endif
#include AddBackslash(AssetsDir) + "defines.iss"

#ifndef SourceDir
  #define SourceDir AddBackslash(SourcePath) + "..\dist\myTTS"
#endif
#ifndef OutputDir
  #define OutputDir AddBackslash(SourcePath) + "..\dist"
#endif
#define AppExe "myTTS.exe"
#if GetStringFileInfo(SourceDir + "\" + AppExe, "ProductVersion") != AppVersion
  #error The version of dist\myTTS\myTTS.exe does not match mytts.__version__: rebuild it
#endif

[Setup]
; "mytts" keeps the Settings > Apps key (mytts_is1) apart from install.ps1's key (mytts).
AppId=mytts
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#ProjectUrl}
AppSupportURL={#ProjectUrl}/issues
AppUpdatesURL={#ProjectUrl}/releases
AppCopyright={#Copyright}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} setup
PrivilegesRequired=lowest
DefaultDirName={autopf}\mytts
DisableDirPage=auto
DisableProgramGroupPage=yes
UsePreviousTasks=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=myTTS-setup-{#AppVersion}
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern dynamic
WizardSmallImageFile={#SmallImages}
WizardImageFile={#LargeImages}
Compression=lzma2/ultra64
SolidCompression=yes
SetupLogging=yes
RestartApplications=no

[Messages]
FinishedLabel=Setup has installed [name] on your computer. Select text in any window and press the read hotkey ({#ReadHotkey}, unless you changed it) to hear it.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start {#AppName} when I sign in to Windows (it waits in the notification area)"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; Start clean, so files a newer build no longer has don't linger and get loaded.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Comment: "Reads selected text aloud with offline voices"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Comment: "Reads selected text aloud with offline voices"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; A silent update (winget, for example) starts it again in the tray if setup closed it.
Filename: "{app}\{#AppExe}"; Parameters: "--tray"; Flags: nowait runasoriginaluser; Check: RestartAfterSilentUpdate

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitApp"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'mytts';
  SourceInstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\mytts';
  DownloadTries = 3;  { a failed download is tried again twice by itself }
  RetryDelay = 3;     { seconds before the first retry; the second waits twice as long }

var
  DownloadPage: TDownloadWizardPage;
  HadStartup: Boolean;     { a "Start with Windows" entry existed when setup started }
  HadDesktopIcon: Boolean;
  TasksPageSeen: Boolean;
  WasRunning: Boolean;     { setup closed a running copy }
  RemoveModel: Boolean;    { uninstall: the user chose to remove the voice model }

function DataDir: String;
begin
  Result := ExpandConstant('{localappdata}\mytts');
end;

function ModelsDir: String;
begin
  Result := DataDir + '\models';
end;

function AppExePath: String;
begin
  Result := ExpandConstant('{app}\{#AppExe}');
end;

function DesktopIconPath: String;
begin
  Result := ExpandConstant('{autodesktop}\{#AppName}.lnk');
end;

{ The same check as the app (models.is_present): the file exists with the right size. }
function ModelFilePresent(const Name: String; const Size: Int64): Boolean;
var
  Actual: Int64;
begin
  Result := FileSize64(ModelsDir + '\' + Name, Actual) and (Actual = Size);
end;

function ModelPresent: Boolean;
begin
  Result := ModelFilePresent('{#ModelName}', {#ModelSize}) and ModelFilePresent('{#VoicesName}', {#VoicesSize});
end;

function InitializeSetup: Boolean;
begin
  HadStartup := RegValueExists(HKCU, RunKey, RunValue);
  HadDesktopIcon := FileExists(DesktopIconPath);
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading the voice model',
    '{#AppName} reads with the Kokoro voice model ({#ModelMB} MB). It is downloaded once and kept when you update.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

{ The tasks show what is set now, so unticking one turns it off. Inno calls this in a silent
  install too, where it would undo /TASKS: there CurStepChanged keeps what is set instead. }
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and not TasksPageSeen and not WizardSilent then begin
    TasksPageSeen := True;
    if HadStartup then WizardSelectTasks('startup') else WizardSelectTasks('!startup');
    if HadDesktopIcon then WizardSelectTasks('desktopicon') else WizardSelectTasks('!desktopicon');
  end;
end;

{ Inno's text for a failed download, without the "Internal error: Worker thread terminated
  unexpectedly with exception:" in front of the real reason. }
function DownloadDetails(const Raw: String): String;
var
  P: Integer;
begin
  Result := Raw;
  P := Pos('exception: ', Result);
  if P > 0 then
    Result := Copy(Result, P + Length('exception: '), MaxInt);
  Result := AddPeriod(Trim(Result));
end;

{ What went wrong, in plain words. }
function PlainDownloadError(const Details: String): String;
var
  HttpFailed: String;
begin
  HttpFailed := SetupMessage(msgErrorDownloadFailed);  { "Download failed: %1 %2" (the HTTP status) }
  HttpFailed := Copy(HttpFailed, 1, Pos('%1', HttpFailed) - 1);
  if Pos('hash', Lowercase(Details)) > 0 then
    Result := 'A downloaded file arrived incomplete or damaged: it did not match its checksum.'
  else if (HttpFailed <> '') and (Pos(HttpFailed, Details) > 0) then
    Result := 'The download server did not send the file.'
  else
    Result := 'The connection to the download server failed or was cut off.';
end;

{ Waits before trying again, counting down on the download page. Returns False if the user
  pressed Stop download meanwhile. }
function WaitBeforeRetry(const Seconds, NextTry: Integer): Boolean;
var
  Ms: Integer;
begin
  Ms := Seconds * 1000;
  while (Ms > 0) and not DownloadPage.AbortedByUser do begin
    DownloadPage.SetText('The download was interrupted.',
      Format('Trying again in %d s (try %d of %d)...', [(Ms + 999) div 1000, NextTry, DownloadTries]));
    Sleep(250);
    Ms := Ms - 250;
  end;
  Result := not DownloadPage.AbortedByUser;
end;

{ One round: up to DownloadTries tries, waiting a little longer before each retry. Files that
  were already downloaded to the temporary folder with the right hash are not fetched again.
  Returns '' on success, otherwise Inno's text for the last failure. }
function TryDownload(var Stopped: Boolean): String;
var
  Attempt: Integer;
begin
  Stopped := False;
  Attempt := 1;
  while True do begin
    Result := '';
    try
      DownloadPage.Download;
    except
      Result := GetExceptionMessage;
    end;
    if Result = '' then
      exit;
    Stopped := DownloadPage.AbortedByUser;
    if Stopped then begin
      Log('Voice model download stopped by the user');
      exit;
    end;
    Log(Format('Voice model download failed (try %d of %d): %s', [Attempt, DownloadTries, Result]));
    if Attempt >= DownloadTries then
      exit;
    Attempt := Attempt + 1;
    if not WaitBeforeRetry(RetryDelay * (Attempt - 1), Attempt) then begin
      Stopped := True;
      exit;
    end;
  end;
end;

// Downloads the missing model files into the temporary folder; CurStepChanged moves them
// into place. Retries by itself first (a silent install too); then the user can try again or
// install without the model.
function DownloadModel: Boolean;
var
  Failure, Details, InstallLater: String;
  Stopped: Boolean;
  Answer: Integer;
  Done: Boolean;
begin
  Result := True;
  InstallLater := 'You can also install {#AppName} now and download the voice model later from its window.';
  Done := ModelPresent;
  if Done then
    Log('The voice model is already in ' + ModelsDir);
  while not Done do begin
    DownloadPage.Clear;
    if not ModelFilePresent('{#ModelName}', {#ModelSize}) then
      DownloadPage.Add('{#ModelBaseUrl}/{#ModelName}', '{#ModelName}', '{#ModelSha256}');
    if not ModelFilePresent('{#VoicesName}', {#VoicesSize}) then
      DownloadPage.Add('{#ModelBaseUrl}/{#VoicesName}', '{#VoicesName}', '{#VoicesSha256}');
    DownloadPage.Show;
    try
      Failure := TryDownload(Stopped);
    finally
      DownloadPage.Hide;
    end;
    if Failure = '' then
      Done := True
    else if WizardSilent then begin
      Log('Installing without the voice model; the app offers the download');
      Done := True;
    end else begin
      if Stopped then
        Failure := 'The download was stopped.' + #13#10#13#10 + InstallLater
      else begin
        Details := DownloadDetails(Failure);
        Failure := PlainDownloadError(Details) + ' Check that this computer is connected to the internet, then try again.';
        Failure := Failure + #13#10#13#10 + InstallLater + #13#10#13#10 + 'Details: ' + Details;
      end;
      Answer := TaskDialogMsgBox('The voice model could not be downloaded', Failure,
        mbError, MB_RETRYCANCEL, ['Try again', 'Install without it'], 0);
      Done := Answer <> IDRETRY;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
    Result := DownloadModel;
end;

{ Asks the running copy to exit and waits for it (up to 10 s, in the app). }
procedure CloseRunningApp;
var
  Code: Integer;
begin
  if FileExists(AppExePath) then begin
    Exec(AppExePath, 'quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Log(Format('myTTS.exe quit: exit code %d', [Code]));
    WasRunning := Code = 0;  { 1: it was not running }
  end;
end;

{ A copy installed from source by install.ps1: remove it with its own uninstall.ps1, keeping
  the model and settings. Returns an error message, or '' on success. }
function RemoveSourceInstall: String;
var
  Script: String;
  Code: Integer;
begin
  Result := '';
  if not RegKeyExists(HKCU, SourceInstallKey) then
    exit;
  Script := DataDir + '\uninstall.ps1';
  Log('Removing the copy installed by install.ps1');
  if FileExists(Script) then
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" -KeepModel',
      ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, Code)
  else
    Log('No uninstall.ps1 in ' + DataDir);
  if RegKeyExists(HKCU, SourceInstallKey) then
    Result := 'Setup could not remove the copy of {#AppName} that was installed from source (install.ps1). ' +
      'Remove it with "' + Script + '", then run setup again.';
end;

function RestartAfterSilentUpdate: Boolean;
begin
  Result := WizardSilent and WasRunning;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp;
  Result := RemoveSourceInstall;
end;

procedure MoveDownloaded(const Name: String);
var
  Src, Dest: String;
begin
  Src := ExpandConstant('{tmp}\') + Name;
  if not FileExists(Src) then
    exit;
  Dest := ModelsDir + '\' + Name;
  ForceDirectories(ModelsDir);
  DeleteFile(Dest);
  DeleteFile(Dest + '.part');
  if RenameFile(Src, Dest) or CopyFile(Src, Dest, False) then
    Log('Saved ' + Dest)
  else
    Log('Could not save ' + Dest);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Startup, Desktop: Boolean;
begin
  if CurStep <> ssPostInstall then
    exit;
  MoveDownloaded('{#ModelName}');
  MoveDownloaded('{#VoicesName}');

  { A silent install keeps what is set; /TASKS can add to it. }
  Startup := WizardIsTaskSelected('startup') or (WizardSilent and HadStartup);
  if Startup then
    RegWriteStringValue(HKCU, RunKey, RunValue, '"' + AppExePath + '" --tray')
  else
    RegDeleteValue(HKCU, RunKey, RunValue);
  Desktop := WizardIsTaskSelected('desktopicon') or (WizardSilent and HadDesktopIcon);
  if not Desktop then
    DeleteFile(DesktopIconPath);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cmd: String;
begin
  if CurUninstallStep = usUninstall then begin
    { A silent uninstall keeps the model (it may be followed by an install). }
    RemoveModel := DirExists(ModelsDir) and not UninstallSilent and (SuppressibleTaskDialogMsgBox(
      'Also remove the voice model?',
      'The voice model takes {#ModelMB} MB in ' + ModelsDir + '. Keep it if you plan to install {#AppName} again. ' +
      'Your settings are kept either way.',
      mbConfirmation, MB_YESNO, ['Remove the voice model', 'Keep it'], 0, IDNO) = IDYES);
    { Only an entry that starts this copy: the setting may point at another one. }
    if RegQueryStringValue(HKCU, RunKey, RunValue, Cmd) and
       (Pos(Lowercase(AppExePath), Lowercase(Cmd)) > 0) then
      RegDeleteValue(HKCU, RunKey, RunValue);
  end;
  if CurUninstallStep = usPostUninstall then begin
    DelTree(DataDir + '\logs', True, True, True);
    if RemoveModel then
      DelTree(ModelsDir, True, True, True);
    RemoveDir(DataDir);  { only if nothing else is left in it }
  end;
end;
