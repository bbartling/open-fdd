# Test Caddy basic auth for all key routes (one credential set).
# Run from Windows: .\test-auth-windows.ps1
# Or: .\test-auth-windows.ps1 -Host 192.168.204.16 -User openfdd -Password xyz

param(
    [string]$Host = "192.168.204.16",
    [string]$User = "openfdd",
    [string]$Password = "xyz"
)

$baseUrl = "http://${Host}:8088"
$auth = "${User}:${Password}"

$routes = @(
    @{ Path = "/"; Name = "Root (React HTML)" },
    @{ Path = "/sites"; Name = "API /sites" },
    @{ Path = "/health"; Name = "API /health" },
    @{ Path = "/capabilities"; Name = "API /capabilities" },
    @{ Path = "/docs"; Name = "Swagger docs" },
    @{ Path = "/@vite/client"; Name = "Vite client (frontend)" }
)

Write-Host "Testing Caddy basic auth at $baseUrl" -ForegroundColor Cyan
Write-Host "User: $User (one auth for all routes)`n" -ForegroundColor Cyan

$failed = 0
foreach ($r in $routes) {
    $url = $baseUrl + $r.Path
    $code = $null
    try {
        $output = curl.exe -s -o NUL -w "%{http_code}" -u $auth $url 2>&1
        $code = [int]$output
    } catch {
        $code = 0
    }
    if ($code -eq 200) {
        Write-Host "  OK   $($r.Name)  -> $code" -ForegroundColor Green
    } elseif ($code -eq 401) {
        Write-Host "  FAIL $($r.Name)  -> 401 (auth rejected)" -ForegroundColor Red
        $failed++
    } else {
        Write-Host "  ??   $($r.Name)  -> $code" -ForegroundColor Yellow
        if ($code -ne 0) { $failed++ }
    }
}

Write-Host ""
if ($failed -eq 0) {
    Write-Host "All routes accepted basic auth. Browser should do the same (one login for $baseUrl)." -ForegroundColor Green
    Write-Host "If browser still fails: use http (not https), try Chrome Incognito, type $User and $Password manually." -ForegroundColor Gray
} else {
    Write-Host "$failed route(s) failed. Check Caddyfile and restart: docker restart openfdd_caddy" -ForegroundColor Red
}
