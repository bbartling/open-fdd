param(
  [ValidateSet("all", "gateway", "mcp", "ui", "adapter")]
  [string]$Role = "all",
  [string]$BridgeUrl = "http://127.0.0.1:8765",
  [string]$SyncIntervalSeconds = "5"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopUiDir = Join-Path $repoRoot "apps\desktop-ui"
$venvActivate = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
$localDataDir = Join-Path $repoRoot "stack\local-data"
$ttlPath = Join-Path $localDataDir "data_model.ttl"
$ttlMirrorPath = Join-Path $localDataDir "data_model.mirror.ttl"

New-Item -ItemType Directory -Path $localDataDir -Force | Out-Null

if (-not (Test-Path $venvActivate)) {
  throw "Missing venv activation script: $venvActivate"
}

function New-ServiceCommand([string]$serviceCommand, [string]$cwd) {
  return @"
Set-Location '$cwd'
. '$venvActivate'
`$env:OFDD_DESKTOP_DATA_DIR = '$localDataDir'
`$env:OFDD_MODEL_TTL_PATH = '$ttlPath'
`$env:OFDD_MODEL_TTL_MIRROR_PATH = '$ttlMirrorPath'
`$env:OFDD_TTL_SYNC_INTERVAL_SECONDS = '$SyncIntervalSeconds'
`$env:OFDD_BRIDGE_URL = '$BridgeUrl'
$serviceCommand
"@
}

function Start-ServiceWindow([string]$title, [string]$serviceCommand, [string]$cwd) {
  $cmd = New-ServiceCommand -serviceCommand $serviceCommand -cwd $cwd
  Start-Process powershell -ArgumentList @("-NoExit", "-Command", $cmd) -WorkingDirectory $cwd | Out-Null
  Write-Host "Started $title"
}

if ($Role -eq "all") {
  Start-ServiceWindow -title "gateway" -serviceCommand "open-fdd-gateway" -cwd $repoRoot
  Start-ServiceWindow -title "mcp-rag" -serviceCommand "open-fdd-mcp-rag" -cwd $repoRoot
  Start-ServiceWindow -title "desktop-ui" -serviceCommand "npm run dev" -cwd $desktopUiDir
  Write-Host "All services launched with repo-local data defaults."
  exit 0
}

$singleCommand = switch ($Role) {
  "gateway" { "open-fdd-gateway" }
  "mcp" { "open-fdd-mcp-rag" }
  "ui" { "npm run dev" }
  "adapter" { "open-fdd-mcp-adapter" }
  default { throw "Unknown role: $Role" }
}

$singleCwd = if ($Role -eq "ui") { $desktopUiDir } else { $repoRoot }
$scriptBody = New-ServiceCommand -serviceCommand $singleCommand -cwd $singleCwd
Invoke-Expression $scriptBody
