; ToonTown MultiTool — Inno Setup script
; Driven by /D defines from CI (build-windows.yml): MyAppVersion, MyAppName, MyAppId,
; MyAppFlavor (stable|beta), ConfigDirName, OutputBaseFilename.
;
; Local build example (from repo root):
;   ISCC.exe /DMyAppVersion=vDEV /DMyAppName="ToonTown MultiTool" \
;            /DMyAppId={8B2F4F8C-...} /DMyAppFlavor=stable \
;            /DConfigDirName=toontown_multitool \
;            /DOutputBaseFilename=ToonTownMultiTool-Setup-vDEV-Windows-x86_64 \
;            packaging\windows\installer.iss

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
  #define OutputBaseFilename "ToonTownMultiTool-Setup-" + MyAppVersion + "-Windows-x86_64"
#endif
#ifndef MyBuildNumber
  #define MyBuildNumber "0"
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
PrivilegesRequiredOverridesAllowed=dialog commandline
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
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "keepalive";   Description: "Enable &Keep-Alive on first launch (TOS warning applies)"; GroupDescription: "Keep-Alive:"; Flags: unchecked
Name: "checkupdates"; Description: "Check for &updates at startup"; GroupDescription: "Updates:"
Name: "launchapp";   Description: "&Launch {#MyAppName} after install"; GroupDescription: "After install:"

[Registry]
Root: HKCU; Subkey: "Software\flossbud\{#MyAppName}"; ValueType: dword; ValueName: "BuildNumber"; ValueData: "{#MyBuildNumber}"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\flossbud\{#MyAppName}"; ValueType: string; ValueName: "AppVersion"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletevalue

[Files]
Source: "..\..\dist\ToonTownMultiTool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"; Tasks: desktopicon

[Run]
; Persist the wizard's checkbox choices into settings.json. The just-installed
; EXE owns the merge logic (utils.installer_merge); we just call it with flags.
Filename: "{app}\ToonTownMultiTool.exe"; \
  Parameters: "--apply-installer-config --check-updates={code:CheckUpdatesFlag} --keep-alive={code:KeepAliveFlag}"; \
  Flags: runhidden waituntilterminated

; Launch the app if the user kept the "Launch" checkbox.
Filename: "{app}\ToonTownMultiTool.exe"; \
  Description: "Launch {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent; \
  Tasks: launchapp

[UninstallDelete]
; The user-data purge is handled in [Code] via InitializeUninstall + DelTree
; so the channel-specific config dir is removed only when the user opts in.

[Code]
var
  KeepAliveShortNote: TLabel;
  UpdatesExplainer: TLabel;

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

function IsUpgrade(): Boolean;
var
  KeyPath: String;
begin
  KeyPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{#MyAppId}' + '_is1';
  Result := RegKeyExists(HKLM, KeyPath) or RegKeyExists(HKCU, KeyPath);
end;

function GetInstalledBuildNumber(): Integer;
var
  Value: Cardinal;
begin
  Result := 0;
  if RegQueryDWordValue(HKCU, 'Software\flossbud\{#MyAppName}', 'BuildNumber', Value) then
    Result := Integer(Value);
end;

function GetInstalledAppVersion(): String;
var
  Value: String;
begin
  Result := '';
  RegQueryStringValue(HKCU, 'Software\flossbud\{#MyAppName}', 'AppVersion', Value);
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
begin
  Result := ConfirmDowngrade();
end;

procedure InitializeWizard;
var
  TasksPage: TWizardPage;
  Anchor: Integer;
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
  KeepAliveShortNote.Height := ScaleY(36);
  KeepAliveShortNote.Caption :=
    'Keep-Alive sends automated input to your game windows. Both TTR and CC ' +
    'TOS warnings apply - review the details on the next page if you enable it.';

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
end;

var
  ShouldPurgeUserData: Boolean;

function InitializeUninstall(): Boolean;
var
  Response: Integer;
  Msg: String;
  CmdTail: String;
begin
  ShouldPurgeUserData := False;
  // /SILENT and /VERYSILENT suppress MsgBox (it returns 0, which falls
  // through to the else branch and aborts uninstall). In silent mode just
  // proceed without prompting; the user-data purge stays off (the user
  // didn't ask for it).
  CmdTail := UpperCase(GetCmdTail());
  if (Pos('/VERYSILENT', CmdTail) > 0) or (Pos('/SILENT', CmdTail) > 0) then
  begin
    Result := True;
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
  if CurUninstallStep = usPostUninstall then
  begin
    if ShouldPurgeUserData then
    begin
      ConfigDir := ExpandConstant('{userprofile}\.config\{#ConfigDirName}');
      if DirExists(ConfigDir) then
        DelTree(ConfigDir, True, True, True);
    end;
  end;
end;
