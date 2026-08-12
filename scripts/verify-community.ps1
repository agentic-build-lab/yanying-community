[CmdletBinding()]
param(
    [int]$PortOffset = 0,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$ports = [ordered]@{
    api = 35105 + $PortOffset
    tts = 35205 + $PortOffset
    avatar = 35305 + $PortOffset
    render = 35405 + $PortOffset
    content = 35605 + $PortOffset
    web = 8866 + $PortOffset
}

function Wait-ForHealth([string]$Name, [string]$Url) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
            Write-Host "OK  $Name"
            return $response
        } catch {
            Start-Sleep -Milliseconds 350
        }
    } while ((Get-Date) -lt $deadline)
    throw "$Name did not become healthy: $Url"
}

Wait-ForHealth "TTS worker" "http://127.0.0.1:$($ports.tts)/health" | Out-Null
Wait-ForHealth "Avatar worker" "http://127.0.0.1:$($ports.avatar)/health" | Out-Null
Wait-ForHealth "Render worker" "http://127.0.0.1:$($ports.render)/health" | Out-Null
Wait-ForHealth "Content worker" "http://127.0.0.1:$($ports.content)/health" | Out-Null
Wait-ForHealth "API gateway" "http://127.0.0.1:$($ports.api)/health" | Out-Null

$web = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$($ports.web)/" -TimeoutSec 5
if ($web.StatusCode -ne 200 -or $web.Content -notmatch 'id="view_workbench"') {
    throw "Browser studio did not return the expected page."
}
Write-Host "OK  Browser studio"

$status = Invoke-RestMethod -Uri "http://127.0.0.1:$($ports.api)/api/system/status" -TimeoutSec 5
$requiredWorkers = @("tts_worker", "avatar_worker", "render_worker", "content_worker")
foreach ($workerId in $requiredWorkers) {
    $worker = $status.workers | Where-Object { $_.id -eq $workerId }
    if (-not $worker -or $worker.status -ne "connected") {
        throw "Worker is not connected: $workerId"
    }
}

$payload = @{
    project_id = "community_smoke_test"
    script = "YanYing community pipeline smoke test."
    voice_id = "clear_male_zh"
    avatar_source = "image_avatar"
    burn_subtitles = $true
    make_cover = $true
    dry_run = $true
} | ConvertTo-Json

$job = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($ports.api)/api/jobs" -ContentType "application/json" -Body $payload -TimeoutSec 10
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 300
    $current = Invoke-RestMethod -Uri "http://127.0.0.1:$($ports.api)/api/jobs/$($job.job_id)" -TimeoutSec 5
    if ($current.status -in @("qa_required", "approved", "exported")) {
        Write-Host "OK  Dry-run pipeline ($($current.status))"
        Write-Host "YanYing Community verification passed."
        exit 0
    }
    if ($current.status -eq "failed") {
        throw "Dry-run pipeline failed."
    }
} while ((Get-Date) -lt $deadline)

throw "Dry-run pipeline did not finish within $TimeoutSeconds seconds."
