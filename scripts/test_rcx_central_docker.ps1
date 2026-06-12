# Smoke test OpenFDD RCx Central Docker stack (Windows Docker Desktop)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Compose = "docker compose -f `"$Root/docker/rcx-central/docker-compose.yml`""

if (-not $env:OPENFDD_IMAGE_TAG) { $env:OPENFDD_IMAGE_TAG = "local" }

Invoke-Expression "$Compose build"
Invoke-Expression "$Compose up -d"

try {
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8060/health" -UseBasicParsing -TimeoutSec 5
            if ($r.Content -match "ok") { $ok = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ok) { throw "API health did not respond" }

    Invoke-WebRequest -Uri "http://127.0.0.1:8050/" -UseBasicParsing -TimeoutSec 10 | Out-Null
    Invoke-Expression "$Compose exec -T rcx-central-api python -c `"from pathlib import Path; p=Path('/app/portfolio/data/reports'); p.mkdir(exist_ok=True); (p/'_write_test').write_text('ok'); assert (p/'_write_test').read_text()=='ok'`""
    Write-Host "RCx Central Docker smoke: PASS"
}
finally {
    Invoke-Expression "$Compose down"
}
