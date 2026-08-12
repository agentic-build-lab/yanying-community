[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".runtime\community-processes.json"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No YanYing Community process record was found."
    exit 0
}

$record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($entry in $record.processes) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $entry.pid -ErrorAction Stop
        Write-Host "Stopped $($entry.name) (PID $($entry.pid))."
    }
}

Remove-Item -LiteralPath $pidFile -Force
