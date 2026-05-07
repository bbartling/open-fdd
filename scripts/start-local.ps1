param(
  [ValidateSet("all", "gateway", "mcp", "ui", "adapter")]
  [string]$Role = "all",
  [string]$BridgeUrl = "http://127.0.0.1:8765",
  [string]$SyncIntervalSeconds = "5",
  [ValidateSet("auto", "always", "skip")]
  [string]$RagIndex = "auto",
  # Private LAN dashboard: bind gateway + MCP on 0.0.0.0, Vite --host 0.0.0.0, CORS for RFC1918, and set
  # bridge / MCP / UI public URLs to this host (e.g. 192.168.1.10). Open firewall for 8765, 8090, 5173.
  [string]$LanHost = "",
  # Bind gateway + MCP on 0.0.0.0 without setting public URLs (use OFDD_BRIDGE_URL or AI Agent Bridge base URL).
  [switch]$ListenAll
)

$ErrorActionPreference = "Stop"
Write-Host "[checkpoint] start-local.ps1 starting (role=$Role)"

$LanDashboard = $false
if ((-not $LanHost -or $LanHost.Trim().Length -eq 0) -and $env:OFDD_LAN_HOST -and $env:OFDD_LAN_HOST.Trim().Length -gt 0) {
  $LanHost = $env:OFDD_LAN_HOST.Trim()
}
if ($LanHost -and $LanHost.Trim().Length -gt 0) {
  $LanDashboard = $true
  $h = $LanHost.Trim()
  $BridgeUrl = "http://${h}:8765"
  $env:OFDD_UI_PUBLIC_BASE = "http://${h}:5173"
  $env:OFDD_MCP_REST_BASE = "http://${h}:8090"
  $env:OFDD_BRIDGE_HOST = "0.0.0.0"
  $env:OFDD_MCP_LISTEN_HOST = "0.0.0.0"
  $env:OFDD_CORS_ALLOW_PRIVATE_LAN = "1"
  Write-Host "LAN dashboard: URLs use ${h}; gateway+MCP listen on 0.0.0.0; Vite --host 0.0.0.0. Allow inbound TCP 8765, 8090, 5173 on this machine if other PCs connect."
}
elseif ($ListenAll) {
  $env:OFDD_BRIDGE_HOST = "0.0.0.0"
  $env:OFDD_MCP_LISTEN_HOST = "0.0.0.0"
  if (-not $env:OFDD_CORS_ALLOW_PRIVATE_LAN -or $env:OFDD_CORS_ALLOW_PRIVATE_LAN.Trim().Length -eq 0) {
    $env:OFDD_CORS_ALLOW_PRIVATE_LAN = "1"
  }
  if ($env:OFDD_BRIDGE_URL -and $env:OFDD_BRIDGE_URL.Trim().Length -gt 0) {
    $BridgeUrl = $env:OFDD_BRIDGE_URL.TrimEnd("/")
  }
  Write-Host "Listen-all: gateway+MCP bind 0.0.0.0; Vite --host 0.0.0.0. Set OFDD_BRIDGE_URL / OFDD_UI_PUBLIC_BASE for public URLs, or use Bridge base URL in the AI Agent tab."
}

$BindAllInterfaces = [bool]($LanDashboard -or $ListenAll)

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
  # Default 0 matches start-local.sh (opt in with OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI=1 for POST /local-codex/install-cli).
  return "0"
}
function Get-OfddOpenClawGatewayUrl {
  if ($env:OFDD_OPENCLAW_GATEWAY_URL -and $env:OFDD_OPENCLAW_GATEWAY_URL.Trim()) {
    return $env:OFDD_OPENCLAW_GATEWAY_URL.TrimEnd("/")
  }
  if ($env:OFDD_CLAW_GATEWAY_URL -and $env:OFDD_CLAW_GATEWAY_URL.Trim()) {
    return $env:OFDD_CLAW_GATEWAY_URL.TrimEnd("/")
  }
  return "http://127.0.0.1:18789"
}

function Invoke-McpRagIndexBuild {
  $outPath = Join-Path $repoRoot "stack\mcp-rag\index\rag_index.json"
  $modeRaw = ($RagIndex | ForEach-Object { "$_".Trim().ToLower() })
  $mode = if ($modeRaw) { $modeRaw } else { "auto" }
  if ($env:OFDD_SKIP_MCP_INDEX_BUILD -eq "1") {
    $mode = "skip"
  }
  if ($env:OFDD_MCP_RAG_INDEX_MODE) {
    $envMode = $env:OFDD_MCP_RAG_INDEX_MODE.Trim().ToLower()
    if ($envMode -in @("auto", "always", "skip")) {
      $mode = $envMode
    }
  }
  if ($mode -eq "skip") {
    Write-Host "Skipping MCP RAG index rebuild (mode=skip; set -RagIndex always to force)."
    return
  }
  if ($mode -eq "auto" -and (Test-Path $outPath)) {
    Write-Host "MCP RAG index exists; skipping rebuild (mode=auto): $outPath"
    return
  }
  Write-Host "Building MCP RAG index (mode=$mode)... this may take a few minutes."
  Write-Host "Tip: use -RagIndex skip for faster startup, or -RagIndex always to force rebuild."
  $pyExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path $pyExe)) {
    $pyExe = "python"
  }
  $scriptPath = Join-Path $repoRoot "scripts\build_mcp_rag_index.py"
  $startedAt = Get-Date
  Push-Location $repoRoot
  try {
    $proc = Start-Process -FilePath $pyExe -ArgumentList @($scriptPath, "--output", $outPath) -NoNewWindow -PassThru
    $nextHeartbeatSeconds = 10
    while (-not $proc.HasExited) {
      Start-Sleep -Seconds 2
      $elapsed = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
      if ($elapsed -ge $nextHeartbeatSeconds) {
        Write-Host "Still building MCP RAG index... (${elapsed}s elapsed)"
        $nextHeartbeatSeconds += 10
      }
    }
    # ExitCode is not guaranteed until WaitForExit(); without this, $null/-1 can falsely trigger failure.
    $null = $proc.WaitForExit()
    $exitCode = $proc.ExitCode
    if ($null -ne $exitCode -and $exitCode -ne 0) {
      Write-Warning "MCP RAG index build failed; search_docs may be stale until you fix errors and restart MCP."
    } else {
      $elapsed = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
      Write-Host "MCP RAG index build complete (${elapsed}s): $outPath"
    }
  } finally {
    Pop-Location
  }
}

New-Item -ItemType Directory -Path $localDataDir -Force | Out-Null
Write-Host "[checkpoint] local data dir ready: $localDataDir"

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
  [string]$AllowInstallCli,
  [bool]$BindAllInterfaces = $false
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
  $lanBlock = ""
  if ($BindAllInterfaces) {
    $lanBlock = @"
`$env:OFDD_BRIDGE_HOST = '0.0.0.0'
`$env:OFDD_MCP_LISTEN_HOST = '0.0.0.0'
if (-not `$env:OFDD_CORS_ALLOW_PRIVATE_LAN -or `$env:OFDD_CORS_ALLOW_PRIVATE_LAN.Trim().Length -eq 0) {
  `$env:OFDD_CORS_ALLOW_PRIVATE_LAN = '1'
}
"@
  }
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
$lanBlock
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
  [string]$AllowInstallCli,
  [bool]$BindAllInterfaces = $false
) {
  $cmd = New-ServiceCommand -serviceCommand $serviceCommand -cwd $cwd -activateVenv:$activateVenv -BootstrapJsonPath $BootstrapJsonPath -McpRestBase $McpRestBase -UiPublicBase $UiPublicBase -AllowInstallCli $AllowInstallCli -BindAllInterfaces:$BindAllInterfaces
  Start-Process powershell -ArgumentList @("-NoExit", "-Command", $cmd) -WorkingDirectory $cwd | Out-Null
  Write-Host "Started $title"
}

function Stop-ListeningProcessOnPort(
  [int]$Port,
  [string]$Name
) {
  try {
    $rows = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $rows) { return }
    $pids = @($rows | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($procId in $pids) {
      if (-not $procId) { continue }
      try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped existing $Name process on port $Port (pid=$procId)."
      } catch {
        Write-Warning "Could not stop existing $Name process pid=$procId on port $Port."
      }
    }
  } catch {
    Write-Warning "Port check failed for $Name on $Port; continuing."
  }
}

function Restart-ExistingServiceIfRunning([string]$serviceName) {
  switch ($serviceName) {
    "gateway" { Stop-ListeningProcessOnPort -Port 8765 -Name "gateway" }
    "mcp-rag" { Stop-ListeningProcessOnPort -Port 8090 -Name "mcp-rag" }
    "desktop-ui" { Stop-ListeningProcessOnPort -Port 5173 -Name "desktop-ui" }
    "adapter" {
      try {
        $adapterProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object {
          ($_.CommandLine -as [string]) -match "open-fdd-mcp-adapter"
        })
        foreach ($m in $adapterProcs) {
          Stop-Process -Id $m.ProcessId -Force -ErrorAction SilentlyContinue
          Write-Host "Stopped existing adapter process (pid=$($m.ProcessId))."
        }
      } catch {
        Write-Warning "Adapter process check failed; continuing."
      }
    }
  }
}

if ($Role -eq "all") {
  Write-Host "[checkpoint] role=all preparing bootstrap and environment"
  $bootstrapPath = Join-Path $localDataDir "openfdd-agent-bootstrap.json"
  $mcpRest = Get-OfddMcpRestBase
  $uiBase = Get-OfddUiPublicBase
  $allowInstallCli = Get-OfddAllowLocalCodexInstallCli
  $openclawUrl = Get-OfddOpenClawGatewayUrl
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
  Write-Host "[checkpoint] bootstrap written"

  Invoke-McpRagIndexBuild
  Write-Host "[checkpoint] MCP RAG index step finished"

  $uiDevCmd = if ($BindAllInterfaces) { "npm run dev -- --host 0.0.0.0" } else { "npm run dev" }
  Write-Host "[checkpoint] launching service windows (gateway, mcp-rag, desktop-ui)"
  Restart-ExistingServiceIfRunning "gateway"
  Restart-ExistingServiceIfRunning "mcp-rag"
  Restart-ExistingServiceIfRunning "desktop-ui"
  Start-ServiceWindow -title "gateway" -serviceCommand "open-fdd-gateway" -cwd $repoRoot -activateVenv:$true -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli -BindAllInterfaces:$BindAllInterfaces
  Start-ServiceWindow -title "mcp-rag" -serviceCommand "open-fdd-mcp-rag" -cwd $repoRoot -activateVenv:$true -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli -BindAllInterfaces:$BindAllInterfaces
  Start-ServiceWindow -title "desktop-ui" -serviceCommand $uiDevCmd -cwd $desktopUiDir -activateVenv:$false -BootstrapJsonPath $bootstrapPath -McpRestBase $mcpRest -UiPublicBase $uiBase -AllowInstallCli $allowInstallCli -BindAllInterfaces:$BindAllInterfaces
  Write-Host 'All services launched with repo-local data defaults.'
  Write-Host 'Tip: MCP RAG index behavior is controlled by -RagIndex (auto|always|skip). Re-running without stopping old gateway/mcp/ui windows can leave ports 8765, 8090, or 5173 busy — close old jobs first — see docs/howto/desktop_app.md (Restarting start-local and MCP).'
  Write-Host ""
  Write-Host ('Open-FDD UI:        {0}' -f $uiBase)
  Write-Host ('Open-FDD agent API: {0}/openfdd-agent/context  (POST .../openfdd-agent/chat)' -f $bridgeTrim)
  Write-Host ('MCP RAG REST:       {0}/manifest' -f $mcpRest)
  Write-Host ('Plots (FDD-ready):  {0}/plots?fdd=1&skipMissing=1&runSource=csv' -f $uiBase)
  Write-Host ('  Add site_id=<uuid> after you ingest (see GET {0}/assistant/readiness) for one-click overlay.' -f $bridgeTrim)
  Write-Host ('Bridge health:      {0}/health' -f $bridgeTrim)
  Write-Host ('OpenClaw gateway:   {0}/health' -f $openclawUrl)
  Write-Host ('OpenClaw token set: {0}' -f ([bool]($env:OFDD_OPENCLAW_GATEWAY_TOKEN -or $env:OFDD_CLAW_GATEWAY_TOKEN)))
  Write-Host 'If the browser shows ERR_CONNECTION_REFUSED, the gateway window was closed or failed to bind; re-run this script.'
  Write-Host "[checkpoint] running startup health checks"
  $healthOk = $false
  for ($i = 0; $i -lt 30; $i++) {
    try {
      Invoke-WebRequest -Uri ('{0}/health' -f $bridgeTrim) -UseBasicParsing -TimeoutSec 2 | Out-Null
      $healthOk = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if ($healthOk) {
    Write-Host ('Bridge responded OK at {0}/health (UI may need a few more seconds for Vite).' -f $bridgeTrim)
  } else {
    Write-Host ('WARNING: Bridge did not respond at {0}/health within 30s. Check the gateway PowerShell window for errors.' -f $bridgeTrim)
  }
  try {
    Invoke-WebRequest -Uri ('{0}/health' -f $mcpRest) -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Host ('MCP responded OK at {0}/health.' -f $mcpRest)
  } catch {
    Write-Warning ('MCP did not respond at {0}/health. Check mcp-rag PowerShell window.' -f $mcpRest)
  }
  try {
    Invoke-WebRequest -Uri $uiBase -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Host ('UI responded OK at {0}.' -f $uiBase)
  } catch {
    Write-Warning ('UI did not respond at {0}. Check desktop-ui PowerShell window for Vite errors/port conflicts.' -f $uiBase)
  }
  try {
    Invoke-WebRequest -Uri ('{0}/health' -f $openclawUrl) -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Host ('OpenClaw gateway responded OK at {0}/health.' -f $openclawUrl)
  } catch {
    Write-Warning ('OpenClaw gateway not reachable at {0}/health (optional unless using /assistant/data-model-openclaw).' -f $openclawUrl)
  }
  Write-Host "[checkpoint] role=all startup sequence complete"
  exit 0
}

$singleCommand = switch ($Role) {
  "gateway" { "open-fdd-gateway" }
  "mcp" { "open-fdd-mcp-rag" }
  "ui" { if ($BindAllInterfaces) { "npm run dev -- --host 0.0.0.0" } else { "npm run dev" } }
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
Write-Host "[checkpoint] role=$Role bootstrap written: $singleBootstrap"
if ($Role -eq "mcp") {
  Invoke-McpRagIndexBuild
  Write-Host "[checkpoint] role=mcp RAG index step finished"
}
if ($Role -eq "gateway") { Restart-ExistingServiceIfRunning "gateway" }
if ($Role -eq "mcp") { Restart-ExistingServiceIfRunning "mcp-rag" }
if ($Role -eq "ui") { Restart-ExistingServiceIfRunning "desktop-ui" }
if ($Role -eq "adapter") { Restart-ExistingServiceIfRunning "adapter" }
$scriptBody = New-ServiceCommand -serviceCommand $singleCommand -cwd $singleCwd -activateVenv:(Needs-PythonVenv $Role) -BootstrapJsonPath $singleBootstrap -McpRestBase $singleMcpRest -UiPublicBase $singleUiBase -AllowInstallCli $singleAllowInstallCli -BindAllInterfaces:$BindAllInterfaces
Write-Host "[checkpoint] launching role=$Role command"
Invoke-Expression $scriptBody
