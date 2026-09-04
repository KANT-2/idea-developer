param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "IdeaDeveloperMidnightMaintenance"
)

$resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$pythonPath = Join-Path $resolvedProject ".venv\Scripts\python.exe"
$managePath = Join-Path $resolvedProject "manage.py"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "가상환경 Python을 찾을 수 없습니다: $pythonPath"
}
if (-not (Test-Path -LiteralPath $managePath -PathType Leaf)) {
    throw "manage.py를 찾을 수 없습니다: $managePath"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument 'manage.py run_midnight_maintenance --settings=config.settings.development' `
    -WorkingDirectory $resolvedProject
$trigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "매일 자정 PRD 자동 완료 및 만료 데이터 정리" `
    -Force | Out-Null

Write-Host "등록 완료: $TaskName (매일 00:00, 놓친 실행은 PC 시작 후 보정)"
