# Build operator dashboard → workspace/api/static/app (same artifact as build_operator_dashboard.sh).
#
#   .\scripts\build_operator_dashboard.ps1
#   .\scripts\build_operator_dashboard.ps1 -Mode test
#   .\scripts\build_operator_dashboard.ps1 -DeployHost 192.168.204.18 -DeployUser ben
#
# When -DeployHost is set, rsync/scp the static bundle to the edge after build (LAN remote deploy).
# Caddy-served edges: browse http://<edge-ip>/ — no VITE_DESKTOP_BRIDGE_BASE needed (same-origin /api).
param(
    [ValidateSet("prod", "test")]
    [string]$Mode = "prod",
    [string]$DeployHost = "",
    [string]$DeployUser = "ben",
    [string]$RemoteDir = "~/open-fdd",
    [int]$SshPort = 22
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dashboard = Join-Path $Root "workspace\dashboard"
$OutDir = Join-Path $Root "workspace\api\static\app"

Set-Location $Dashboard
if (Test-Path package-lock.json) {
    npm ci
} else {
    npm install
}

switch ($Mode) {
    "test" {
        Write-Host "==> Dashboard vitest"
        npm test
        Write-Host "==> Dashboard production build"
        npm run build
    }
    default {
        npm run build
    }
}

$Index = Join-Path $OutDir "index.html"
if (-not (Test-Path $Index)) {
    throw "Build failed — missing $Index"
}

$asset = ""
if ((Get-Content $Index -Raw) -match 'index-[^"]+\.js') {
    $asset = $Matches[0]
}
Write-Host "Dashboard built to workspace/api/static/app ($asset)"

if (-not $DeployHost) {
    Write-Host ""
    Write-Host "Local only. To push to edge from LAN:"
    Write-Host "  .\scripts\build_operator_dashboard.ps1 -DeployHost <edge-ip> -DeployUser ben"
    Write-Host "Then open: http://<edge-ip>/  (Caddy) or http://<edge-ip>:8765/ (no Caddy)"
    exit 0
}

$RemotePath = "$DeployUser@${DeployHost}:$($RemoteDir.TrimEnd('/'))/workspace/api/static/app/"
Write-Host ""
Write-Host "==> Deploy static bundle → $RemotePath"

$sshArgs = @("-p", $SshPort)
$remoteMkdir = "mkdir -p $($RemoteDir.TrimEnd('/'))/workspace/api/static/app"

ssh @sshArgs "${DeployUser}@${DeployHost}" $remoteMkdir
if ($LASTEXITCODE -ne 0) { throw "ssh mkdir failed (exit $LASTEXITCODE)" }

$rsync = Get-Command rsync -ErrorAction SilentlyContinue
if ($rsync) {
    $sshCmd = "ssh -p $SshPort"
    & rsync -az --delete -e $sshCmd "${OutDir}/" $RemotePath
    if ($LASTEXITCODE -ne 0) { throw "rsync failed (exit $LASTEXITCODE)" }
} else {
    Write-Host "rsync not found — using scp (slower; install rsync or Git for Windows for --delete sync)"
    scp @sshArgs -r "${OutDir}\*" "${DeployUser}@${DeployHost}:$($RemoteDir.TrimEnd('/'))/workspace/api/static/app/"
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)" }
}

Write-Host "OK — edge UI bundle $asset synced to $DeployHost"
Write-Host "Open: http://${DeployHost}/  (Caddy :80) — login with integrator creds from workspace/auth.env.local on edge"
