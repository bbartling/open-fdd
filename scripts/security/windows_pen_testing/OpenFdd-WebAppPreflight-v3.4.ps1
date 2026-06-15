<#
OpenFdd-WebAppPreflight-v3.4.ps1

Small no-SSH preflight before running Run-OpenFddWebAppSecurityScan-v3.4.ps1.
It checks one Open-FDD web app URL from this Windows machine.
#>

param(
    [string]$TargetUrl = "http://192.168.204.18",
    [string]$ExpectedClosedPorts = "8765,8090,5173,8000,8080",
    [string]$ReportDir = "openfdd-webapp-preflight",
    [int]$TimeoutSec = 10,
    [switch]$SkipExpectedClosedPorts
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$TargetUrl = $TargetUrl.TrimEnd('/')
try { $Uri = [System.Uri]$TargetUrl; $TargetHost = $Uri.Host; $FrontPort = $Uri.Port } catch { throw "TargetUrl must be a valid URL like http://192.168.204.18 or http://192.168.204.18:8765" }
$BaseDir = if ([System.IO.Path]::IsPathRooted($ReportDir)) { $ReportDir } else { Join-Path (Get-Location).Path $ReportDir }
if (Test-Path $BaseDir) { Remove-Item -Path $BaseDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $BaseDir | Out-Null
$Report = Join-Path $BaseDir "openfdd-webapp-preflight.txt"

function Write-Section { param([string]$Text) Write-Host "`n--- $Text ---" -ForegroundColor Yellow; Add-Content -Path $Report -Value "`n--- $Text ---" -Encoding utf8 }
function Write-Ok { param([string]$Text) Write-Host "OK: $Text" -ForegroundColor Green; Add-Content -Path $Report -Value "OK: $Text" -Encoding utf8 }
function Write-Warn { param([string]$Text) Write-Host "WARN: $Text" -ForegroundColor Yellow; Add-Content -Path $Report -Value "WARN: $Text" -Encoding utf8 }
function Write-Bad { param([string]$Text) Write-Host "FAIL: $Text" -ForegroundColor Red; Add-Content -Path $Report -Value "FAIL: $Text" -Encoding utf8 }
function Test-CommandAvailable { param([string]$Name) return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue)) }

function Invoke-OpenFddGet {
    param([string]$Url)
    Write-Host "GET $Url"
    Add-Content -Path $Report -Value "`nGET $Url" -Encoding utf8
    if (Test-CommandAvailable "curl.exe") {
        $Out = & curl.exe -k -sS --max-time $TimeoutSec -i $Url 2>&1 | ForEach-Object { $_.ToString() }
        $Exit = $LASTEXITCODE
        Add-Content -Path $Report -Value $Out -Encoding utf8
        $Out | Select-Object -First 30 | ForEach-Object { Write-Host $_ }
        if ($Exit -ne 0) { Write-Bad "curl exit code $Exit"; return $false }
        return $true
    }
    try {
        $Resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        Write-Host "Status: $($Resp.StatusCode)"
        Add-Content -Path $Report -Value "Status: $($Resp.StatusCode)" -Encoding utf8
        return $true
    } catch {
        Write-Bad $_.Exception.Message
        return $false
    }
}

Set-Content -Path $Report -Value @(
    "Open-FDD web app preflight",
    "Run time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "TargetUrl: $TargetUrl",
    "TargetHost: $TargetHost",
    "FrontPort: $FrontPort",
    "Expected closed ports: $ExpectedClosedPorts",
    ""
) -Encoding utf8

Write-Host "=== Open-FDD web app preflight ===" -ForegroundColor Cyan
Write-Host "Target: $TargetUrl"
Write-Host "Report: $Report"
$ScriptDir = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { $PSScriptRoot }
$LocalAuthFile = Join-Path $ScriptDir "auth.env.local"
if (Test-Path $LocalAuthFile) { Write-Host "Auth file next to scripts: $LocalAuthFile" -ForegroundColor Green }
else { Write-Host "Auth file next to scripts not found: $LocalAuthFile" -ForegroundColor Yellow }

Write-Section "This PC IPv4 addresses"
try {
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" } | Select-Object InterfaceAlias, IPAddress, PrefixLength | Format-Table -AutoSize | Out-String | Tee-Object -FilePath $Report -Append | Write-Host
} catch { Write-Warn "Could not read local IPv4 addresses: $($_.Exception.Message)" }

Write-Section "DNS / ping $TargetHost"
try {
    $Resolved = Resolve-DnsName -Name $TargetHost -ErrorAction SilentlyContinue
    if ($Resolved) { $Resolved | Format-Table -AutoSize | Out-String | Tee-Object -FilePath $Report -Append | Write-Host }
} catch { }
if (Test-Connection -ComputerName $TargetHost -Count 2 -Quiet) { Write-Ok "Ping responded" } else { Write-Warn "Ping failed or is blocked; TCP may still work" }

Write-Section "Front-door TCP port $FrontPort"
$Tcp = Test-NetConnection -ComputerName $TargetHost -Port $FrontPort -WarningAction SilentlyContinue
("TcpTestSucceeded: $($Tcp.TcpTestSucceeded)" | Tee-Object -FilePath $Report -Append) | Write-Host
if (-not $Tcp.TcpTestSucceeded) {
    Write-Bad "TCP connection failed to $($TargetHost):$FrontPort"
    Write-Host "Common fixes: wrong URL/port, Caddy not running, firewall/UFW, different subnet, VPN/Tailscale path issue."
    exit 1
} else { Write-Ok "Front-door TCP port reachable" }

if (-not $SkipExpectedClosedPorts) {
    Write-Section "Expected-closed internal/dev ports"
    foreach ($PText in ($ExpectedClosedPorts -split ',')) {
        $PText = $PText.Trim()
        if ($PText -notmatch '^\d+$') { continue }
        $P = [int]$PText
        if ($P -eq $FrontPort) { Write-Warn "Skipping expected-closed check for active front-door port $P"; continue }
        $T = Test-NetConnection -ComputerName $TargetHost -Port $P -WarningAction SilentlyContinue
        if ($T.TcpTestSucceeded) { Write-Bad "Port $P is reachable. Confirm this is intentional." }
        else { Write-Ok "Port $P not reachable from this PC" }
    }
}

Write-Section "HTTP probes"
$AnyOk = $false
foreach ($Path in @("/", "/health", "/api/health", "/login")) {
    $Ok = Invoke-OpenFddGet -Url "$TargetUrl$Path"
    if ($Ok) { $AnyOk = $true }
}

if ($AnyOk) {
    Write-Ok "Web app path looks usable"
    Write-Host "Report saved: $Report"
} else {
    Write-Bad "TCP works, but HTTP probes failed"
    Write-Host "Report saved: $Report"
    exit 1
}
