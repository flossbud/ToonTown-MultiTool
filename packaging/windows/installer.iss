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

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if (PageID = KeepAliveConsentPage.ID) then
    Result := not WizardIsTaskSelected('keepalive')
  else
    Result := False;
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
  if (CurPageID = KeepAliveConsentPage.ID) then
  begin
    // Hide the standard Next and reveal our two consent buttons positioned
    // to the left of the Cancel button.
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
