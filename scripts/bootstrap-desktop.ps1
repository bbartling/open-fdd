param(
    [switch]$InstallDeps,
    [switch]$NoBridge,
    [switch]$NoTauri,
    [switch]$NoLaunch
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
$DesktopUiDir = Join-Path $RepoRoot "apps\desktop-ui"
$VenvActivate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"

Write-Step "Repo root: $RepoRoot"

if (-not (Test-Path $DesktopUiDir)) {
    throw "Desktop UI directory not found: $DesktopUiDir"
}

if (Test-Path $CargoBin) {
    if (-not ($env:Path -split ";" | Where-Object { $_ -eq $CargoBin })) {
        $env:Path += ";$CargoBin"
    }
}

if (-not (Test-Path $VenvActivate)) {
    Write-Step "Creating Python virtualenv..."
    Push-Location $RepoRoot
    try {
        python -m venv .venv
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
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            $killed = $true
        }
    } catch {
        # best effort
    }
    if (-not $killed) {
        try {
            $null = & taskkill /F /IM open-fdd-desktop-bridge.exe 2>$null
        } catch {
            # best effort
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

    Write-Step "Installing desktop UI npm deps..."
    Push-Location $DesktopUiDir
    try {
        Invoke-Checked { npm install } "npm install failed."
    } finally {
        Pop-Location
    }
}

if ($NoLaunch) {
    Write-Step "Bootstrap complete (NoLaunch set)."
    exit 0
}

if (-not $NoBridge) {
    Write-Step "Starting FastAPI desktop bridge in a new terminal..."
    $bridgeCommand = @(
        "Set-Location '$RepoRoot'",
        "if (Test-Path '$VenvActivate') { . '$VenvActivate' }",
        "open-fdd-desktop-bridge"
    ) -join "; "
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $bridgeCommand) | Out-Null
}

if (-not $NoTauri) {
    Write-Step "Starting Tauri desktop UI in a new terminal..."
    $tauriCommand = @(
        "if (Test-Path '$CargoBin') { `$env:Path += ';$CargoBin' }",
        "Set-Location '$DesktopUiDir'",
        "npm run tauri dev"
    ) -join "; "
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $tauriCommand) | Out-Null
}

Write-Step "Done. Use -InstallDeps on first run if needed."
