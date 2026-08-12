[CmdletBinding()]
param(
    [int]$PortOffset = 0,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $repoRoot ".runtime"
$logRoot = Join-Path $runtimeRoot "logs"
$pidFile = Join-Path $runtimeRoot "community-processes.json"

if (-not $Python) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

if (Test-Path -LiteralPath $pidFile) {
    throw "A process record already exists. Run scripts\stop-community.ps1 first."
}

New-Item -ItemType Directory -Force -Path $logRoot, (Join-Path $runtimeRoot "outputs"), (Join-Path $runtimeRoot "private") | Out-Null

$ports = [ordered]@{
    api = 35105 + $PortOffset
    tts = 35205 + $PortOffset
    avatar = 35305 + $PortOffset
    render = 35405 + $PortOffset
    content = 35605 + $PortOffset
    web = 8866 + $PortOffset
}

$env:METAHUMAN_BIND_HOST = "127.0.0.1"
$env:METAHUMAN_TTS_BIND_HOST = "127.0.0.1"
$env:METAHUMAN_AVATAR_BIND_HOST = "127.0.0.1"
$env:METAHUMAN_RENDER_BIND_HOST = "127.0.0.1"
$env:METAHUMAN_TTS_WORKER_URL = "http://127.0.0.1:$($ports.tts)"
$env:METAHUMAN_AVATAR_WORKER_URL = "http://127.0.0.1:$($ports.avatar)"
$env:METAHUMAN_RENDER_WORKER_URL = "http://127.0.0.1:$($ports.render)"
$env:METAHUMAN_CONTENT_WORKER_URL = "http://127.0.0.1:$($ports.content)"
$env:METAHUMAN_ENABLE_LEGACY_ADAPTER = "0"
$env:METAHUMAN_OUTPUT_ROOT = Join-Path $runtimeRoot "outputs"
$env:METAHUMAN_CONTENT_RUNTIME_DIR = Join-Path $runtimeRoot "private"
$env:METAHUMAN_CONTENT_LOG_DIR = Join-Path $logRoot "content"
$env:METAHUMAN_CONTENT_BROWSER_PROFILE = Join-Path $runtimeRoot "browser-profile"

function Start-CommunityProcess {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string[]]$Arguments
    )

    $stdout = Join-Path $logRoot "$Name.stdout.log"
    $stderr = Join-Path $logRoot "$Name.stderr.log"
    $process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    return [ordered]@{ name = $Name; pid = $process.Id; stdout = $stdout; stderr = $stderr }
}

$processes = @()
try {
    $processes += Start-CommunityProcess "tts" (Join-Path $repoRoot "services\tts_worker") @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$($ports.tts)")
    $processes += Start-CommunityProcess "avatar" (Join-Path $repoRoot "services\avatar_worker") @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$($ports.avatar)")
    $processes += Start-CommunityProcess "render" (Join-Path $repoRoot "services\render_worker") @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$($ports.render)")
    $processes += Start-CommunityProcess "content" $repoRoot @((Join-Path $repoRoot "services\content_worker\app\main.py"), "--host", "127.0.0.1", "--port", "$($ports.content)")
    $processes += Start-CommunityProcess "api" (Join-Path $repoRoot "services\api_gateway") @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$($ports.api)")
    $processes += Start-CommunityProcess "web" $repoRoot @("-m", "http.server", "$($ports.web)", "--bind", "127.0.0.1", "--directory", (Join-Path $repoRoot "apps\studio_web"))

    [ordered]@{ started_at = (Get-Date).ToString("o"); port_offset = $PortOffset; ports = $ports; processes = $processes } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pidFile -Encoding UTF8
} catch {
    foreach ($entry in $processes) {
        Stop-Process -Id $entry.pid -ErrorAction SilentlyContinue
    }
    throw
}

Write-Host "YanYing Community started."
Write-Host "Studio: http://127.0.0.1:$($ports.web)/?api=http://127.0.0.1:$($ports.api)"
Write-Host "Verify: .\scripts\verify-community.ps1 -PortOffset $PortOffset"
