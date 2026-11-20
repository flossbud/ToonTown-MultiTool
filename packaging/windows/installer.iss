; ToonTown MultiTool — Inno Setup script
; Driven by /D defines from CI (build-windows.yml): MyAppVersion, MyAppName, MyAppId,
; MyAppFlavor (stable|beta), ConfigDirName, OutputBaseFilename, MyBuildNumber,
; MyPayloadBytes (installed size, shown by the install window; 0 = not shown).
;
; Local build example (from repo root):
;   ISCC.exe /DMyAppVersion=vDEV /DMyAppName="ToonTown MultiTool" \
;            /DMyAppId={8B2F4F8C-...} /DMyAppFlavor=stable \
;            /DConfigDirName=toontown_multitool \
;            /DOutputBaseFilename=ToonTownMultiTool-Setup-vDEV \
;            packaging\windows\installer.iss
;
; ── How a run goes ─────────────────────────────────────────────────────────
; Setup is the only installer and the only thing that changes the PC. The
; windows the player sees (install, update, uninstall) are a small program of
; their own, "rollcall", carried inside Setup (dist\rollcall). Its engine is
; utils/rollcall/engine_inno.py; the flags below are its protocol.
;
; Double-click (not silent): InitializeSetup unpacks rollcall to {tmp}, runs it
; as the player and waits, then exits with its exit code: the wizard never
; shows. When rollcall is missing or exits with RC_EXIT_NO_WINDOW, the stock
; wizard below runs instead (the safety net). /RCWIZARD forces the wizard.
;
; The window then runs THIS Setup again, silently, with the player's choices
; and /RCPROGRESS=<file>. That second instance does the install and appends
; one line per event to <file> (see RcLine); <file>.pause and <file>.cancel
; are the window's requests. /RCMODE=update /RCPID= /RCFROM= /RCREADY= start
; the update window instead (the running app passes them; utils/rollcall/
; handoff.py). /RCARGS="..." is appended to rollcall's command line (CI).
;
; Silent runs WITHOUT /RCPROGRESS are the legacy path (older apps update with
; /SILENT /SUPPRESSMSGBOXES /RELAUNCH=1, and admins deploy with /VERYSILENT):
; they behave as they always did.
;
; unins000.exe (not silent) hands over to the rollcall uninstall window, which
; runs the uninstaller again with /VERYSILENT /RCPROGRESS=<file>.

#ifndef MyAppName
  #define MyAppName "ToonTown MultiTool"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "vDEV"
#endif
#ifndef MyAppId
  #error "MyAppId must be supplied via /DMyAppId={...GUID...}"
#endif
#ifndef MyAppFlavor
  #define MyAppFlavor "stable"
#endif
#ifndef ConfigDirName
  #define ConfigDirName "toontown_multitool"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "ToonTownMultiTool-Setup-" + MyAppVersion
#endif
#ifndef MyBuildNumber
  #define MyBuildNumber "0"
#endif
#ifndef MyPayloadBytes
  #define MyPayloadBytes "0"
#endif
#ifndef PayloadDir
  #define PayloadDir SourcePath + "..\..\dist\ToonTownMultiTool"
#endif
#ifndef RollcallDir
  #define RollcallDir SourcePath + "..\..\dist\rollcall"
#endif
#ifndef RollcallExe
  #define RollcallExe "rollcall.exe"
#endif
#if FileExists(RollcallDir + "\" + RollcallExe)
  #define HaveRollcall
  #define RollcallState "bundled"
#else
  #define RollcallState "absent"
  #pragma message "rollcall build not found at " + RollcallDir + ": this Setup will only have the wizard"
#endif

[Setup]
; AppId GUIDs from guids.env arrive wrapped in {...}. The leading `{` must be
; doubled or Inno parses the value as a constant lookup ("Unknown constant").
AppId={{#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; VersionInfoVersion intentionally omitted: MyAppVersion has a `v` prefix
; and pre-release suffix; Inno's VersionInfoVersion requires plain numeric
; MAJOR.MINOR.PATCH[.BUILD]. The build number is still persisted via
; [Registry] below for IsUpgrade/ConfirmDowngrade checks.
AppPublisher=flossbud
AppPublisherURL=https://github.com/flossbud/ToonTownMultiTool-v2
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
; No "Select Setup Install Mode" dialog: the install window decides (per user
; by default, the existing install's mode on an upgrade, all users only when
; the chosen folder needs it) and passes /CURRENTUSER or /ALLUSERS. Without
; "dialog", Inno ignores UsePreviousPrivileges, so InitializeSetup re-runs a
; run that did not choose a mode with /ALLUSERS when the existing install is
; an all-users one (RcNeedsAllUsersRespawn): legacy silent updates of such an
; install keep updating it in place, as they did with the dialog allowed.
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
WizardSizePercent=120
WizardImageFile=wizard-image.png
WizardSmallImageFile=wizard-small-image.png
UninstallDisplayIcon={app}\ToonTownMultiTool.exe
OutputDir=Output
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
; Close the running app to release its file locks during an upgrade, but do NOT
; let the Restart Manager relaunch it. The in-app updater quits the app itself
; and asks the installer to reopen it via the /RELAUNCH [Run] entry; an RM
; auto-restart would race that and could double-launch.
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenuicon"; Description: "Create a &Start Menu entry"; GroupDescription: "Shortcuts:"
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "keepalive";   Description: "Enable &Keep-Alive on first launch (TOS warning applies)"; GroupDescription: "Keep-Alive:"; Flags: unchecked
Name: "checkupdates"; Description: "Check for &updates at startup"; GroupDescription: "Updates:"
Name: "launchapp";   Description: "&Launch {#MyAppName} after install"; GroupDescription: "After install:"

[Registry]
Root: HKA; Subkey: "Software\flossbud\{#MyAppName}"; ValueType: dword; ValueName: "BuildNumber"; ValueData: "{#MyBuildNumber}"; Flags: uninsdeletevalue; Check: RcShortcutsCheckpoint
Root: HKA; Subkey: "Software\flossbud\{#MyAppName}"; ValueType: string; ValueName: "AppVersion"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletevalue; Check: RcShortcutsCheckpoint

[InstallDelete]
; Never deletes anything (its Check returns False). It is the hook that runs
; after the Restart Manager closed the app and before any folder or file is
; touched: a window-driven run moves the existing install aside here.
;
; Where a window-driven run can be stopped: Inno swallows exceptions raised in
; a Check (the entry is skipped and the install carries on) and in Before/
; AfterInstall, but an exception while it expands a file's destination is a
; file error, which with /SUPPRESSMSGBOXES aborts the install and rolls it
; back (exit code 5). So the files' DestDir is {code:RcFileDestDir}: it returns
; {app}, and raises there to stop the run (cancel, a failed move-aside, the
; /RCTESTFAIL test hook). The Checks below only mark steps and hold a pause.
Type: files; Name: "{app}\.rollcall-hook"; Check: RcBeforeFiles

[Files]
#ifdef HaveRollcall
; The windows, FIRST so a double-click unpacks them from the head of the solid
; stream. One copy for {tmp} (dontcopy: the double-click extracts it), one in
; {app}\rollcall for the uninstaller. Same source, stored once.
Source: "{#RollcallDir}\*"; DestDir: "{tmp}\rollcall"; Flags: dontcopy recursesubdirs createallsubdirs
Source: "{#RollcallDir}\*"; DestDir: "{code:RcFileDestDir}\rollcall"; Flags: ignoreversion recursesubdirs createallsubdirs; BeforeInstall: RcFileStarting
#endif
Source: "{#PayloadDir}\*"; DestDir: "{code:RcFileDestDir}"; Flags: ignoreversion recursesubdirs createallsubdirs; BeforeInstall: RcFileStarting

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"; Tasks: startmenuicon; Check: RcShortcutsCheckpoint
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon; Check: RcShortcutsCheckpoint
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"; Tasks: desktopicon; Check: RcShortcutsCheckpoint

[Run]
; Persist the wizard's checkbox choices into settings.json. The just-installed
; EXE owns the merge logic (utils.installer_merge); we just call it with flags.
; A window-driven run skips it: the window runs the same command itself, as
; the player, after Setup returns (its "Saving your choices" step).
Filename: "{app}\ToonTownMultiTool.exe"; \
  Parameters: "--apply-installer-config --check-updates={code:CheckUpdatesFlag} --keep-alive={code:KeepAliveFlag}"; \
  Flags: runhidden waituntilterminated; \
  Check: RcNotWindowRun

; Launch the app if the user kept the "Launch" checkbox (interactive install).
Filename: "{app}\ToonTownMultiTool.exe"; \
  Description: "Launch {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent; \
  Tasks: launchapp

; Reopen the app after a silent in-app update. The updater passes /RELAUNCH=1
; and closes the running app; skipifsilent on the entry above means it would
; otherwise stay closed, which reads to the user as "nothing happened".
Filename: "{app}\ToonTownMultiTool.exe"; \
  Flags: nowait; \
  Check: WantSilentRelaunch

[UninstallDelete]
; The user-data purge is handled in [Code] via InitializeUninstall + DelTree
; so the channel-specific config dir is removed only when the user opts in.
; A backup or trash folder a window-driven update left behind (it never does
; on a run that ends normally) goes with the app.
Type: filesandordirs; Name: "{app}.previous-version"
Type: filesandordirs; Name: "{app}.removing"

[Code]
const
  // rollcall's exit code for "no window could be shown": Setup falls back to
  // its own wizard (install) or tells the app (update). Keep in step with
  // utils/rollcall/engine_inno.py EXIT_NO_WINDOW.
  RC_EXIT_NO_WINDOW = 3;
  RC_BACKUP_SUFFIX = '.previous-version';
  RC_TRASH_SUFFIX = '.removing';

var
  KeepAliveShortNote:          TLabel;
  UpdatesExplainer:            TLabel;
  KeepAliveConsentPage:        TWizardPage;
  KeepAliveConsentHeading:     TLabel;
  KeepAliveConsentDisclaimer:  TLabel;
  KeepAliveConsentTOS:         TLabel;
  KeepAliveConsentPrompt:      TLabel;
  KeepAliveTaskIndex:          Integer;
  BtnConsentDecline:           TButton;
  BtnConsentAccept:            TButton;

  // Window-driven silent run (/RCPROGRESS=<file>); '' on every other run.
  RcProgressFile:      String;
  RcStep:              Integer;
  RcCopying:           Boolean;
  RcHookDone:          Boolean;
  RcBackupFailed:      Boolean;
  RcLastPermille:      Integer;
  RcAppDir:            String;
  RcBackupDir:         String;
  RcInstallSucceeded:  Boolean;
  RcTestFailAt:        Integer;
  RcTestFailNow:       Boolean;
  RcSavedRegValid:     Boolean;
  RcSavedBuild:        Cardinal;
  RcSavedVersion:      String;

function RcGetCurrentProcessId: Cardinal;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
procedure RcExitProcess(Code: Cardinal);
  external 'ExitProcess@kernel32.dll stdcall';

// Forward declarations: InitializeWizard references @OnConsentDeclineClick
// and @OnConsentAcceptClick to wire the consent-page buttons, but the
// procedure bodies live further down the file. Pascal Script requires
// declaration before use when taking a procedure address.
procedure OnConsentDeclineClick(Sender: TObject); forward;
procedure OnConsentAcceptClick(Sender: TObject); forward;

// ── Roll Call: command line and progress protocol ─────────────────────────

function RcParam(const Name: String): String;
var
  I: Integer;
  P, Prefix: String;
begin
  // The value of /NAME=value (quotes already removed by Inno), '' if absent.
  Result := '';
  Prefix := '/' + Uppercase(Name) + '=';
  for I := 1 to ParamCount do
  begin
    P := ParamStr(I);
    if Pos(Prefix, Uppercase(P)) = 1 then
    begin
      Result := Copy(P, Length(Prefix) + 1, Length(P));
      Exit;
    end;
  end;
end;

function RcFlag(const Name: String): Boolean;
var
  I: Integer;
  U, P: String;
begin
  // True when /NAME or /NAME=... is on the command line.
  Result := False;
  U := '/' + Uppercase(Name);
  for I := 1 to ParamCount do
  begin
    P := Uppercase(ParamStr(I));
    if (P = U) or (Pos(U + '=', P) = 1) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function RcBool(const B: Boolean): String;
begin
  if B then Result := 'yes' else Result := 'no';
end;

procedure RcLine(const S: String);
var
  A: TArrayOfString;
  Tries: Integer;
begin
  // One event per line, appended. The window reads the file while Setup
  // writes it, and Inno opens it exclusively, so a write can meet a read:
  // retry for about a second rather than lose the line.
  Log('[RollCall] ' + S);
  if RcProgressFile = '' then Exit;
  SetArrayLength(A, 1);
  A[0] := S;
  for Tries := 1 to 50 do
  begin
    if SaveStringsToUTF8FileWithoutBOM(RcProgressFile, A, True) then Exit;
    Sleep(20);
  end;
  Log('[RollCall] could not write the progress line above');
end;

function RcWindowRun: Boolean;
begin
  Result := RcProgressFile <> '';
end;

function RcNotWindowRun: Boolean;
begin
  Result := RcProgressFile = '';
end;

function RcCancelRequested: Boolean;
begin
  Result := (RcProgressFile <> '') and FileExists(RcProgressFile + '.cancel');
end;

procedure RcHoldWhilePaused;
var
  Announced: Boolean;
begin
  // The window shows "Stop installing?": hold here until it answers.
  if RcProgressFile = '' then Exit;
  Announced := False;
  while FileExists(RcProgressFile + '.pause') and (not RcCancelRequested) do
  begin
    if not Announced then
    begin
      RcLine('paused');
      Announced := True;
    end;
    Sleep(100);
  end;
  if Announced and (not RcCancelRequested) then
    RcLine('resumed');
end;

procedure RcCheckpoint(const Where: String);
begin
  // Only called where an exception stops the install AND rolls it back:
  // RcFileDestDir (see [InstallDelete]) and CurStepChanged(ssInstall).
  RcHoldWhilePaused;
  if RcCancelRequested then
  begin
    RcLine('cancelled ' + Where);
    RaiseException('Stopped from the install window (' + Where + ').');
  end;
end;

procedure RcEnterStep(const N: Integer);
begin
  if N > RcStep then
  begin
    RcStep := N;
    RcLine('step ' + IntToStr(N));
  end;
end;

// ── Roll Call: the previous version, kept until the new one is in ─────────

function RcIsOurInstallDir(const Dir: String): Boolean;
begin
  Result := (Length(Dir) > 3) and
    FileExists(AddBackslash(Dir) + 'ToonTownMultiTool.exe') and
    FileExists(AddBackslash(Dir) + 'unins000.dat');
end;

function RcRenameWithRetries(const OldName, NewName: String; const Tries: Integer): Boolean;
var
  I: Integer;
begin
  // A scanner opening a file inside the folder blocks a rename for a moment.
  Result := False;
  for I := 1 to Tries do
  begin
    if RenameFile(OldName, NewName) then
    begin
      Result := True;
      Exit;
    end;
    Sleep(250);
  end;
end;

procedure RcSaveRegistry;
var
  Value: Cardinal;
begin
  // Rolling back the new version's [Registry] entries deletes these values;
  // the restore writes the previous ones back.
  RcSavedRegValid := RegQueryStringValue(HKA, 'Software\flossbud\{#MyAppName}', 'AppVersion', RcSavedVersion);
  if RegQueryDWordValue(HKA, 'Software\flossbud\{#MyAppName}', 'BuildNumber', Value) then
    RcSavedBuild := Value
  else
    RcSavedBuild := 0;
end;

procedure RcRestoreRegistry;
begin
  if not RcSavedRegValid then Exit;
  RegWriteStringValue(HKA, 'Software\flossbud\{#MyAppName}', 'AppVersion', RcSavedVersion);
  if RcSavedBuild > 0 then
    RegWriteDWordValue(HKA, 'Software\flossbud\{#MyAppName}', 'BuildNumber', RcSavedBuild);
end;

procedure RcMoveAside;
var
  Trash, Backup: String;
begin
  // Window-driven run, just before any folder or file is touched: move the
  // installed version out of the way in one rename. If the run fails or is
  // stopped, DeinitializeSetup renames it back; if it succeeds, ssPostInstall
  // deletes it. The rename either moves the whole install or nothing, and a
  // folder with a file in use cannot be renamed, so a failure here stops the
  // run (at the first file, RcFileDestDir) before anything changed.
  RcAppDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  Backup := RcAppDir + RC_BACKUP_SUFFIX;
  Trash := RcAppDir + RC_TRASH_SUFFIX;
  if DirExists(Trash) then
    DelTree(Trash, True, True, True);
  if DirExists(Backup) then
  begin
    // An earlier window-driven run never finished (Setup was killed between
    // the move and the restore): the backup is the last complete install and
    // what is in {app} is half of a new one. Keep the backup as this run's.
    RcLine('heal ' + Backup);
    RcSaveRegistry;
    if DirExists(RcAppDir) then
    begin
      if not RcRenameWithRetries(RcAppDir, Trash, 20) then
      begin
        RcLine('error backup in-use ' + RcAppDir);
        RcBackupFailed := True;
        Exit;
      end;
      DelTree(Trash, True, True, True);
    end;
    RcBackupDir := Backup;
    RcLine('backup ok ' + Backup);
    Exit;
  end;
  if not RcIsOurInstallDir(RcAppDir) then
  begin
    // A fresh install (or a folder that is not an install of ours, which is
    // never moved): Inno's own rollback removes whatever a failed run copied.
    RcLine('backup none');
    Exit;
  end;
  RcSaveRegistry;
  if not RcRenameWithRetries(RcAppDir, Backup, 20) then
  begin
    RcLine('error backup in-use ' + RcAppDir);
    RcBackupFailed := True;
    Exit;
  end;
  RcBackupDir := Backup;
  RcLine('backup ok ' + Backup);
end;

procedure RcRestoreBackup;
var
  Trash: String;
  I: Integer;
  Ok: Boolean;
begin
  // The run failed or was stopped after the move: put the previous version
  // back. Inno's rollback has already removed what this run copied.
  Trash := RcAppDir + RC_TRASH_SUFFIX;
  Ok := False;
  for I := 1 to 40 do
  begin
    if DirExists(Trash) then
      DelTree(Trash, True, True, True);
    if DirExists(RcAppDir) then
      RenameFile(RcAppDir, Trash);
    if (not DirExists(RcAppDir)) and RenameFile(RcBackupDir, RcAppDir) then
    begin
      Ok := True;
      Break;
    end;
    Sleep(250);
  end;
  if Ok then
  begin
    RcRestoreRegistry;
    RcBackupDir := '';
    if DirExists(Trash) then
      DelTree(Trash, True, True, True);
    RcLine('restored ' + RcAppDir);
  end
  else
    // The next Setup run heals it (RcMoveAside); the window says so.
    RcLine('error restore ' + RcBackupDir);
end;

function RcIsPayloadName(const Name: String): Boolean;
var
  L: String;
begin
  L := Lowercase(Name);
  Result := (L = 'toontownmultitool.exe') or (L = '_internal') or (L = 'rollcall') or
    (L = '.beta_flavor') or (Pos('unins', L) = 1);
end;

procedure RcDropBackup;
var
  Trash: String;
  FindRec: TFindRec;
begin
  // Success. Rename first (one step), so a backup that is still there on a
  // later run always means "that run did not finish".
  Trash := RcAppDir + RC_TRASH_SUFFIX;
  if DirExists(Trash) then
    DelTree(Trash, True, True, True);
  if not RcRenameWithRetries(RcBackupDir, Trash, 8) then
  begin
    RcLine('warning backup-kept ' + RcBackupDir);
    Exit;
  end;
  RcBackupDir := '';
  // Anything at the top level that is not the app's (something the player
  // put there) comes back.
  if FindFirst(Trash + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
           (not RcIsPayloadName(FindRec.Name)) and
           (not FileOrDirExists(RcAppDir + '\' + FindRec.Name)) then
          RenameFile(Trash + '\' + FindRec.Name, RcAppDir + '\' + FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  DelTree(Trash, True, True, True);
end;

procedure RcSweepShortcuts;
var
  Group: String;
begin
  // The window's switches are the truth: a shortcut an older install made
  // goes when its switch is off.
  if not WizardIsTaskSelected('desktopicon') then
    DeleteFile(ExpandConstant('{autodesktop}\{#MyAppName}.lnk'));
  if not WizardIsTaskSelected('startmenuicon') then
  begin
    Group := ExpandConstant('{group}');
    DeleteFile(Group + '\{#MyAppName}.lnk');
    DeleteFile(Group + '\Uninstall {#MyAppName}.lnk');
    RemoveDir(Group);
  end;
end;

// ── Roll Call: hooks Inno calls during the install ────────────────────────

function RcBeforeFiles: Boolean;
begin
  // [InstallDelete] Check: after the Restart Manager, before CreateDirs.
  // Never raises (a Check cannot stop the run); RcFileDestDir does.
  Result := False;
  if RcHookDone then Exit;
  RcHookDone := True;
  if RcProgressFile = '' then Exit;
  RcHoldWhilePaused;
  if RcCancelRequested then Exit;
  RcMoveAside;
end;

procedure RcFileStarting;
begin
  // [Files] BeforeInstall, once per file, just before RcFileDestDir. It only
  // marks the step: Inno swallows exceptions raised here.
  if not RcCopying then
  begin
    RcCopying := True;
    if RcProgressFile <> '' then
      RcEnterStep(1);
  end;
end;

function RcFileDestDir(Param: String): String;
begin
  // [Files] DestDir, expanded once per file while it is copied (and also
  // while the Restart Manager lists the files, before RcCopying is set).
  // Raising here is a file error: the run stops and is rolled back.
  if (RcProgressFile <> '') and RcCopying then
  begin
    if RcBackupFailed then
    begin
      RcBackupFailed := False;
      RaiseException('The install folder is in use; nothing was changed.');
    end;
    RcCheckpoint('copying');
    if RcTestFailNow then
    begin
      RcTestFailNow := False;
      RcTestFailAt := -1;
      RcLine('error test-failure');
      RaiseException('Simulated failure (/RCTESTFAIL) for a test run.');
    end;
  end;
  Result := ExpandConstant('{app}');
end;

function RcShortcutsCheckpoint: Boolean;
begin
  // [Icons] and [Registry] Check: the files are in. Past the last file a
  // run can no longer be stopped from here (a Check cannot), so a stop asked
  // for now is honoured by the window after Setup ends (fresh install: it
  // runs the uninstaller). A pause still holds.
  Result := True;
  if RcProgressFile = '' then Exit;
  RcEnterStep(2);
  RcHoldWhilePaused;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  Permille: Integer;
begin
  if (RcProgressFile = '') or (MaxProgress <= 0) then Exit;
  Permille := Round((CurProgress * 1.0) / MaxProgress * 1000);
  if (RcTestFailAt >= 0) and (Permille >= RcTestFailAt) then
    RcTestFailNow := True;
  if Permille >= RcLastPermille + 5 then
  begin
    RcLastPermille := Permille;
    RcLine('progress ' + IntToStr(Permille));
  end;
  // Exceptions here are swallowed by Inno: hold for a pause, never stop.
  RcHoldWhilePaused;
end;

// ── Roll Call: handing the double-click to the window ─────────────────────

function RcTempDir: String;
begin
  Result := RemoveBackslashUnlessRoot(GetEnv('TEMP'));
  if Result = '' then
    Result := RemoveBackslashUnlessRoot(ExpandConstant('{tmp}'));
end;

function RcFlavorArgs: String;
begin
  Result :=
    ' --app-name ' + AddQuotes('{#MyAppName}') +
    ' --app-version ' + AddQuotes('{#MyAppVersion}') +
    ' --build {#MyBuildNumber}' +
    ' --app-id ' + AddQuotes('{#MyAppId}') +
    ' --config-dir-name {#ConfigDirName}' +
    ' --channel {#MyAppFlavor}' +
    ' --payload-bytes {#MyPayloadBytes}';
end;

function RcWindowLog: String;
begin
  Result := RcParam('RCLOG');
  if Result = '' then
    Result := RcTempDir + '\ttmt-rollcall.log';
end;

procedure RcStampWindowLog(const S: String);
var
  A: TArrayOfString;
begin
  Log('[RollCall] ' + S);
  SetArrayLength(A, 1);
  A[0] := '[RollCall] ' + S;
  SaveStringsToUTF8FileWithoutBOM(RcWindowLog, A, True);
end;

procedure RcCleanTempAndExit(const Code: Integer);
begin
  // InitializeSetup can only say "abort" (exit code 1). The double-click and
  // the all-users re-run pass on the exit code of the run that did the work.
  // Setup's own cleanup does not run after ExitProcess: remove {tmp} here.
  DelTree(ExpandConstant('{tmp}'), True, True, True);
  RcExitProcess(Code);
end;

function RcRunWindow(const Mode, ReadyFile: String; var Code: Integer): Boolean;
var
  Exe, Dir, Params: String;
begin
  // True when the window ran (whatever it decided). False when it could not
  // start, and Setup carries on without it.
  Result := False;
  Code := 0;
#ifdef HaveRollcall
  try
    ExtractTemporaryFiles('{tmp}\rollcall\*');
  except
    RcStampWindowLog('setup could not unpack the window: ' + GetExceptionMessage);
    Exit;
  end;
#endif
  Dir := ExpandConstant('{tmp}\rollcall');
  Exe := Dir + '\{#RollcallExe}';
  if not FileExists(Exe) then
  begin
    RcStampWindowLog('setup {#MyAppVersion} build {#MyBuildNumber}: no window in this Setup (rollcall {#RollcallState})');
    Exit;
  end;
  Params := '--mode ' + Mode +
    ' --setup ' + AddQuotes(ExpandConstant('{srcexe}')) +
    ' --log ' + AddQuotes(RcWindowLog) +
    ' --ready-file ' + AddQuotes(ReadyFile) +
    RcFlavorArgs;
  if Mode = 'update' then
    Params := Params + ' --app-pid ' + RcParam('RCPID') +
      ' --from-version ' + AddQuotes(RcParam('RCFROM'));
  if RcParam('RCARGS') <> '' then
    Params := Params + ' ' + RcParam('RCARGS');
  RcStampWindowLog('setup {#MyAppVersion} build {#MyBuildNumber} flavor={#MyAppFlavor}: starting the ' + Mode + ' window');
  if not ExecAsOriginalUser(Exe, Params, Dir, SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then
  begin
    RcStampWindowLog('setup could not start the window: ' + SysErrorMessage(Code));
    Exit;
  end;
  RcStampWindowLog('setup: the ' + Mode + ' window exited with ' + IntToStr(Code));
  if Code = RC_EXIT_NO_WINDOW then Exit;
  // A crash (an NTSTATUS, not one of the window's own codes) before the
  // window was ever up is a window that could not start.
  if ((Code < 0) or (Code > 255)) and (not FileExists(ReadyFile)) then Exit;
  Result := True;
end;

// ── Roll Call: install mode for a run that did not choose one ─────────────

function RcExistingInstallAt(const RootKey: Integer): Boolean;
begin
  Result := RegKeyExists(RootKey,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1');
end;

function RcNeedsAllUsersRespawn: Boolean;
begin
  // What UsePreviousPrivileges did while the mode dialog was allowed: an
  // existing all-users install (and no per-user one) is updated in place.
  Result := (not IsAdminInstallMode) and (not RcFlag('ALLUSERS')) and
    (not RcFlag('CURRENTUSER')) and RcExistingInstallAt(HKLM) and
    (not RcExistingInstallAt(HKCU));
end;

procedure RcRespawnAllUsers;
var
  I, Code: Integer;
  P, Params: String;
begin
  Params := '';
  for I := 1 to ParamCount do
  begin
    P := ParamStr(I);
    // The first run keeps its log file open: the second gets its own.
    if Pos('/LOG=', Uppercase(P)) = 1 then
      P := P + '.allusers.log';
    Params := Params + AddQuotes(P) + ' ';
  end;
  Params := Params + '/ALLUSERS';
  Log('[RollCall] the existing install is for all users: running Setup again with ' + Params);
  if not Exec(ExpandConstant('{srcexe}'), Params, '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then
  begin
    Log('[RollCall] could not run Setup again: ' + SysErrorMessage(Code));
    Code := 1;
  end;
  Log('[RollCall] the all-users run exited with ' + IntToStr(Code));
  RcCleanTempAndExit(Code);
end;

// ── Existing wizard helpers ───────────────────────────────────────────────

function CheckUpdatesFlag(Param: String): String;
begin
  if WizardIsTaskSelected('checkupdates') then
    Result := '1'
  else
    Result := '0';
end;

function KeepAliveFlag(Param: String): String;
begin
  if WizardIsTaskSelected('keepalive') then
    Result := '1'
  else
    Result := '0';
end;

function WantSilentRelaunch(): Boolean;
begin
  // The in-app updater runs Setup with /SILENT /RELAUNCH=1 and quits the
  // running app itself, so the Restart Manager has nothing to relaunch
  // (RestartApplications=no). Reopen the freshly-installed app exactly once,
  // and only when the updater asked for it. Never relaunches for an admin's own
  // silent deployment, and never double-launches alongside the interactive
  // postinstall checkbox.
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function IsUpgrade(): Boolean;
var
  KeyPath: String;
begin
  KeyPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1';
  Result := RegKeyExists(HKLM, KeyPath) or RegKeyExists(HKCU, KeyPath);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if (PageID = KeepAliveConsentPage.ID) then
    // A silent install (the in-app updater runs Setup with /SILENT) cannot
    // collect interactive consent, and this page hides Next in CurPageChanged
    // which would strand Inno's silent page driver. Always skip it silently.
    // Inno's UsePreviousTasks default can restore 'keepalive' as selected on a
    // silent upgrade, so the keepalive check alone is not enough to skip it.
    // The user's existing in-app Keep-Alive choice is left untouched either way
    // (installer_merge never strips an existing consent marker).
    Result := WizardSilent or (not WizardIsTaskSelected('keepalive'))
  else
    Result := False;
end;

function GetInstalledBuildNumber(): Integer;
var
  Value: Cardinal;
begin
  Result := 0;
  if RegQueryDWordValue(HKA, 'Software\flossbud\{#MyAppName}', 'BuildNumber', Value) then
    Result := Integer(Value);
end;

function GetInstalledAppVersion(): String;
var
  Value: String;
begin
  Result := '';
  RegQueryStringValue(HKA, 'Software\flossbud\{#MyAppName}', 'AppVersion', Value);
  Result := Value;
end;

function ConfirmDowngrade(): Boolean;
var
  InstalledBuild: Integer;
  IncomingBuild: Integer;
  Msg: String;
begin
  Result := True;
  if not IsUpgrade() then Exit;
  InstalledBuild := GetInstalledBuildNumber();
  IncomingBuild := StrToIntDef('{#MyBuildNumber}', 0);
  if (InstalledBuild > 0) and (IncomingBuild > 0) and (IncomingBuild <= InstalledBuild) then
  begin
    Msg :=
      'You already have ' + GetInstalledAppVersion() + ' (build ' + IntToStr(InstalledBuild) + ') installed.' + #13#10 + #13#10 +
      'Install ' + '{#MyAppVersion}' + ' (build ' + IntToStr(IncomingBuild) + ') anyway?';
    Result := (MsgBox(Msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES);
  end;
end;

function InitializeSetup(): Boolean;
var
  Code: Integer;
  Mode, ReadyFile: String;
  A: TArrayOfString;
begin
  RcProgressFile := RcParam('RCPROGRESS');
  RcStep := -1;
  RcLastPermille := -1000;
  RcTestFailAt := StrToIntDef(RcParam('RCTESTFAIL'), -1);
  Log('[RollCall] setup {#MyAppVersion} build {#MyBuildNumber} flavor={#MyAppFlavor} rollcall={#RollcallState}' +
    ' silent=' + RcBool(WizardSilent) + ' admin-mode=' + RcBool(IsAdminInstallMode) +
    ' window-run=' + RcBool(RcProgressFile <> ''));

  if WizardSilent then
  begin
    if RcProgressFile <> '' then
    begin
      // The window's own run: it chose the mode, the folder and the tasks,
      // and it already asked about anything worth asking.
      RcLine('hello ' + IntToStr(RcGetCurrentProcessId) + ' {#MyAppVersion} {#MyBuildNumber} ' +
        RcBool(IsAdminInstallMode));
      if RcCancelRequested then
      begin
        RcLine('cancelled starting');
        Result := False;
        Exit;
      end;
      RcEnterStep(0);
      Result := True;
      Exit;
    end;
    if RcNeedsAllUsersRespawn then
      RcRespawnAllUsers;
    Result := ConfirmDowngrade();
    Exit;
  end;

  // Double-click: hand over to the window.
  if not RcFlag('RCWIZARD') then
  begin
    Mode := Lowercase(RcParam('RCMODE'));
    if Mode <> 'update' then
      Mode := 'install';
    ReadyFile := RcParam('RCREADY');
    if ReadyFile = '' then
      ReadyFile := RcTempDir + '\ttmt-rollcall-ready-' + IntToStr(RcGetCurrentProcessId) + '.txt';
    if RcRunWindow(Mode, ReadyFile, Code) then
    begin
      if Mode = 'install' then
        DeleteFile(ReadyFile);
      RcCleanTempAndExit(Code);
    end;
    if Mode = 'install' then
      DeleteFile(ReadyFile);
    if Mode = 'update' then
    begin
      // The app is waiting for the window. Tell it there is none (it keeps
      // running and falls back to its old silent update); never show the
      // wizard over a running app.
      SetArrayLength(A, 1);
      A[0] := 'no-window';
      SaveStringsToUTF8FileWithoutBOM(ReadyFile, A, False);
      RcCleanTempAndExit(RC_EXIT_NO_WINDOW);
    end;
    RcStampWindowLog('setup: no window, showing the wizard');
  end;

  // The stock wizard.
  if RcNeedsAllUsersRespawn then
    RcRespawnAllUsers;
  Result := ConfirmDowngrade();
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if RcProgressFile = '' then Exit;
  if CurStep = ssInstall then
  begin
    // Abort here ends Setup before anything changed.
    RcHoldWhilePaused;
    if RcCancelRequested then
    begin
      RcLine('cancelled before-install');
      Abort;
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    RcInstallSucceeded := True;
    RcSweepShortcuts;
    if RcBackupDir <> '' then
      RcDropBackup;
    RcLine('installed');
  end;
end;

procedure DeinitializeSetup();
begin
  if RcProgressFile = '' then Exit;
  if (RcBackupDir <> '') and (not RcInstallSucceeded) then
    RcRestoreBackup;
  RcLine('end');
end;

procedure InitializeWizard;
var
  TasksPage: TWizardPage;
  Anchor: Integer;
  I: Integer;
begin
  // Inno's [Tasks] section auto-generates a TasksList on wpSelectTasks.
  // We augment that page with our own labels — they sit in the same panel
  // and inherit the modern wizard styling automatically.
  TasksPage := PageFromID(wpSelectTasks);
  Anchor := WizardForm.TasksList.Top + WizardForm.TasksList.Height + ScaleY(8);

  // Keep-Alive short note (immediately under the Keep-Alive checkbox)
  KeepAliveShortNote := TLabel.Create(WizardForm);
  KeepAliveShortNote.Parent := TasksPage.Surface;
  KeepAliveShortNote.Left := ScaleX(28);
  KeepAliveShortNote.Top := Anchor;
  KeepAliveShortNote.Width := WizardForm.TasksList.Width - ScaleX(28);
  KeepAliveShortNote.AutoSize := False;
  KeepAliveShortNote.WordWrap := True;
  KeepAliveShortNote.Height := ScaleY(48);
  KeepAliveShortNote.Caption :=
    'Keep-Alive sends automated input to your game windows. Both TTR and CC ' +
    'Terms-of-Service warnings apply. Review the details on the next page ' +
    'if you enable this option.';

  // Updates explainer (under the Updates checkbox)
  UpdatesExplainer := TLabel.Create(WizardForm);
  UpdatesExplainer.Parent := TasksPage.Surface;
  UpdatesExplainer.Left := ScaleX(28);
  UpdatesExplainer.Top := KeepAliveShortNote.Top + KeepAliveShortNote.Height + ScaleY(8);
  UpdatesExplainer.Width := WizardForm.TasksList.Width - ScaleX(28);
  UpdatesExplainer.AutoSize := False;
  UpdatesExplainer.WordWrap := True;
  UpdatesExplainer.Height := ScaleY(32);
  UpdatesExplainer.Caption :=
    'The app will check GitHub for new releases when it launches. ' +
    'You''ll be asked before any update is downloaded or installed.';

  if IsUpgrade() then
  begin
    WizardForm.WelcomeLabel1.Caption := 'Upgrade ' + '{#MyAppName}';
    WizardForm.WelcomeLabel2.Caption :=
      'This wizard will upgrade ' + '{#MyAppName}' + ' to ' + '{#MyAppVersion}' +
      ' (build ' + '{#MyBuildNumber}' + ').' + #13#10 + #13#10 +
      'It is recommended that you close all other applications before continuing.';
  end;

  // ── Keep-Alive consent page ──────────────────────────────────────────────
  // Inserted after wpSelectTasks. Gated by ShouldSkipPage (added in Task 3).
  KeepAliveConsentPage := CreateCustomPage(
    wpSelectTasks,
    'Confirm Keep-Alive Opt-In',
    'Please read the disclaimer below before enabling Keep-Alive on first launch.'
  );

  // TODO: per the design spec, a warning icon (imageres.dll index 79 or a
  // bundled bitmap) should sit to the left of this heading. Deferred — the
  // bold heading + bold red TOS warning carry enough visual gravity for now.

  // Bold heading
  KeepAliveConsentHeading := TLabel.Create(WizardForm);
  KeepAliveConsentHeading.Parent := KeepAliveConsentPage.Surface;
  KeepAliveConsentHeading.Left := ScaleX(28);
  KeepAliveConsentHeading.Top := ScaleY(8);
  KeepAliveConsentHeading.Width := KeepAliveConsentPage.SurfaceWidth - ScaleX(56);
  KeepAliveConsentHeading.AutoSize := False;
  KeepAliveConsentHeading.Height := ScaleY(32);
  KeepAliveConsentHeading.Font.Style := [fsBold];
  KeepAliveConsentHeading.Font.Size := 14;
  KeepAliveConsentHeading.Caption := 'Keep-Alive uses automated input.';

  // Disclaimer paragraph (verbatim from the original inline label)
  KeepAliveConsentDisclaimer := TLabel.Create(WizardForm);
  KeepAliveConsentDisclaimer.Parent := KeepAliveConsentPage.Surface;
  KeepAliveConsentDisclaimer.Left := ScaleX(28);
  KeepAliveConsentDisclaimer.Top := KeepAliveConsentHeading.Top + KeepAliveConsentHeading.Height + ScaleY(8);
  KeepAliveConsentDisclaimer.Width := KeepAliveConsentPage.SurfaceWidth - ScaleX(56);
  KeepAliveConsentDisclaimer.AutoSize := False;
  KeepAliveConsentDisclaimer.WordWrap := True;
  KeepAliveConsentDisclaimer.Height := ScaleY(48);
  KeepAliveConsentDisclaimer.Caption :=
    'Keep-Alive sends a key to your game windows on a timer to prevent the AFK ' +
    'disconnect. This is input not produced by a live keystroke from you.';

  // TOS warning paragraph (verbatim, bold red)
  KeepAliveConsentTOS := TLabel.Create(WizardForm);
  KeepAliveConsentTOS.Parent := KeepAliveConsentPage.Surface;
  KeepAliveConsentTOS.Left := ScaleX(28);
  KeepAliveConsentTOS.Top := KeepAliveConsentDisclaimer.Top + KeepAliveConsentDisclaimer.Height + ScaleY(8);
  KeepAliveConsentTOS.Width := KeepAliveConsentPage.SurfaceWidth - ScaleX(56);
  KeepAliveConsentTOS.AutoSize := False;
  KeepAliveConsentTOS.WordWrap := True;
  KeepAliveConsentTOS.Height := ScaleY(80);
  KeepAliveConsentTOS.Font.Color := $002020D0;  // BGR: red emphasis
  KeepAliveConsentTOS.Font.Style := [fsBold];
  KeepAliveConsentTOS.Caption :=
    'Toontown Rewritten and Corporate Clash both prohibit input automation in ' +
    'their Terms of Service. Use is at your own risk and may result in action ' +
    'against your account. You can turn this off any time in Settings.';

  // Action prompt
  KeepAliveConsentPrompt := TLabel.Create(WizardForm);
  KeepAliveConsentPrompt.Parent := KeepAliveConsentPage.Surface;
  KeepAliveConsentPrompt.Left := ScaleX(28);
  KeepAliveConsentPrompt.Top := KeepAliveConsentTOS.Top + KeepAliveConsentTOS.Height + ScaleY(24);
  KeepAliveConsentPrompt.Width := KeepAliveConsentPage.SurfaceWidth - ScaleX(56);
  KeepAliveConsentPrompt.AutoSize := False;
  KeepAliveConsentPrompt.Height := ScaleY(24);
  KeepAliveConsentPrompt.Font.Style := [fsItalic];
  KeepAliveConsentPrompt.Caption := 'Choose one option below to continue.';

  // ── Locate keepalive in TasksList ────────────────────────────────────────
  // OnConsentDeclineClick will use this index to programmatically uncheck
  // the task. Substring match on the displayed caption text — if it fails
  // (e.g. the [Tasks] description changes upstream), Decline no-ops the
  // uncheck and the install log gets a warning so it surfaces in QA.
  KeepAliveTaskIndex := -1;
  for I := 0 to WizardForm.TasksList.Items.Count - 1 do
    if Pos('Keep-Alive', WizardForm.TasksList.ItemCaption[I]) > 0 then
    begin
      KeepAliveTaskIndex := I;
      Break;
    end;
  if KeepAliveTaskIndex < 0 then
    Log('WARNING: Keep-Alive task index not found in WizardForm.TasksList. ' +
        'Decline auto-uncheck will no-op.');

  // ── Consent-page action buttons ──────────────────────────────────────────
  // Parented to WizardForm (not a page surface) so they live alongside the
  // wizard's native Next/Back/Cancel button row. Visibility is toggled in
  // CurPageChanged (Task 5). OnClick is wired in Task 6.
  BtnConsentDecline := TButton.Create(WizardForm);
  BtnConsentDecline.Parent  := WizardForm;
  BtnConsentDecline.Caption := 'Decline';
  BtnConsentDecline.Default := True;
  BtnConsentDecline.Visible := False;
  BtnConsentDecline.Width   := ScaleX(80);
  BtnConsentDecline.OnClick := @OnConsentDeclineClick;

  BtnConsentAccept := TButton.Create(WizardForm);
  BtnConsentAccept.Parent  := WizardForm;
  BtnConsentAccept.Caption := 'I Accept and Enable Keep-Alive';
  BtnConsentAccept.Visible := False;
  BtnConsentAccept.Width   := ScaleX(220);
  BtnConsentAccept.OnClick := @OnConsentAcceptClick;
end;

procedure OnConsentDeclineClick(Sender: TObject);
begin
  if KeepAliveTaskIndex >= 0 then
    WizardForm.TasksList.Checked[KeepAliveTaskIndex] := False;
  // Advance via the wizard's standard Next-button click handler so all
  // existing hooks (validation, ShouldSkipPage on the next page, etc.) fire.
  WizardForm.NextButton.OnClick(WizardForm.NextButton);
end;

procedure OnConsentAcceptClick(Sender: TObject);
begin
  // Task stays checked. Just advance.
  WizardForm.NextButton.OnClick(WizardForm.NextButton);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = KeepAliveConsentPage.ID) and (not WizardSilent) then
  begin
    // Hide the standard Next and reveal our two consent buttons positioned
    // to the left of the Cancel button. Guarded by `not WizardSilent` as
    // defense in depth: ShouldSkipPage already skips this page when silent, but
    // hiding Next under a silent driver would deadlock it (EAbort), so never do
    // it silently even if page routing changes later.
    WizardForm.NextButton.Visible := False;

    BtnConsentAccept.Top     := WizardForm.NextButton.Top;
    BtnConsentAccept.Height  := WizardForm.NextButton.Height;
    BtnConsentAccept.Left    :=
      WizardForm.CancelButton.Left - BtnConsentAccept.Width - ScaleX(8);
    BtnConsentAccept.Visible := True;

    BtnConsentDecline.Top     := WizardForm.NextButton.Top;
    BtnConsentDecline.Height  := WizardForm.NextButton.Height;
    BtnConsentDecline.Left    :=
      BtnConsentAccept.Left - BtnConsentDecline.Width - ScaleX(8);
    BtnConsentDecline.Visible := True;
  end
  else
  begin
    // Restore the standard Next on every other page; hide the consent buttons.
    WizardForm.NextButton.Visible := True;
    BtnConsentDecline.Visible     := False;
    BtnConsentAccept.Visible      := False;
  end;
end;

// ── Uninstall ─────────────────────────────────────────────────────────────

var
  ShouldPurgeUserData: Boolean;

function RcCopyTree(const Src, Dest: String): Boolean;
var
  FindRec: TFindRec;
  S, D: String;
begin
  Result := ForceDirectories(Dest);
  if not Result then Exit;
  if FindFirst(Src + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          S := Src + '\' + FindRec.Name;
          D := Dest + '\' + FindRec.Name;
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          begin
            if not RcCopyTree(S, D) then
              Result := False;
          end
          else if not CopyFile(S, D, False) then
            Result := False;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function RcHandOverUninstall: Boolean;
var
  Src, Dest, Params: String;
  Code: Integer;
begin
  // The uninstall window runs from a copy outside {app} (which is about to
  // go) and starts this uninstaller again, silently. Not waited on: the
  // silent run must be able to delete this unins000.exe.
  Result := False;
  Src := ExpandConstant('{app}\rollcall');
  if not FileExists(Src + '\{#RollcallExe}') then
  begin
    Log('[RollCall] no uninstall window in ' + Src);
    Exit;
  end;
  Dest := RcTempDir + '\ttmt-rollcall-uninstall-' + IntToStr(RcGetCurrentProcessId);
  if DirExists(Dest) then
    DelTree(Dest, True, True, True);
  if not RcCopyTree(Src, Dest) then
  begin
    Log('[RollCall] could not copy the uninstall window to ' + Dest);
    DelTree(Dest, True, True, True);
    Exit;
  end;
  Params := '--mode uninstall' +
    ' --uninstaller ' + AddQuotes(ExpandConstant('{uninstallexe}')) +
    ' --app-dir ' + AddQuotes(RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) +
    ' --log ' + AddQuotes(RcWindowLog) +
    ' --self-dir ' + AddQuotes(Dest) +
    RcFlavorArgs;
  if RcParam('RCARGS') <> '' then
    Params := Params + ' ' + RcParam('RCARGS');
  RcStampWindowLog('uninstaller {#MyAppVersion} build {#MyBuildNumber}: starting the uninstall window');
  Result := Exec(Dest + '\{#RollcallExe}', Params, Dest, SW_SHOWNORMAL, ewNoWait, Code);
  if not Result then
  begin
    RcStampWindowLog('uninstaller could not start the window: ' + SysErrorMessage(Code));
    DelTree(Dest, True, True, True);
  end;
end;

function InitializeUninstall(): Boolean;
var
  Response: Integer;
  Msg: String;
begin
  ShouldPurgeUserData := False;
  RcProgressFile := RcParam('RCPROGRESS');
  Log('[RollCall] uninstaller {#MyAppVersion} build {#MyBuildNumber} flavor={#MyAppFlavor}' +
    ' silent=' + RcBool(UninstallSilent) + ' window-run=' + RcBool(RcProgressFile <> ''));
  // /SILENT and /VERYSILENT suppress MsgBox (it returns 0, which falls
  // through to the else branch and aborts uninstall). In silent mode just
  // proceed without prompting; the user-data purge stays off (the user
  // didn't ask for it; the uninstall window removes it itself, as the
  // player, when its box is ticked).
  if UninstallSilent then
  begin
    if RcProgressFile <> '' then
      RcLine('hello ' + IntToStr(RcGetCurrentProcessId) + ' {#MyAppVersion} {#MyBuildNumber} uninstall');
    Result := True;
    Exit;
  end;
  if (not RcFlag('RCWIZARD')) and RcHandOverUninstall then
  begin
    Result := False;
    Exit;
  end;
  Msg :=
    '{#MyAppName} will be removed from your computer.' + #13#10 + #13#10 +
    'Do you also want to remove your saved settings, accounts, and profiles?' + #13#10 + #13#10 +
    '  Yes   — Remove the app AND wipe settings/accounts/profiles.' + #13#10 +
    '  No    — Remove the app, keep settings for a future reinstall (recommended).' + #13#10 +
    '  Cancel — Don''t uninstall anything.' + #13#10 + #13#10 +
    'Note: saved passwords are stored in Windows Credential Locker and are not ' +
    'removed by either option. To remove saved passwords, clear them from inside ' +
    'the app before uninstalling, or use Windows Credential Manager.';
  Response := MsgBox(Msg, mbConfirmation, MB_YESNOCANCEL);
  case Response of
    IDYES:    begin ShouldPurgeUserData := True;  Result := True;  end;
    IDNO:     begin ShouldPurgeUserData := False; Result := True;  end;
    IDCANCEL: Result := False;
  else
    Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ConfigDir: String;
begin
  if CurUninstallStep = usUninstall then
    RcLine('removing')
  else if CurUninstallStep = usPostUninstall then
  begin
    RcLine('removed');
    if ShouldPurgeUserData then
    begin
      ConfigDir := ExpandConstant('{userprofile}\.config\{#ConfigDirName}');
      if DirExists(ConfigDir) then
        DelTree(ConfigDir, True, True, True);
    end;
  end;
end;

procedure DeinitializeUninstall();
begin
  RcLine('end');
end;
