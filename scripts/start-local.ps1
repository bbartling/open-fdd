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

function Escape-PSLiteral([string]$value) {
  return $value.Replace("'", "''")
}

function Needs-PythonVenv([string]$roleValue) {
  return $roleValue -ne "ui"
}

if ((Needs-PythonVenv $Role) -and -not (Test-Path $venvActivate)) {
  throw "Missing venv activation script: $venvActivate"
}

function New-ServiceCommand([string]$serviceCommand, [string]$cwd, [bool]$activateVenv) {
  $escapedCwd = Escape-PSLiteral $cwd
  $escapedVenv = Escape-PSLiteral $venvActivate
  $escapedLocalDataDir = Escape-PSLiteral $localDataDir
  $escapedTtlPath = Escape-PSLiteral $ttlPath
  $escapedTtlMirrorPath = Escape-PSLiteral $ttlMirrorPath
  $escapedSyncIntervalSeconds = Escape-PSLiteral $SyncIntervalSeconds
  $escapedBridgeUrl = Escape-PSLiteral $BridgeUrl
  $activateLine = if ($activateVenv) { ". '$escapedVenv'" } else { "" }
  return @"
Set-Location '$escapedCwd'
$activateLine
`$env:OFDD_DESKTOP_DATA_DIR = '$escapedLocalDataDir'
`$env:OFDD_MODEL_TTL_PATH = '$escapedTtlPath'
`$env:OFDD_MODEL_TTL_MIRROR_PATH = '$escapedTtlMirrorPath'
`$env:OFDD_TTL_SYNC_INTERVAL_SECONDS = '$escapedSyncIntervalSeconds'
`$env:OFDD_BRIDGE_URL = '$escapedBridgeUrl'
`$env:OFDD_MCP_OFDD_API_URL = '$escapedBridgeUrl'
`$env:OFDD_UI_PUBLIC_BASE = 'http://127.0.0.1:5173'
$serviceCommand
"@
}

function Start-ServiceWindow([string]$title, [string]$serviceCommand, [string]$cwd, [bool]$activateVenv) {
  $cmd = New-ServiceCommand -serviceCommand $serviceCommand -cwd $cwd -activateVenv:$activateVenv
  Start-Process powershell -ArgumentList @("-NoExit", "-Command", $cmd) -WorkingDirectory $cwd | Out-Null
  Write-Host "Started $title"
}

if ($Role -eq "all") {
  Start-ServiceWindow -title "gateway" -serviceCommand "open-fdd-gateway" -cwd $repoRoot -activateVenv:$true
  Start-ServiceWindow -title "mcp-rag" -serviceCommand "open-fdd-mcp-rag" -cwd $repoRoot -activateVenv:$true
  Start-ServiceWindow -title "desktop-ui" -serviceCommand "npm run dev" -cwd $desktopUiDir -activateVenv:$false
  Write-Host "All services launched with repo-local data defaults."
  Write-Host ""
  Write-Host "Open-FDD UI:        http://127.0.0.1:5173"
  Write-Host "Plots (FDD-ready):  http://127.0.0.1:5173/plots?fdd=1&skipMissing=1&runSource=csv"
  Write-Host "  Add site_id=<uuid> after you ingest (see GET http://127.0.0.1:8765/assistant/readiness) for one-click overlay."
  Write-Host "Bridge health:      $BridgeUrl/health"
  Write-Host "If the browser shows ERR_CONNECTION_REFUSED, the gateway window was closed or failed to bind; re-run this script."
  $healthOk = $false
  for ($i = 0; $i -lt 30; $i++) {
    try {
      Invoke-WebRequest -Uri "$BridgeUrl/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
      $healthOk = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if ($healthOk) {
    Write-Host "Bridge responded OK at $BridgeUrl/health (UI may need a few more seconds for Vite)."
  } else {
    Write-Host "WARNING: Bridge did not respond at $BridgeUrl/health within 30s. Check the gateway PowerShell window for errors."
  }
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
$scriptBody = New-ServiceCommand -serviceCommand $singleCommand -cwd $singleCwd -activateVenv:(Needs-PythonVenv $Role)
Invoke-Expression $scriptBody
