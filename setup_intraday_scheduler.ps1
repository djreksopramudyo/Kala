# setup_intraday_scheduler.ps1 - register the intraday guard in Task Scheduler.
#
# Creates ONE task, "Kala Intraday Watch": every 15 minutes, Mon-Fri,
# 09:00-16:00 WIB. intraday_watch.py itself checks the exact IDX sessions
# (lunch break, Friday prayers gap) and exits instantly when closed, so the
# task being slightly wider than market hours costs nothing.
#
# Why 15 minutes and not 5: Yahoo's IDX quotes are delayed ~10-20 minutes,
# so polling faster than the data refreshes is pure noise.
#
# Run once from the project folder:
#     powershell -ExecutionPolicy Bypass -File .\setup_intraday_scheduler.ps1
# Remove later with:
#     Unregister-ScheduledTask -TaskName "Kala Intraday Watch" -Confirm:$false

$ErrorActionPreference = "Stop"

$Root   = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "intraday_watch.py"

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: $Python not found. Create the venv first." -ForegroundColor Red
    exit 1
}

$Action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:00
$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 09:00 `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 7)).Repetition
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Kala Intraday Watch" `
    -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Kala: intraday stop/limit-down/watchlist-dip alerts for held positions. Event-driven, deduped, read-only." `
    -Force | Out-Null

Write-Host ""
Write-Host "Registered: 'Kala Intraday Watch' - Mon-Fri, every 15 min 09:00-16:00." -ForegroundColor Green
Write-Host "Test it now (ignores market hours):"
Write-Host "  .\.venv\Scripts\python.exe intraday_watch.py --force"
