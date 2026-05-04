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

function Get-OfddMcpRestBase {
  if ($env:OFDD_MCP_REST_BASE -and $env:OFDD_MCP_REST_BASE.Trim()) {
    return $env:OFDD_MCP_REST_BASE.TrimEnd("/")
  }
  return "http://127.0.0.1:8090"
}
function Get-OfddUiPublicBase {
  if ($env:OFDD_UI_PUBLIC_BASE -and $env:OFDD_UI_PUBLIC_BASE.Trim()) {
    return $env:OFDD_UI_PUBLIC_BASE.TrimEnd("/")
  }
  return "http://127.0.0.1:5173"
}
function Get-OfddAllowLocalCodexInstallCli {
  if ($env:OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI -and $env:OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI.Trim()) {
    return $env:OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI.Trim()
  }
  return "1"
}

New-Item -ItemType Directory -Path $localDataDir -Force | Out-Null

function Escape-PSLiteral([string]$value) {
  return $value.Replace("'", "''")
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $Content, $utf8)
}

function Needs-PythonVenv([string]$roleValue) {
  return $roleValue -ne "ui"
}

if ((Needs-PythonVenv $Role) -and -not (Test-Path $venvActivate)) {
  throw "Missing venv activation script: $venvActivate"
}

function New-ServiceCommand(
  [string]$serviceCommand,
  [string]$cwd,
  [bool]$activateVenv,
  [string]$BootstrapJsonPath,
  [string]$McpRestBase,
  [string]$UiPublicBase,
  [string]$AllowInstallCli
) {
  $escapedCwd = Escape-PSLiteral $cwd
  $escapedVenv = Escape-PSLiteral $venvActivate
  $escapedLocalDataDir = Escape-PSLiteral $localDataDir
  $escapedTtlPath = Escape-PSLiteral $ttlPath
  $escapedTtlMirrorPath = Escape-PSLiteral $ttlMirrorPath
  $escapedSyncIntervalSeconds = Escape-PSLiteral $SyncIntervalSeconds
  $escapedBridgeUrl = Escape-PSLiteral $BridgeUrl
  $escapedBootstrap = Escape-PSLiteral $BootstrapJsonPath
  $escapedMcpRest = Escape-PSLiteral $McpRestBase
  $escapedUiPublic = Escape-PSLiteral $UiPublicBase
  $escapedAllowInstall = Escape-PSLiteral $AllowInstallCli
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
`$env:OFDD_MCP_REST_BASE = '$escapedMcpRest'
`$env:OFDD_UI_PUBLIC_BASE = '$escapedUiPublic'
`$env:OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI = '$escapedAllowInstall'
`$env:OFDD_AGENT_BOOTSTRAP_FILE = '$escapedBootstrap'
$serviceCommand
"@
}

function Start-ServiceWindow(
  [string]$title,
  [string]$serviceCommand,
  [string]$cwd,
  [bool]$activateVenv,
  [string]$BootstrapJsonPath,
  [string]$McpRestBase,
  [string]$UiPublicBase,
  [string]$AllowInstallCli
) {
  $cmd = New-ServiceCommand -serviceCommand $serviceCommand -cwd $cwd -activateVenv:$activateVenv -BootstrapJsonPath $BootstrapJsonPath -McpRestBase $McpRestBase -UiPublicBase $UiPublicBase -AllowInstallCli $AllowInstallCli
  Start-Process powershell -ArgumentList @("-NoExit", "-Command", $cmd) -WorkingDirectory $cwd | Out-Null
  Write-Host "Started $title"
}

if ($Role -eq "all") {
  $bootstrapPath = Join-Path $localDataDir "openfdd-agent-bootstrap.json"
  $mcpRest = Get-OfddMcpRestBase
  $uiBase = Get-OfddUiPublicBase
  $allowInstallCli = Get-OfddAllowLocalCodexInstallCli
  $bridgeTrim = $BridgeUrl.TrimEnd("/")
  $bootstrapJson = @{
    bridge_base     = $bridgeTrim
    mcp_rest_base   = $mcpRest
    ui_public_base  = $uiBase
    started_with    = "scripts/start-local.ps1"
    role            = "all"
    desktop_data_dir = $localDataDir
    notes           = @(
      "Open-FDD built-in agent reads this file via OFDD_AGENT_BOOTSTRAP_FILE (set on child processes).",
      "GET $($bridgeTrim)/openfdd-agent/context for live merged JSON from the bridge.",
      "MCP: GET $($mcpRest)/manifest - REST tools under POST $($mcpRest)/tools/..."
    )
  } | ConvertTo-Json -Depth 6
  Write-Utf8NoBom -Path $bootstrapPath -Content $bootstrapJson
  Write-Host "Wrote agent bootstrap: $bootstrapPath"

  Start-ServiceWindow -title "gateway" -serviceCommand "open-fdd-gateway" -cwd $repoRoot -activateVenv:$true -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli
  Start-ServiceWindow -title "mcp-rag" -serviceCommand "open-fdd-mcp-rag" -cwd $repoRoot -activateVenv:$true -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli
  Start-ServiceWindow -title "desktop-ui" -serviceCommand "npm run dev" -cwd $desktopUiDir -activateVenv:$false -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli
  Write-Host "All services launched with repo-local data defaults."
  Write-Host "Tip: Re-running this script without closing the previous gateway / mcp-rag / desktop-ui windows can leave ports 8765, 8090, or 5173 busy. Close old windows (or stop old PIDs) to refresh MCP and pick up a rebuilt rag_index.json — see docs/howto/desktop_app.md (Restarting start-local and MCP)."
  Write-Host ""
  Write-Host "Open-FDD UI:        http://127.0.0.1:5173"
  Write-Host "Open-FDD agent API: $BridgeUrl/openfdd-agent/context  (POST .../openfdd-agent/chat)"
  Write-Host "MCP RAG REST:       $mcpRest/manifest"
  Write-Host 'Plots (FDD-ready):  http://127.0.0.1:5173/plots?fdd=1&skipMissing=1&runSource=csv'
  Write-Host "  Add site_id=<uuid> after you ingest (see GET $bridgeTrim/assistant/readiness) for one-click overlay."
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
$singleBootstrap = Join-Path $localDataDir "openfdd-agent-bootstrap.json"
$singleMcpRest = Get-OfddMcpRestBase
$singleUiBase = Get-OfddUiPublicBase
$singleAllowInstallCli = Get-OfddAllowLocalCodexInstallCli
$singleBootstrapJson = @{
  bridge_base    = $BridgeUrl.TrimEnd("/")
  mcp_rest_base  = $singleMcpRest
  ui_public_base = $singleUiBase
  started_with   = "scripts/start-local.ps1"
  role           = $Role
} | ConvertTo-Json -Depth 5
Write-Utf8NoBom -Path $singleBootstrap -Content $singleBootstrapJson
$scriptBody = New-ServiceCommand -serviceCommand $singleCommand -cwd $singleCwd -activateVenv:(Needs-PythonVenv $Role) -BootstrapJsonPath $singleBootstrap -McpRestBase $singleMcpRest -UiPublicBase $singleUiBase -AllowInstallCli $singleAllowInstallCli
Invoke-Expression $scriptBody
