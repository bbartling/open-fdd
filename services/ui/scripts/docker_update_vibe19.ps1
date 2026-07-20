# Easy button: pull newest vibe19 image and recreate the long-running container.
# Usage:
#   .\scripts\docker_update_vibe19.ps1
#   .\scripts\docker_update_vibe19.ps1 -Tag develop
#   .\scripts\docker_update_vibe19.ps1 -Tag latest -HostPort 8501
param(
    [string]$Tag = "latest",
    [string]$Name = "vibe19",
    [int]$HostPort = 8502
)

$ErrorActionPreference = "Stop"
$Image = "ghcr.io/bbartling/vibe19:$Tag"

Write-Host "==> Pulling $Image"
docker pull $Image
if ($LASTEXITCODE -ne 0) { throw "docker pull failed" }

Write-Host "==> Recreating container '$Name' on host port $HostPort"
docker stop $Name 2>$null | Out-Null
docker rm $Name 2>$null | Out-Null
docker run -d --restart unless-stopped `
    -p "${HostPort}:8501" `
    --name $Name `
    $Image
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

Write-Host "==> Running:"
docker ps --filter "name=$Name"
Write-Host "Open http://localhost:${HostPort}  (or http://<host-ip>:${HostPort})"
Write-Host "Note: a running container never auto-updates — re-run this script after GHCR builds."
