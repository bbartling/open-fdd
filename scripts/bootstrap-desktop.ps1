param(
    [switch]$InstallDeps,
    [switch]$NoBridge,
    [switch]$NoMcp,
    [switch]$NoUi,
    [switch]$NoLaunch,
    [ValidateSet("static", "dev")]
    [string]$UiMode = "static",
    [int]$UiPort = 8080,
    [string]$BridgeUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[open-fdd] $Message" -ForegroundColor Cyan
}

function Invoke-Checked([scriptblock]$Command, [string]$FailureMessage) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WebUiDir = Join-Path $RepoRoot "apps\desktop-ui"
$VenvActivate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"

Write-Step "Repo root: $RepoRoot"

if (-not (Test-Path $WebUiDir)) {
    throw "Web UI directory not found: $WebUiDir"
}

if (-not (Test-Path $VenvActivate)) {
    Write-Step "Creating Python virtualenv..."
    Push-Location $RepoRoot
    try {
        Invoke-Checked { python -m venv .venv } "Failed to create .venv with 'python -m venv .venv'."
    } finally {
        Pop-Location
    }
}

if ($InstallDeps) {
    Write-Step "Stopping running bridge process (if any) before pip install..."
    $bridgeExePath = Join-Path $RepoRoot ".venv\Scripts\open-fdd-desktop-bridge.exe"
    $killed = $false
    try {
        foreach ($p in Get-Process -Name "open-fdd-desktop-bridge" -ErrorAction SilentlyContinue) {
            try {
                Stop-Process -Id $p.Id -Force
            } catch {
                Write-Warning "Failed to stop bridge process id=$($p.Id): $($_.Exception.Message)"
            }
        }
        $killed = -not (Get-Process -Name "open-fdd-desktop-bridge" -ErrorAction SilentlyContinue)
    } catch {
        Write-Warning "Error while checking bridge processes: $($_.Exception.Message)"
    }
    if (-not $killed) {
        try {
            $null = & taskkill /F /IM open-fdd-desktop-bridge.exe 2>$null
        } catch {
            Write-Warning "taskkill fallback failed: $($_.Exception.Message)"
        }
    }
    if (Test-Path $bridgeExePath) {
        Start-Sleep -Milliseconds 300
    }

    Write-Step "Installing Python deps (editable dev+desktop)..."
    Push-Location $RepoRoot
    try {
        . $VenvActivate
        Invoke-Checked { pip install -e ".[dev,desktop]" } "pip install failed. If lock persists, close bridge terminals and rerun."
    } finally {
        Pop-Location
    }

    Write-Step "Installing web UI npm deps..."
    Push-Location $WebUiDir
    try {
        # Install devDependencies even when NODE_ENV=production (Docker images often set it).
        $env:NPM_CONFIG_PRODUCTION = "false"
        if (Test-Path (Join-Path $WebUiDir "package-lock.json")) {
            Invoke-Checked { npm ci } "npm ci failed."
        } else {
            Invoke-Checked { npm install } "npm install failed."
        }
    } finally {
        Pop-Location
    }
}

if ($NoLaunch) {
    Write-Step "Bootstrap complete (NoLaunch set)."
    exit 0
}

if (-not $NoBridge) {
    Write-Step "Starting FastAPI bridge in a new terminal ($BridgeUrl)..."
    $bridgeCommand = @(
        "Set-Location '$RepoRoot'",
        "if (Test-Path '$VenvActivate') { . '$VenvActivate' }",
        "`$env:OFDD_BRIDGE_URL='$BridgeUrl'",
        "open-fdd-desktop-bridge"
    ) -join "; "
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $bridgeCommand) | Out-Null
}

if (-not $NoMcp) {
    Write-Step "Starting MCP RAG server in a new terminal..."
    $mcpCommand = @(
        "Set-Location '$RepoRoot'",
        "if (Test-Path '$VenvActivate') { . '$VenvActivate' }",
        "open-fdd-mcp-rag"
    ) -join "; "
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $mcpCommand) | Out-Null
}

if (-not $NoUi) {
    if ($UiMode -eq "dev") {
        Write-Step "Starting web UI (Vite dev) in a new terminal..."
        $uiCommand = @(
            "Set-Location '$RepoRoot'",
            "if (Test-Path '$VenvActivate') { . '$VenvActivate' }",
            "Set-Location '$WebUiDir'",
            "`$env:VITE_DESKTOP_BRIDGE_BASE='$BridgeUrl'",
            "npm run dev -- --host 0.0.0.0 --port $UiPort"
        ) -join "; "
        Start-Process powershell -ArgumentList @("-NoExit", "-Command", $uiCommand) | Out-Null
    } else {
        Write-Step "Building and serving static web UI in a new terminal..."
        $uiCommand = @(
            "Set-Location '$RepoRoot'",
            "if (Test-Path '$VenvActivate') { . '$VenvActivate' }",
            "Set-Location '$WebUiDir'",
            "`$env:VITE_DESKTOP_BRIDGE_BASE='$BridgeUrl'",
            "npm run build",
            "python -m http.server $UiPort --directory dist --bind 0.0.0.0"
        ) -join "; "
        Start-Process powershell -ArgumentList @("-NoExit", "-Command", $uiCommand) | Out-Null
    }
}

Write-Step "Ready."
Write-Step "Bridge API: $BridgeUrl"
if (-not $NoMcp) { Write-Step "MCP URL: http://127.0.0.1:8090" }
if (-not $NoUi) { Write-Step "Web UI:  http://127.0.0.1:$UiPort" }
