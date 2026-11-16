param(
  [ValidateSet("check", "play", "log", "stop")][string]$Mode = "check",
  [string]$Src = "C:\ttmt-test\src-strips",
  [string]$Tag = "s1",
  [ValidateSet("neon", "flat")][string]$Style = "neon"
)
# Float strips on the Windows test rig. A GUI started over ssh has no desktop,
# so everything here runs in the logged-on user's session through ONE
# scheduled task of its own, ttmt-strips, and writes to C:\ttmt-test\strips.
#
#   strip_win32_rig.ps1 -Mode check [-Tag s1] [-Style flat]
#       runs scripts\strip_win32_check.py (about a minute; it injects pointer
#       and key input, so nobody should touch the machine), prints the result
#       and leaves nothing running.
#   strip_win32_rig.ps1 -Mode play [-Style flat]
#       opens the playground (four stand-in windows with strips) and leaves
#       it up for a person to click on.
#   strip_win32_rig.ps1 -Mode log      what the clicks did so far
#   strip_win32_rig.ps1 -Mode stop     ends the playground or a stuck check
#
# -Src is the source tree to run (default C:\ttmt-test\src-strips).
# It never touches a TTMT, a game, or any task but its own.
$root = "C:\ttmt-test"
$out = "$root\strips"
$pyw = "$root\venv\Scripts\pythonw.exe"
$task = "ttmt-strips"
New-Item -ItemType Directory -Force $out | Out-Null

function Get-Ours {
  Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in "pythonw.exe", "python.exe") -and (
      ($_.CommandLine -like "*strip_demo.py*") -or
      ($_.CommandLine -like "*strip_standin.py*") -or
      ($_.CommandLine -like "*strip_win32_check.py*"))
  }
}

function Stop-Ours {
  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
  Get-Ours | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
  $left = Get-Ours
  if ($left) { "=== STILL RUNNING:"; $left | ForEach-Object { "{0} {1}" -f $_.ProcessId, $_.CommandLine } }
  else { "=== stopped; nothing left running" }
}

function Start-InSession([string]$arguments) {
  $a = New-ScheduledTaskAction -Execute $pyw -Argument $arguments -WorkingDirectory $Src
  $p = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4)
  Register-ScheduledTask -TaskName $task -Action $a -Principal $p -Settings $s -Force | Out-Null
  Start-ScheduledTask -TaskName $task
}

if ($Mode -eq "stop") { Stop-Ours; exit 0 }

if ($Mode -eq "log") {
  if (Test-Path "$out\play.log") { Get-Content "$out\play.log" } else { "=== no playground log yet" }
  exit 0
}

if (-not (Test-Path "$Src\scripts\strip_demo.py")) { "=== no strips source in $Src"; exit 2 }
if (Get-Ours) { "=== a strips run is already up; use -Mode stop first"; Get-Ours | ForEach-Object { "{0} {1}" -f $_.ProcessId, $_.CommandLine }; exit 2 }

if ($Mode -eq "play") {
  Remove-Item "$out\play.log" -ErrorAction SilentlyContinue
  Start-InSession "`"$Src\scripts\strip_demo.py`" --play --style $Style --log `"$out\play.log`""
  foreach ($i in 1..20) { Start-Sleep 1; if ((Test-Path "$out\play.log") -and (Select-String -Quiet '\[Strips\]' "$out\play.log")) { break } }
  "=== playground started; -Mode log shows the actions, -Mode stop ends it"
  if (Test-Path "$out\play.log") { Get-Content "$out\play.log" | Select-Object -First 10 }
  exit 0
}

# check
# A running TTMT would have its own strips and input hooks on the same desktop.
$busy = Get-CimInstance Win32_Process | Where-Object { ($_.Name -in "pythonw.exe", "python.exe") -and ($_.CommandLine -like "*main.py*") }
if ($busy) { "=== a TTMT instance is running; not starting the check beside it"; $busy | ForEach-Object { "{0} {1}" -f $_.ProcessId, $_.CommandLine }; exit 2 }
Remove-Item "$out\$Tag*" -Recurse -ErrorAction SilentlyContinue
Start-InSession "`"$Src\scripts\strip_win32_check.py`" --style $Style --out `"$out\$Tag.out`" --shots `"$out\$Tag-shots`""
$done = $false
foreach ($i in 1..150) {
  Start-Sleep 1
  if ((Test-Path "$out\$Tag.out") -and (Select-String -Quiet '^DONE ' "$out\$Tag.out")) { $done = $true; break }
}
"=== check finished=$done"
if (Test-Path "$out\$Tag.out") { Get-Content "$out\$Tag.out" }
"=== screenshots"; if (Test-Path "$out\$Tag-shots") { Get-ChildItem "$out\$Tag-shots" -Name }
Stop-Ours
