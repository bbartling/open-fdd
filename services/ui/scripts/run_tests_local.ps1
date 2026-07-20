# Windows-safe pytest runner — redirects TMP/TEMP/cache away from locked AppData temp.
# Usage (from vibe_code_apps_19):
#   .\scripts\run_tests_local.ps1
#   .\scripts\run_tests_local.ps1 -PytestArgs @("-k", "weather")

param(
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tmp = Join-Path $Root ".pytest_tmp"
$Cache = Join-Path $Root ".pytest_cache_local"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

$env:TMP = $Tmp
$env:TEMP = $Tmp
Set-Location $Root

Write-Host "TMP/TEMP -> $Tmp"
Write-Host "cache_dir -> $Cache"
& python -m pytest -q -o "cache_dir=$Cache" @PytestArgs
exit $LASTEXITCODE
