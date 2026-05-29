# Open-FDD LAN connectivity check — run on your Windows PC.
# Usage:  powershell -ExecutionPolicy Bypass -File .\lan_diag.ps1
#         powershell -ExecutionPolicy Bypass -File .\lan_diag.ps1 -Host 192.168.204.18 -Port 8765

param(
    [string]$Host = "192.168.204.18",
    [int]$Port = 8765
)

$ErrorActionPreference = "Continue"
Write-Host "=== Open-FDD LAN diagnostic ===" -ForegroundColor Cyan
Write-Host "Target: http://${Host}:${Port}/login"
Write-Host ""

Write-Host "--- This PC ---" -ForegroundColor Yellow
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" } |
    Select-Object InterfaceAlias, IPAddress, PrefixLength |
    Format-Table -AutoSize

Write-Host "--- Ping ${Host} ---" -ForegroundColor Yellow
Test-Connection -ComputerName $Host -Count 2 -Quiet | ForEach-Object {
    if ($_) { Write-Host "Ping: OK" -ForegroundColor Green }
    else { Write-Host "Ping: " -NoNewline; Write-Host "FAILED" -ForegroundColor Red }
}

Write-Host ""
Write-Host "--- TCP port ${Port} ---" -ForegroundColor Yellow
$tcp = Test-NetConnection -ComputerName $Host -Port $Port -WarningAction SilentlyContinue
Write-Host "TcpTestSucceeded: $($tcp.TcpTestSucceeded)"
if (-not $tcp.TcpTestSucceeded) {
    Write-Host ""
    Write-Host "CONNECTION TIMEOUT usually means:" -ForegroundColor Red
    Write-Host "  1. bensserver firewall (UFW) blocking port $Port — on bensserver run:"
    Write-Host "       sudo ./scripts/open_lan_port.sh"
    Write-Host "  2. Windows and bensserver on different subnets / guest Wi-Fi isolation"
    Write-Host "  3. Corporate VPN or proxy intercepting LAN traffic"
    Write-Host ""
    Write-Host "If you have Tailscale on both machines, try:"
    Write-Host "  http://100.119.25.53:${Port}/login"
    exit 1
}

Write-Host ""
Write-Host "--- HTTP GET /health ---" -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://${Host}:${Port}/health" -UseBasicParsing -TimeoutSec 10
    Write-Host "Status: $($resp.StatusCode)"
    Write-Host $resp.Content
} catch {
    Write-Host "HTTP failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "--- HTTP GET /login (first 200 chars) ---" -ForegroundColor Yellow
try {
    $login = Invoke-WebRequest -Uri "http://${Host}:${Port}/login" -UseBasicParsing -TimeoutSec 10
    Write-Host "Status: $($login.StatusCode)  Content-Type: $($login.Headers['Content-Type'])"
    $preview = $login.Content
    if ($preview.Length -gt 200) { $preview = $preview.Substring(0, 200) + "..." }
    Write-Host $preview
} catch {
    Write-Host "Login page failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "LAN path looks OK — open in Chrome/Firefox (not an IDE preview):" -ForegroundColor Green
Write-Host "  http://${Host}:${Port}/login"
Write-Host "  integrator / msi-local"
