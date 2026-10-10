param(
    [switch]$NoBuild,
    [int]$HealthTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $composeArgs = @("compose", "up", "-d")
    if (-not $NoBuild) { $composeArgs += "--build" }
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }

    Write-Host "Waiting for init service to seed tickers and initialize portfolios..."

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health/" -TimeoutSec 3
            if ($health.status -eq "ok" -and $health.mongodb -eq "connected") {
                Write-Host "Backend and MongoDB are healthy."
                Write-Host "Backend: http://localhost:8000"
                Write-Host "Health:  http://localhost:8000/api/health/"
                Write-Host "Mongo:   mongodb://localhost:27018/financial_nlp"
                & docker compose ps
                exit 0
            }
        }
        catch {
            Start-Sleep -Seconds 3
        }
    } while ((Get-Date) -lt $deadline)

    & docker compose ps
    throw "Backend health check did not pass within $HealthTimeoutSeconds seconds. Check logs with: docker compose logs backend mongo"
}
finally {
    Pop-Location
}
