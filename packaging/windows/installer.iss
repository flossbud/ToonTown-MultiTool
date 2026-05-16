; ToonTown MultiTool — Inno Setup script
; Driven by /D defines from CI (build.yml): MyAppVersion, MyAppName, MyAppId,
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

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
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

[Files]
Source: "..\..\dist\ToonTownMultiTool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\ToonTownMultiTool.exe"; Tasks: desktopicon

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
  KeepAliveDisclaimer: TLabel;
  KeepAliveWarning: TLabel;
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

  // Keep-Alive disclaimer paragraphs (immediately under the Keep-Alive checkbox)
  KeepAliveDisclaimer := TLabel.Create(WizardForm);
  KeepAliveDisclaimer.Parent := TasksPage.Surface;
  KeepAliveDisclaimer.Left := ScaleX(28);
  KeepAliveDisclaimer.Top := Anchor;
  KeepAliveDisclaimer.Width := WizardForm.TasksList.Width - ScaleX(28);
  KeepAliveDisclaimer.AutoSize := False;
  KeepAliveDisclaimer.WordWrap := True;
  KeepAliveDisclaimer.Height := ScaleY(48);
  KeepAliveDisclaimer.Caption :=
    'Keep-Alive sends a key to your game windows on a timer to prevent the AFK ' +
    'disconnect. This is input not produced by a live keystroke from you.';

  KeepAliveWarning := TLabel.Create(WizardForm);
  KeepAliveWarning.Parent := TasksPage.Surface;
  KeepAliveWarning.Left := ScaleX(28);
  KeepAliveWarning.Top := KeepAliveDisclaimer.Top + KeepAliveDisclaimer.Height + ScaleY(4);
  KeepAliveWarning.Width := WizardForm.TasksList.Width - ScaleX(28);
  KeepAliveWarning.AutoSize := False;
  KeepAliveWarning.WordWrap := True;
  KeepAliveWarning.Height := ScaleY(64);
  KeepAliveWarning.Font.Color := $002020D0;  // BGR: red emphasis
  KeepAliveWarning.Font.Style := [fsBold];   // bold survives high-contrast themes
  KeepAliveWarning.Caption :=
    'Toontown Rewritten and Corporate Clash both prohibit input automation in ' +
    'their Terms of Service. Use is at your own risk and may result in action ' +
    'against your account. You can turn this off any time in Settings.';

  // Updates explainer (under the Updates checkbox)
  UpdatesExplainer := TLabel.Create(WizardForm);
  UpdatesExplainer.Parent := TasksPage.Surface;
  UpdatesExplainer.Left := ScaleX(28);
  UpdatesExplainer.Top := KeepAliveWarning.Top + KeepAliveWarning.Height + ScaleY(8);
  UpdatesExplainer.Width := WizardForm.TasksList.Width - ScaleX(28);
  UpdatesExplainer.AutoSize := False;
  UpdatesExplainer.WordWrap := True;
  UpdatesExplainer.Height := ScaleY(32);
  UpdatesExplainer.Caption :=
    'The app will check GitHub for new releases when it launches. ' +
    'You''ll be asked before any update is downloaded or installed.';
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
