# setup_scheduler.ps1 - register the daily Kala run in Windows Task Scheduler.
#
# What it creates: ONE task, "Kala Daily Run", every weekday at 17:00
# (after IDX close, WIB). daily_run.py itself handles the weekly/monthly
# cadence internally, so one task is all you need.
#
# Run once from the project folder:
#     .\setup_scheduler.ps1
# (If blocked as "not digitally signed", run instead:
#      powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 )
#
# Remove later with:
#     Unregister-ScheduledTask -TaskName "Kala Daily Run" -Confirm:$false
#
# Notes:
#  * Uses THIS project's .venv python explicitly - the optkit-venv mistake
#    cannot happen here.
#  * -StartWhenAvailable: if your PC was off/asleep at 17:00, the task runs
#    as soon as it is back. If the PC is off all evening, that day is skipped
#    (Task Scheduler cannot wake a powered-off machine) - the paper trader
#    just carries its pending orders to the next session, same as a holiday.

$ErrorActionPreference = "Stop"

$Root   = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "daily_run.py"

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: $Python not found." -ForegroundColor Red
    Write-Host "Create the venv first:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Host "ERROR: daily_run.py not found next to this script." -ForegroundColor Red
    exit 1
}

$Action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday,Saturday -At 17:00
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Kala Daily Run" `
    -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Kala: EOD scan, paper trading, watchlist alerts, Telegram tickets. Saturday adds the weekly fundamental screen." `
    -Force | Out-Null

Write-Host ""
Write-Host "Registered: 'Kala Daily Run' - Mon-Sat 17:00, using:" -ForegroundColor Green
Write-Host "  $Python"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit runner_config.json (capital, Telegram token and chat id)."
Write-Host "  2. Test it now:   Start-ScheduledTask -TaskName 'Kala Daily Run'"
Write-Host "  3. Watch results\daily_run.log for output."
