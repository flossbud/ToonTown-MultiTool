# Windows installer

Inno Setup 6 script that wraps the PyInstaller onedir build into a wizard
installer. Built by CI on every tag; local builds for testing follow the
steps below.

## Prerequisites

- Windows 10/11 (or Wine on Linux, but CI is the reference build env)
- Inno Setup 6: `choco install innosetup` or download from
  https://jrsoftware.org/isinfo.php
- A completed PyInstaller build at `dist\ToonTownMultiTool\`

## Build the PyInstaller payload

From the repo root, on Windows:

```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm ToonTownMultiTool.spec
```

## Build the stable installer locally

Source the GUIDs from `guids.env`, then run ISCC:

```
for /f "tokens=1,* delims==" %A in (packaging\windows\guids.env) do set %A=%B
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" ^
  /DMyAppVersion=vDEV ^
  /DMyAppName="ToonTown MultiTool" ^
  /DMyAppId=%STABLE_APPID% ^
  /DMyAppFlavor=stable ^
  /DConfigDirName=toontown_multitool ^
  /DOutputBaseFilename=ToonTownMultiTool-Setup-vDEV-Windows-x86_64 ^
  packaging\windows\installer.iss
```

Output: `packaging\windows\Output\ToonTownMultiTool-Setup-vDEV-Windows-x86_64.exe`

## Build the beta installer locally

```
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" ^
  /DMyAppVersion=vDEV-a ^
  /DMyAppName="ToonTown MultiTool Beta" ^
  /DMyAppId=%BETA_APPID% ^
  /DMyAppFlavor=beta ^
  /DConfigDirName=toontown_multitool_beta ^
  /DOutputBaseFilename=ToonTownMultiTool-Setup-vDEV-a-Windows-x86_64 ^
  packaging\windows\installer.iss
```

The beta build additionally requires a `.beta_flavor` sentinel file at
`dist\ToonTownMultiTool\.beta_flavor` so `utils.build_flavor.is_beta()` returns
true at runtime. CI drops this automatically; locally do:

```
type nul > dist\ToonTownMultiTool\.beta_flavor
```

## Smoke-test the installer silently

```
ToonTownMultiTool-Setup-vDEV-Windows-x86_64.exe /VERYSILENT /SUPPRESSMSGBOXES ^
  /DIR=%TEMP%\ttmt-test /LOG=%TEMP%\install.log
"%TEMP%\ttmt-test\ToonTownMultiTool.exe" --version
"%TEMP%\ttmt-test\unins000.exe" /VERYSILENT
```

## SmartScreen

The installer is unsigned. Users will see "Windows protected your PC" on first
download. They click "More info" then "Run anyway". This is the same trust posture
as the existing zipped EXE. See the parent spec for code-signing options.
