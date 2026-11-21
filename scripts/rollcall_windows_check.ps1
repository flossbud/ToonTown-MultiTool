# Roll Call on a real Windows desktop (CI: test-windows.yml, test-windows-rollcall).
#
# Each phase drives the shipped Setup end to end and proves the outcome with
# files, registry keys and log stamps, never with an exit code alone. Run the
# phases in this order on a clean machine:
#
#   cancel     fresh PC: Install, stopped mid-copy  -> nothing left behind
#   install    double-click, the window clicks Install -> installed, choices saved
#   fail       Repair with a forced copy failure    -> the previous version is back
#   update     the app hands over to the update window -> updated and reopened
#   uninstall  unins000.exe hands over to the uninstall window -> removed
#
#   pwsh scripts/rollcall_windows_check.ps1 -Phase <name> -Setup <Setup.exe> -Out <dir>
param(
    [Parameter(Mandatory)] [ValidateSet('cancel', 'install', 'fail', 'update', 'uninstall')]
    [string] $Phase,
    [Parameter(Mandatory)] [string] $Setup,
    [Parameter(Mandatory)] [string] $Out,
    [string] $AppName = 'ToonTown MultiTool',
    [string] $ConfigDirName = 'toontown_multitool'
)
$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$appId = ((Get-Content (Join-Path $repo 'packaging\windows\guids.env')) |
    Where-Object { $_ -like 'STABLE_APPID=*' }).Split('=', 2)[1]
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${appId}_is1"
$appDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$appExe = Join-Path $appDir 'ToonTownMultiTool.exe'
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName\$AppName.lnk"
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"
$settings = Join-Path $env:USERPROFILE ".config\$ConfigDirName\settings.json"
$windowLog = Join-Path $env:TEMP 'ttmt-rollcall.log'
$shots = Join-Path $Out "shots-$Phase"
New-Item -ItemType Directory -Force -Path $Out, $shots | Out-Null

function Fail([string] $why) {
    Write-Host "::error::rollcall $Phase`: $why"
    throw "rollcall $Phase`: $why"
}

function Check([bool] $ok, [string] $what) {
    if ($ok) { Write-Host "  ok    $what" } else { Fail $what }
}

function Mark-Log {
    # Everything this phase adds to the shared window log starts after this.
    if (Test-Path $windowLog) { return (Get-Item $windowLog).Length }
    return 0
}

function Log-Since([long] $mark) {
    if (-not (Test-Path $windowLog)) { return '' }
    $all = [IO.File]::ReadAllBytes($windowLog)
    if ($mark -ge $all.Length) { return '' }
    return [Text.Encoding]::UTF8.GetString($all, $mark, $all.Length - $mark)
}

function Wait-Log([long] $mark, [string[]] $any, [int] $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $text = Log-Since $mark
        foreach ($needle in $any) { if ($text.Contains($needle)) { return $text } }
        Start-Sleep -Milliseconds 500
    }
    return (Log-Since $mark)
}

function Save-Screen([string] $name) {
    # The whole desktop, for whatever a hung process is showing (a message
    # box, a window behind another). Never fails the phase.
    try {
        Add-Type -AssemblyName System.Windows.Forms, System.Drawing
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
        $path = Join-Path $Out "$name.png"
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose(); $bitmap.Dispose()
        Write-Host "  shot  $path"
    } catch {
        Write-Host "  (no screenshot: $($_.Exception.Message))"
    }
}

function Show-Captured([string] $capture) {
    foreach ($stream in 'out', 'err') {
        $file = Join-Path $Out "$capture.$stream"
        Write-Host "--- $capture std$stream ---"
        if (Test-Path $file) { Get-Content $file | ForEach-Object { Write-Host $_ } }
    }
    Write-Host '--- end ---'
}

function Start-And-Wait([string] $file, $arguments, [int] $seconds = 300,
                        [string] $capture = '', [string] $workdir = '') {
    # Waits for the process itself. Start-Process -Wait would also wait for
    # everything it started (the reopened app never exits).
    #
    # -capture NAME sends stdout/stderr to $Out\NAME.out/.err. A windowed
    # Python build started without them has sys.stdout = None, so anything
    # that writes to it raises, and PyInstaller shows a message box that
    # never goes away: the app's --self-check hung exactly so (CI 44838083868).
    #
    # On a timeout: a screenshot, the process tree is killed (so it cannot
    # hold files for the next phase), then the phase fails.
    $extra = @{}
    if ($capture) {
        $extra.RedirectStandardOutput = Join-Path $Out "$capture.out"
        $extra.RedirectStandardError = Join-Path $Out "$capture.err"
    }
    if ($workdir) { $extra.WorkingDirectory = $workdir }
    $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru @extra
    $null = $p.Handle          # keeps ExitCode readable after the exit
    if (-not $p.WaitForExit($seconds * 1000)) {
        $p.Refresh()
        Write-Host "  hung  pid $($p.Id), window title: '$($p.MainWindowTitle)'"
        Save-Screen "$(if ($capture) { $capture } else { 'process' })-timeout"
        try { $p.Kill($true) } catch { Write-Host "  (kill: $($_.Exception.Message))" }
        $null = $p.WaitForExit(15000)
        if ($capture) { Show-Captured $capture }
        Fail "$file did not exit within $seconds s (killed)"
    }
    if ($capture) { Show-Captured $capture }
    return $p.ExitCode
}

function Run-Setup([string[]] $arguments) {
    Write-Host "  run   $Setup $($arguments -join ' ')"
    $code = Start-And-Wait $Setup $arguments
    Write-Host "  exit  $code"
    return $code
}

function Self-Check([string] $capture) {
    # Captured like the other jobs' --self-check, so its output is in the
    # artifact and sys.stdout exists.
    $code = Start-And-Wait $appExe '--self-check' 120 $capture
    $out = Join-Path $Out "$capture.out"
    $said = (Test-Path $out) -and ((Get-Content $out -Raw) -match 'self-check OK')
    Check ($code -eq 0 -and $said) "installed app --self-check (exit $code, said OK: $said)"
}

function Require-Install {
    # Later phases build on the install phase; say so plainly when it is not there.
    Check ((Test-Path $uninstallKey) -and (Test-Path $appExe)) 'installed by the install phase'
}

function Stop-Leftovers {
    # A failed phase must not leave Setup or a window running into the next
    # one. Setup and its temp copy, and every Roll Call window; never the app.
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and ($_.Path -eq $Setup -or $_.Path -like '*\is-*.tmp\*' -or
                                     $_.Path -like '*\rollcall.exe') } |
        ForEach-Object {
            Write-Host "  stop  $($_.Id) $($_.Path)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
}

function Show-Log([long] $mark) {
    Write-Host '--- window log (this phase) ---'
    Write-Host (Log-Since $mark)
    Write-Host '--- end ---'
}

function Copy-Logs {
    if (Test-Path $windowLog) { Copy-Item $windowLog (Join-Path $Out 'ttmt-rollcall.log') -Force }
    Get-ChildItem $env:TEMP -Directory -Filter 'ttmt-*' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $log = Join-Path $_.FullName 'setup.log'
            if (Test-Path $log) { Copy-Item $log (Join-Path $Out "$($_.Name)-setup.log") -Force }
        }
}

$mark = Mark-Log
try {
    switch ($Phase) {

        'cancel' {
            Check (-not (Test-Path $uninstallKey)) 'clean machine: no install recorded'
            $code = Run-Setup @("/LOG=`"$Out\setup-cancel-first.log`"",
                                "`"/RCARGS=--auto --shots $shots --test-cancel-at 300`"")
            Show-Log $mark
            $log = Log-Since $mark
            Check ($log.Contains("setup ") -and $log.Contains('starting the install window')) 'Setup stamp: handed over to the window'
            Check ($log.Contains('install window, engine=inno')) 'window stamp: install window, real engine'
            Check ($log.Contains('test: stopping the install at')) 'the stop was asked mid-copy'
            Check ($log.Contains('cancelled; the PC is as it was')) 'the engine saw the rollback finish'
            Check ($code -eq 2) "Setup exit code is the window's 'cancelled' (2), got $code"
            Check (-not (Test-Path $appDir)) "nothing left in $appDir"
            Check (-not (Test-Path $uninstallKey)) 'no uninstall entry'
            Check (-not (Test-Path $startMenu)) 'no Start Menu entry'
            Check (-not (Test-Path $desktop)) 'no desktop shortcut'
            Check (-not (Test-Path $settings)) 'no settings written'
            $left = Get-ChildItem $env:TEMP -Directory -Filter 'ttmt-setup-*' -ErrorAction SilentlyContinue
            Check (-not $left) "no run folder left in TEMP ($($left.Name -join ', '))"
        }

        'install' {
            $code = Run-Setup @("/LOG=`"$Out\setup-install-first.log`"",
                                "`"/RCARGS=--auto --shots $shots`"")
            Show-Log $mark
            $log = Log-Since $mark
            Check ($log.Contains('install window, engine=inno')) 'window stamp'
            Check ($log.Contains('install finished')) 'the engine finished'
            Check ($code -eq 0) "Setup exit code 0, got $code"
            Check (Test-Path $appExe) "the app is in $appDir"
            Check (Test-Path (Join-Path $appDir 'rollcall\rollcall.exe')) 'the uninstall window is installed with it'
            Check (Test-Path $uninstallKey) 'per-user uninstall entry'
            $path = (Get-ItemProperty $uninstallKey).'Inno Setup: App Path'
            Check ($path -eq $appDir) "recorded folder is $appDir ($path)"
            Check (Test-Path $startMenu) 'Start Menu entry (window default: on)'
            Check (Test-Path $desktop) 'desktop shortcut (window default: on)'
            Check (Test-Path $settings) 'choices saved as the player'
            $json = Get-Content $settings -Raw | ConvertFrom-Json
            Check ($json.check_for_updates_at_startup -eq $true) 'check_for_updates_at_startup saved'
            Check (-not (Test-Path "$appDir.previous-version")) 'no backup folder'
            Self-Check 'selfcheck-install'
        }

        'fail' {
            Require-Install
            $marker = Join-Path $appDir '_internal\rollcall-ci-marker.txt'
            Set-Content -Path $marker -Value 'the previous version'
            $before = (Get-ChildItem $appDir -Recurse -File).Count
            $code = Run-Setup @("/LOG=`"$Out\setup-fail-first.log`"",
                                "`"/RCARGS=--auto --shots $shots --test-fail-at 500`"")
            Show-Log $mark
            $log = Log-Since $mark
            Check ($log.Contains('failed at step 1')) 'the copy step failed'
            Check ($log.Contains('restored=True')) 'Setup put the previous version back'
            Check ($log.Contains('intact=True')) 'the window was told the previous version is intact'
            Check ($code -eq 1) "Setup exit code is the window's 'failed' (1), got $code"
            Check (Test-Path $marker) 'the previous files are back (marker file survived)'
            $after = (Get-ChildItem $appDir -Recurse -File).Count
            Check ($after -eq $before) "same file count as before ($before -> $after)"
            Check (-not (Test-Path "$appDir.previous-version")) 'no backup folder left'
            Check (-not (Test-Path "$appDir.removing")) 'no trash folder left'
            Check (Test-Path $uninstallKey) 'still installed'
            Self-Check 'selfcheck-fail'
            Remove-Item $marker
        }

        'update' {
            Require-Install
            # A stand-in for the running app: the real handoff code, in a
            # Python process that exits as soon as it returns True (what the
            # app does: it quits), exactly like "Restart & update". It runs
            # in the install folder, as the app does when started from its
            # shortcuts: Setup must not inherit that folder, or the update
            # cannot move the installed version aside.
            $stand = @"
import os, sys
sys.path.insert(0, r'$repo')
from utils.rollcall.handoff import start_update_window
ok = start_update_window(r'$Setup', app_pid=os.getpid(), from_version='v0.0.1-ci')
print('HANDOFF', ok, os.getpid(), flush=True)
sys.exit(0 if ok else 1)
"@
            Set-Content -Path (Join-Path $Out 'standin.py') -Value $stand
            $code = Start-And-Wait python "`"$(Join-Path $Out 'standin.py')`"" 120 'standin' $appDir
            Check ($code -eq 0) 'the handoff returned True once the update window was up'
            $log = Wait-Log $mark @('update finished', 'failed at step') 240
            Show-Log $mark
            Check ($log.Contains('update window, engine=inno')) 'window stamp'
            Check ($log.Contains('ready file')) 'the window told the app to quit'
            Check (-not $log.Contains('backup in-use')) 'nothing held the install folder (Setup was not started in it)'
            Check ($log.Contains('backup=ok')) 'Setup moved the installed version aside before copying'
            Check ($log.Contains('update finished')) 'the update finished with the app window on screen'
            $running = Get-Process -Name ToonTownMultiTool -ErrorAction SilentlyContinue |
                Where-Object { $_.Path -eq $appExe }
            Check ([bool]$running) 'the app was reopened from the install folder'
            Check (-not (Test-Path "$appDir.previous-version")) 'no backup folder left'
        }

        'uninstall' {
            Require-Install
            $unins = Join-Path $appDir 'unins000.exe'
            Check (Test-Path $unins) 'uninstaller present'
            $running = Get-Process -Name ToonTownMultiTool -ErrorAction SilentlyContinue
            Write-Host "  app running before: $([bool]$running)"
            $code = Start-And-Wait $unins "`"/RCARGS=--auto --shots $shots`"" 120
            Write-Host "  unins000.exe handed over and exited ($code)"
            $log = Wait-Log $mark @('uninstall finished', 'failed at step') 240
            Show-Log $mark
            Check ($log.Contains('starting the uninstall window')) 'uninstaller stamp: handed over'
            Check ($log.Contains('uninstall window, engine=inno')) 'window stamp'
            if ($running) {
                Check ($log.Contains(': accepted')) 'the running app took the quit request'
            }
            Check ($log.Contains('uninstall finished')) 'the engine finished'
            Check (-not (Test-Path $appDir)) "$appDir removed"
            Check (-not (Test-Path $uninstallKey)) 'uninstall entry removed'
            Check (-not (Test-Path $startMenu)) 'Start Menu entry removed'
            Check (-not (Test-Path $desktop)) 'desktop shortcut removed'
            Check (Test-Path $settings) 'user data kept (the box was not ticked)'
            Check (-not (Get-Process -Name ToonTownMultiTool -ErrorAction SilentlyContinue)) 'the app is closed'
            # The window ran from a temp copy and leaves a cleaner behind for
            # it, which retries for up to a minute while the window's files
            # stay locked and then logs what became of the folder.
            $log = Wait-Log $mark @('temp copy removed', 'temp copy still there',
                                    'could not start the cleaner', 'no cleaner:') 90
            ($log -split "`r?`n") | Where-Object { $_ -like '*temp copy*' } |
                ForEach-Object { Write-Host "  $_" }
            $copies = Get-ChildItem $env:TEMP -Directory -Filter 'ttmt-rollcall-uninstall-*' -ErrorAction SilentlyContinue
            foreach ($copy in $copies) {
                Get-ChildItem $copy.FullName -Recurse -File -ErrorAction SilentlyContinue |
                    Select-Object -First 10 | ForEach-Object { Write-Host "  left  $($_.FullName)" }
            }
            Check ($log.Contains('temp copy: cleaner started')) 'the window started a cleaner for its temp copy'
            Check ($log.Contains('temp copy removed')) 'the cleaner removed the temp copy'
            Check (-not $copies) "the window's temp copy is gone ($($copies.Name -join ', '))"
        }
    }
    Write-Host "ROLLCALL $($Phase.ToUpper()) OK"
}
catch {
    Save-Screen "$Phase-failed"
    Stop-Leftovers
    throw
}
finally {
    Copy-Logs
}
