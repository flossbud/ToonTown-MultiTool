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

[UninstallDelete]
; The user-data purge is handled in [Code] via InitializeUninstall + DelTree
; so the channel-specific config dir is removed only when the user opts in.
