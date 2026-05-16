<#
.SYNOPSIS
    ToonTown MultiTool dependency installer for Windows.

.DESCRIPTION
    Detects a supported Python interpreter (3.9 to 3.13) on PATH or via
    the py launcher, creates a venv at .\venv, and installs the Python
    dependencies from requirements.txt. PySide6 wheels are self-contained
    on Windows, so no system package install is needed.

.PARAMETER Yes
    Skip all confirmation prompts. (Currently no-op; reserved for parity
    with install.sh and for future use.)

.PARAMETER Force
    Wipe .\venv and redo everything regardless of idempotency state.

.PARAMETER SkipSystemDeps
    No-op on Windows. Kept for cross-platform flag parity with install.sh.

.PARAMETER Help
    Show this help and exit.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$Force,
    [switch]$SkipSystemDeps,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit 0
}

# Move to the script's directory so relative paths work regardless of cwd
Set-Location -Path $PSScriptRoot

$VenvDir = '.\venv'
$Sentinel = Join-Path $VenvDir '.requirements.sha'

function Get-RequirementsHash {
    $hash = Get-FileHash -Path 'requirements.txt' -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
}

function Get-VenvPythonVersion {
    $py = Join-Path $VenvDir 'Scripts\python.exe'
    if (-not (Test-Path $py)) { return $null }
    try {
        $output = & $py -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>$null
        return $output.Trim()
    } catch {
        return $null
    }
}

function Test-VenvPythonInRange {
    $v = Get-VenvPythonVersion
    return $v -in @('3.9', '3.10', '3.11', '3.12', '3.13')
}

# Idempotency early-exit
if (-not $Force) {
    if ((Test-Path (Join-Path $VenvDir 'Scripts\python.exe')) `
        -and (Test-VenvPythonInRange) `
        -and (Test-Path $Sentinel)) {
        $current = (Get-Content $Sentinel -Raw).Trim().ToLowerInvariant()
        if ($current -eq (Get-RequirementsHash)) {
            Write-Host 'venv is already up to date.'
            Write-Host 'Activate with: .\venv\Scripts\Activate.ps1'
            Write-Host 'Then run: python main.py'
            exit 0
        }
    }
}

# Find a supported Python (3.13 down to 3.9)
function Find-SupportedPython {
    # Pre-check command availability so a missing `py` or `python` does not
    # turn into a PowerShell "command not found" error (which Stop-mode
    # terminates on, before we get to the LASTEXITCODE check).
    $pyAvailable = $null -ne (Get-Command py -ErrorAction SilentlyContinue)
    $pythonAvailable = $null -ne (Get-Command python -ErrorAction SilentlyContinue)

    if ($pyAvailable) {
        foreach ($v in '3.13', '3.12', '3.11', '3.10', '3.9') {
            # Try py launcher first (standard on python.org installs)
            $pyOutput = & py "-$v" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $pyOutput) {
                return @{
                    Launcher = "py"
                    Version = $v
                    Path = $pyOutput.Trim()
                }
            }
        }
    }

    if ($pythonAvailable) {
        # Fallback: try plain python on PATH
        $pythonOutput = & python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>$null
        if ($LASTEXITCODE -eq 0 -and $pythonOutput) {
            $v = $pythonOutput.Trim()
            if ($v -in @('3.9', '3.10', '3.11', '3.12', '3.13')) {
                $path = & python -c 'import sys; print(sys.executable)' 2>$null
                return @{
                    Launcher = "python"
                    Version = $v
                    Path = $path.Trim()
                }
            }
        }
    }

    return $null
}

$pythonInfo = Find-SupportedPython
if (-not $pythonInfo) {
    Write-Host ''
    Write-Host 'No supported Python (3.9 to 3.13) found on PATH or via the py launcher.'
    Write-Host ''
    Write-Host 'To install Python 3.13:'
    Write-Host '  winget install Python.Python.3.13'
    Write-Host ''
    Write-Host 'After installation, open a new PowerShell window and re-run .\install.ps1.'
    exit 1
}

Write-Host "Found supported Python $($pythonInfo.Version): $($pythonInfo.Path)"

# Handle existing wrong-version venv
$recreateVenv = $false
if (Test-Path $VenvDir) {
    if (-not (Test-VenvPythonInRange)) {
        Write-Host ''
        Write-Host "Existing $VenvDir has a missing or unsupported Python interpreter."
        if ($Force -or $Yes) {
            $recreateVenv = $true
        } else {
            $reply = Read-Host "Delete and recreate with Python $($pythonInfo.Version)? [y/N]"
            if ($reply -match '^(y|yes)$') {
                $recreateVenv = $true
            } else {
                Write-Error 'Aborted. Run .\install.ps1 -Force to skip this prompt.'
                exit 1
            }
        }
    }
}

if ($Force -or $recreateVenv) {
    Write-Host "Removing existing $VenvDir..."
    Remove-Item -Path $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvDir)) {
    Write-Host ''
    Write-Host "Creating venv at $VenvDir with Python $($pythonInfo.Version)..."
    if ($pythonInfo.Launcher -eq 'py') {
        & py "-$($pythonInfo.Version)" -m venv $VenvDir
    } else {
        & python -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'Failed to create venv. See output above.'
        exit 1
    }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'

Write-Host ''
Write-Host 'Upgrading pip...'
& $VenvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error 'pip upgrade failed.'
    exit 1
}

Write-Host ''
Write-Host 'Installing Python dependencies from requirements.txt...'
& $VenvPip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error 'pip install failed. See output above.'
    exit 1
}

# Sentinel write
Get-RequirementsHash | Set-Content -Path $Sentinel -NoNewline

Write-Host ''
Write-Host 'Done.'
Write-Host 'Activate with: .\venv\Scripts\Activate.ps1'
Write-Host 'Then run: python main.py'
