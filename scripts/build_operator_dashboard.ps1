$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "workspace\dashboard")
if (Test-Path package-lock.json) { npm ci } else { npm install }
npm run build
Write-Host "Dashboard built to workspace/api/static/app"
