<#
Run-OpenFddWebAppSecurityScan-v3.4.ps1

Open-FDD web-app-only security smoke/release gate from Windows PowerShell.

Version 3.4 makes authentication explicit and fail-fast. By default, the scanner expects
a local auth.env.local file in the same directory as this PowerShell script. It stops before
scanning if AuthKind is Basic and the env file or selected role credentials cannot be loaded.
Secrets are parsed as text, not dot-sourced, so special characters like &, %, $, #, and * are safe.

Scope:
- One web app URL only
- ZAP baseline/passive scan
- Scoped Nmap safe web/header/service scan against one host
- Anonymous protected-route checks
- Authenticated route checks using auth.env.local beside this script by default
- CORS negative tests with a fake hostile Origin
- Header/cache checks
- Built/static asset scan for hardcoded private IPs and absolute app URLs

No SSH. No server login. No subnet scanning. No active ZAP attack scan. No Notepad/browser.
#>

param(
    [string]$TargetUrl = "http://192.168.204.18",
    [string]$HostIp = "",
    [string]$Ports = "80,443,8765,8000,8080,5173,8090",
    [string]$ExpectedOpenPorts = "80",
    [string]$ExpectedClosedPorts = "8765,8000,8080,5173,8090",
    [string]$ReportDir = "openfdd-webapp-security-report",
    [string]$BuiltAssetsDir = "",

    [ValidateSet("None", "Basic")]
    [string]$AuthKind = "Basic",
    [ValidateSet("Integrator", "Operator", "Agent")]
    [string]$AuthRole = "Integrator",
    [string]$AuthEnvFile = "", # default: auth.env.local beside this .ps1
    [string]$AuthUser = "",
    [string]$AuthPassword = "",

    [int]$HttpTimeoutSec = 20,
    [int]$ZapSpiderMinutes = 3,
    [int]$MaxAssets = 40,

    [string[]]$PublicPaths = @("/", "/health", "/api/health", "/login"),
    [string[]]$ProtectedPaths = @(
        "/api/auth/me",
        "/api/points",
        "/api/equipment",
        "/api/rules",
        "/api/faults",
        "/api/fdd/results",
        "/api/bacnet/points",
        "/api/bacnet/overrides",
        "/api/runtime/metrics",
        "/api/rdf/model",
        "/api/niagara/samples",
        "/api/commission/status"
    ),

    [switch]$SkipZap,
    [switch]$SkipZapPull,
    [switch]$SkipNmap,
    [switch]$SkipAssetScan,
    [switch]$SkipRouteTests,
    [switch]$KeepExisting,
    [switch]$DeepTls,
    [switch]$MediumIsFail,
    [switch]$ExitNonZeroOnFail
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$script:Findings = New-Object System.Collections.Generic.List[object]
$script:AuthHeaderResolved = ""
$script:AuthPasswordResolved = ""

function Write-Section { param([string]$Text) Write-Host ""; Write-Host "============================================================" -ForegroundColor DarkGray; Write-Host $Text -ForegroundColor Cyan; Write-Host "============================================================" -ForegroundColor DarkGray }
function Write-Ok { param([string]$Text) Write-Host "OK: $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "WARN: $Text" -ForegroundColor Yellow }
function Write-Bad { param([string]$Text) Write-Host "FAIL: $Text" -ForegroundColor Red }
function Test-CommandAvailable { param([string]$Name) return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue)) }

function Add-Finding {
    param([ValidateSet("PASS","WARN","FAIL","INFO")][string]$Severity, [string]$Area, [string]$Message)
    $script:Findings.Add([pscustomobject]@{ Severity=$Severity; Area=$Area; Message=$Message }) | Out-Null
    if ($Severity -eq "PASS") { Write-Ok "$Area - $Message" }
    elseif ($Severity -eq "FAIL") { Write-Bad "$Area - $Message" }
    elseif ($Severity -eq "WARN") { Write-Warn "$Area - $Message" }
}

function Mask-SecretText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $Text }
    if (-not [string]::IsNullOrWhiteSpace($script:AuthPasswordResolved)) { $Text = $Text.Replace($script:AuthPasswordResolved, "***PASSWORD***") }
    if (-not [string]::IsNullOrWhiteSpace($script:AuthHeaderResolved)) { $Text = $Text.Replace($script:AuthHeaderResolved, "Basic ***MASKED***") }
    return $Text
}

function Invoke-NativeToFile {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$OutputFile,
        [string[]]$DisplayArgs = $null,
        [switch]$Append
    )
    if ($null -eq $DisplayArgs) { $DisplayArgs = $Args }
    $ArgLine = ($DisplayArgs | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_.Replace('"','\"')) + '"' } else { $_ } }) -join " "
    $Header = @("> $Exe $ArgLine", "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", "")
    if ($Append) { Add-Content -Path $OutputFile -Value $Header -Encoding utf8 } else { Set-Content -Path $OutputFile -Value $Header -Encoding utf8 }
    try {
        $Output = & $Exe @Args 2>&1 | ForEach-Object { Mask-SecretText $_.ToString() }
        $ExitCode = $LASTEXITCODE
        if ($null -eq $ExitCode) { $ExitCode = 0 }
        Add-Content -Path $OutputFile -Value "ExitCode: $ExitCode" -Encoding utf8
        if ($Output) { Add-Content -Path $OutputFile -Value "`n--- OUTPUT ---" -Encoding utf8; Add-Content -Path $OutputFile -Value $Output -Encoding utf8 }
        Add-Content -Path $OutputFile -Value "`nFinished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" -Encoding utf8
        return $ExitCode
    } catch {
        Add-Content -Path $OutputFile -Value "ERROR: $($_.Exception.Message)" -Encoding utf8
        return 9999
    }
}

function Get-NormalizedUrl { param([string]$Url) return $Url.TrimEnd('/') }
function Join-UrlPath { param([string]$BaseUrl, [string]$Path) return "$(Get-NormalizedUrl $BaseUrl)/$($Path.TrimStart('/'))" }

function Get-HostFromUrl {
    param([string]$Url)
    try { return ([System.Uri]$Url).Host } catch { return $Url }
}

function Get-ZapDockerTargetUrl {
    param([string]$Url)
    try {
        $Uri = [System.Uri]$Url
        if ($Uri.Host -in @("localhost", "127.0.0.1", "::1")) {
            $Builder = New-Object System.UriBuilder($Uri)
            $Builder.Host = "host.docker.internal"
            return $Builder.Uri.AbsoluteUri.TrimEnd('/')
        }
    } catch { return $Url }
    return (Get-NormalizedUrl $Url)
}

function Test-SingleHostScope {
    param([string]$HostValue)
    if ($HostValue -match '/' -or $HostValue -match ',' -or $HostValue -match '\s' -or $HostValue -match '\.\.\.' -or $HostValue -match '\d-\d') {
        throw "HostIp must be one host only, not a CIDR/range/list. Received: $HostValue"
    }
}

function Read-DotEnvFile {
    param([string]$Path)
    $Map = @{}
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) { return $Map }
    foreach ($LineRaw in Get-Content -Path $Path -ErrorAction SilentlyContinue) {
        $Line = $LineRaw.Trim()
        if ($Line -eq "" -or $Line.StartsWith("#")) { continue }
        $Idx = $Line.IndexOf("=")
        if ($Idx -le 0) { continue }
        $Key = $Line.Substring(0, $Idx).Trim()
        $Val = $Line.Substring($Idx + 1).Trim().Trim('"').Trim("'")
        $Map[$Key] = $Val
    }
    return $Map
}

function Resolve-Auth {
    if ($AuthKind -eq "None") { return $false }
    $Env = Read-DotEnvFile -Path $AuthEnvFile

    # Open-FDD uses OFDD_* keys in auth.env.local. Keep legacy/common
    # names too so older benches and Caddy/basic-auth test files still work.
    $RolePrefix = $AuthRole.ToUpperInvariant()
    $UserKeys = @(
        "OFDD_${RolePrefix}_USER",
        "OFDD_${RolePrefix}_USERNAME",
        "OPENFDD_${RolePrefix}_USER",
        "OPENFDD_${RolePrefix}_USERNAME",
        "OFDD_AUTH_USER",
        "OPENFDD_AUTH_USER",
        "${RolePrefix}_USER",
        "${RolePrefix}_USERNAME",
        "CADDY_AUTH_USER",
        "BASIC_AUTH_USER"
    )
    $PassKeys = @(
        "OFDD_${RolePrefix}_PASSWORD",
        "OPENFDD_${RolePrefix}_PASSWORD",
        "OFDD_AUTH_PASSWORD",
        "OPENFDD_AUTH_PASSWORD",
        "${RolePrefix}_PASSWORD",
        "CADDY_AUTH_PASSWORD",
        "BASIC_AUTH_PASSWORD"
    )

    if ([string]::IsNullOrWhiteSpace($AuthUser)) {
        foreach ($K in $UserKeys) { if ($Env.ContainsKey($K) -and -not [string]::IsNullOrWhiteSpace($Env[$K])) { $script:AuthUserResolved = $Env[$K]; break } }
    } else { $script:AuthUserResolved = $AuthUser }
    if ([string]::IsNullOrWhiteSpace($AuthPassword)) {
        foreach ($K in $PassKeys) { if ($Env.ContainsKey($K) -and -not [string]::IsNullOrWhiteSpace($Env[$K])) { $script:AuthPasswordResolved = $Env[$K]; break } }
    } else { $script:AuthPasswordResolved = $AuthPassword }

    if ($AuthKind -eq "Basic" -and -not [string]::IsNullOrWhiteSpace($script:AuthUserResolved) -and -not [string]::IsNullOrWhiteSpace($script:AuthPasswordResolved)) {
        $Pair = "$($script:AuthUserResolved):$($script:AuthPasswordResolved)"
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Pair)
        $script:AuthHeaderResolved = "Basic " + [System.Convert]::ToBase64String($Bytes)
        return $true
    }
    return $false
}

function Invoke-CurlProbe {
    param(
        [string]$Url,
        [string]$OutPrefix,
        [string]$Method = "GET",
        [string[]]$Headers = @(),
        [switch]$UseAuth
    )
    $HeadersFile = "$OutPrefix.headers.txt"
    $BodyFile = "$OutPrefix.body.txt"
    $ConsoleFile = "$OutPrefix.console.txt"
    $Args = @("-k", "-sS", "--max-time", "$HttpTimeoutSec", "-D", $HeadersFile, "-o", $BodyFile, "-X", $Method)
    $DisplayArgs = @("-k", "-sS", "--max-time", "$HttpTimeoutSec", "-D", $HeadersFile, "-o", $BodyFile, "-X", $Method)
    foreach ($H in $Headers) { $Args += @("-H", $H); $DisplayArgs += @("-H", $H) }
    if ($UseAuth -and -not [string]::IsNullOrWhiteSpace($script:AuthHeaderResolved)) {
        $Args += @("-H", "Authorization: $($script:AuthHeaderResolved)")
        $DisplayArgs += @("-H", "Authorization: Basic ***MASKED***")
    }
    $Args += $Url
    $DisplayArgs += $Url
    Invoke-NativeToFile -Exe "curl.exe" -Args $Args -DisplayArgs $DisplayArgs -OutputFile $ConsoleFile | Out-Null
    $Status = 0
    if (Test-Path $HeadersFile) {
        $Lines = Get-Content -Path $HeadersFile -ErrorAction SilentlyContinue
        $HttpLines = @($Lines | Where-Object { $_ -match '^HTTP/' })
        if ($HttpLines.Count -gt 0 -and $HttpLines[-1] -match '^HTTP/\S+\s+(\d+)') { $Status = [int]$Matches[1] }
    }
    return [pscustomobject]@{ Status=$Status; HeadersFile=$HeadersFile; BodyFile=$BodyFile; ConsoleFile=$ConsoleFile }
}

function Get-HeaderValue {
    param([string]$HeaderFile, [string]$Name)
    if (-not (Test-Path $HeaderFile)) { return "" }
    $Pattern = "^" + [regex]::Escape($Name) + ":\s*(.*)$"
    $Values = @(Get-Content -Path $HeaderFile -ErrorAction SilentlyContinue | Where-Object { $_ -match $Pattern } | ForEach-Object { ($_ -replace $Pattern, '$1').Trim() })
    if ($Values.Count -eq 0) { return "" }
    return $Values[-1]
}

function Resolve-AssetUrl {
    param([string]$BaseUrl, [string]$Asset)
    if ($Asset -match '^https?://') { return $Asset }
    $Uri = [System.Uri](Get-NormalizedUrl $BaseUrl)
    if ($Asset.StartsWith('/')) { return "$($Uri.Scheme)://$($Uri.Authority)$Asset" }
    return "$(Get-NormalizedUrl $BaseUrl)/$Asset"
}

function Get-NmapPortStates {
    param([string]$NmapFile)
    $Rows = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path $NmapFile)) { return $Rows }
    foreach ($Line in Get-Content -Path $NmapFile -ErrorAction SilentlyContinue) {
        if ($Line -match '^(\d+)/tcp\s+(open|closed|filtered)\s+(\S+)') {
            $Rows.Add([pscustomobject]@{ Port=[int]$Matches[1]; State=$Matches[2]; Service=$Matches[3]; Line=$Line }) | Out-Null
        }
    }
    return $Rows
}

function Get-ZapAlertsFromJson {
    param([string]$JsonPath)
    $Alerts = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path $JsonPath)) { return $Alerts }
    try {
        $Json = Get-Content -Raw -Path $JsonPath | ConvertFrom-Json
        if ($Json.site) {
            foreach ($Site in @($Json.site)) {
                foreach ($Alert in @($Site.alerts)) { $Alerts.Add($Alert) | Out-Null }
            }
        }
    } catch { }
    return $Alerts
}

# Normalize target, auth, and paths
$TargetUrl = Get-NormalizedUrl $TargetUrl
if ([string]::IsNullOrWhiteSpace($HostIp)) { $HostIp = Get-HostFromUrl $TargetUrl }
Test-SingleHostScope -HostValue $HostIp
$ZapTargetUrl = Get-ZapDockerTargetUrl $TargetUrl

$ScriptDir = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($AuthEnvFile)) {
    $AuthEnvFile = Join-Path $ScriptDir "auth.env.local"
} elseif (-not [System.IO.Path]::IsPathRooted($AuthEnvFile)) {
    # Relative auth paths are resolved relative to the script directory, not the current shell folder.
    $AuthEnvFile = Join-Path $ScriptDir $AuthEnvFile
}

$ExplicitAuthProvided = (-not [string]::IsNullOrWhiteSpace($AuthUser)) -and (-not [string]::IsNullOrWhiteSpace($AuthPassword))
if ($AuthKind -ne "None" -and -not $ExplicitAuthProvided -and -not (Test-Path $AuthEnvFile)) {
    Write-Host "FAIL: auth - required auth env file was not found: $AuthEnvFile" -ForegroundColor Red
    Write-Host "Put auth.env.local beside the .ps1 scripts, or pass -AuthEnvFile with a valid path. Use -AuthKind None only for anonymous-only testing." -ForegroundColor Yellow
    exit 2
}

$AuthEnabled = Resolve-Auth
if ($AuthKind -ne "None" -and -not $AuthEnabled) {
    $AuthRoleHint = "OFDD_$($AuthRole.ToUpperInvariant())_USER and OFDD_$($AuthRole.ToUpperInvariant())_PASSWORD"
    Write-Host "FAIL: auth - could not load Basic auth credentials for role $AuthRole from: $AuthEnvFile" -ForegroundColor Red
    Write-Host "Expected keys include: $AuthRoleHint" -ForegroundColor Yellow
    Write-Host "The scan is stopping so we do not accidentally run a mostly anonymous test." -ForegroundColor Yellow
    exit 2
}

$BaseDir = if ([System.IO.Path]::IsPathRooted($ReportDir)) { $ReportDir } else { Join-Path (Get-Location).Path $ReportDir }
if ((Test-Path $BaseDir) -and -not $KeepExisting) { Remove-Item -Path $BaseDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $BaseDir | Out-Null
$AssetDir = Join-Path $BaseDir "downloaded-assets"
New-Item -ItemType Directory -Force -Path $AssetDir | Out-Null

$ToolReport = Join-Path $BaseDir "00-tool-checks.txt"
$TargetReport = Join-Path $BaseDir "01-target-reachability.txt"
$NmapConsole = Join-Path $BaseDir "20-nmap-console.txt"
$NmapServices = Join-Path $BaseDir "21-nmap-services.nmap"
$NmapHttp = Join-Path $BaseDir "22-nmap-http.nmap"
$NmapHttpConsole = Join-Path $BaseDir "23-nmap-http-console.txt"
$HeaderReport = Join-Path $BaseDir "05-header-cache-summary.txt"
$RouteReport = Join-Path $BaseDir "04-route-auth-cors-tests.txt"
$AssetReport = Join-Path $BaseDir "06-asset-leak-summary.txt"
$ZapConsole = Join-Path $BaseDir "40-zap-console.txt"
$ZapHtml = "zap-baseline.html"
$ZapJson = "zap-baseline.json"
$ZapMd = "zap-baseline.md"
$ZapJsonPath = Join-Path $BaseDir $ZapJson
$ZapMdPath = Join-Path $BaseDir $ZapMd
$NmapFindings = Join-Path $BaseDir "30-nmap-findings-summary.txt"
$ZapFindings = Join-Path $BaseDir "31-zap-findings-summary.txt"
$GateCsv = Join-Path $BaseDir "98-security-gate-results.csv"
$QuickSummary = Join-Path $BaseDir "90-quick-findings-summary.txt"
$Checklist = Join-Path $BaseDir "99-review-checklist.txt"
$FixPrompt = Join-Path $BaseDir "91-cursor-agent-fix-prompt.txt"
$WebRootPrefix = Join-Path $BaseDir "02-root"
$WebBodySample = "$WebRootPrefix.body.txt"

Write-Section "Open-FDD web app security smoke scan"
Write-Host "TargetUrl: $TargetUrl"
Write-Host "HostIp for Nmap: $HostIp"
Write-Host "ReportDir: $BaseDir"
Write-Host "Auth loaded: $AuthEnabled"
Write-Host "No SSH is used by this script."

# Tool checks
Write-Section "Checking local tools"
$DockerOk = Test-CommandAvailable "docker"
$NmapOk = Test-CommandAvailable "nmap"
$CurlOk = Test-CommandAvailable "curl.exe"
@(
    "Tool checks generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "curl.exe: $CurlOk",
    "nmap: $NmapOk",
    "docker: $DockerOk",
    "TargetUrl: $TargetUrl",
    "ZapTargetUrl: $ZapTargetUrl",
    "Auth loaded: $AuthEnabled",
    "AuthRole: $AuthRole",
    "AuthEnvFile: $(if ([string]::IsNullOrWhiteSpace($AuthEnvFile)) { 'not provided' } else { $AuthEnvFile })"
) | Set-Content -Path $ToolReport -Encoding utf8
if ($CurlOk) { Add-Finding PASS "tools" "curl.exe found" } else { Add-Finding FAIL "tools" "curl.exe not found" }
if ($NmapOk) { Add-Finding PASS "tools" "nmap found" } else { Add-Finding WARN "tools" "nmap not found; Nmap scan will be skipped" }
if ($DockerOk) { Add-Finding PASS "tools" "docker found" } else { Add-Finding WARN "tools" "docker not found; ZAP scan will be skipped" }
$AuthRoleHint = "OFDD_$($AuthRole.ToUpperInvariant())_USER/PASSWORD"
if ($AuthEnabled) { Add-Finding INFO "auth" "Basic auth loaded for role $AuthRole from $AuthEnvFile; secrets are masked in reports" } else { Add-Finding INFO "auth" "AuthKind None: anonymous-only scan requested" }

# Reachability and headers
Write-Section "Checking web app reachability and headers"
if ($CurlOk) {
    $Root = Invoke-CurlProbe -Url $TargetUrl -OutPrefix $WebRootPrefix -UseAuth:($AuthEnabled)
    @("Target reachability", "TargetUrl: $TargetUrl", "HTTP status: $($Root.Status)") | Set-Content -Path $TargetReport -Encoding utf8
    if ($Root.Status -ge 200 -and $Root.Status -lt 500) { Add-Finding PASS "target" "target returned HTTP $($Root.Status)" } else { Add-Finding FAIL "target" "target did not return a useful HTTP status: $($Root.Status)" }
} else {
    "curl.exe unavailable; cannot check target." | Set-Content -Path $TargetReport -Encoding utf8
}

@"
Open-FDD header/cache checks
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Expected:
- UI/root should have CSP, referrer policy, nosniff, frame protection.
- API/auth/data responses should usually use Cache-Control: no-store or equivalent.
- CSP with unsafe-inline is a WARN unless you decide to fail Medium findings.
"@ | Set-Content -Path $HeaderReport -Encoding utf8

if ($CurlOk) {
    foreach ($Path in $PublicPaths) {
        $SafeName = ($Path.Trim('/').Replace('/','-')); if ($SafeName -eq "") { $SafeName = "root" }
        $Probe = Invoke-CurlProbe -Url (Join-UrlPath $TargetUrl $Path) -OutPrefix (Join-Path $BaseDir "05-public-$SafeName") -UseAuth:($AuthEnabled)
        Add-Content -Path $HeaderReport -Value "`nPATH $Path -> HTTP $($Probe.Status)" -Encoding utf8
        foreach ($H in @("Content-Security-Policy","Permissions-Policy","Referrer-Policy","X-Content-Type-Options","X-Frame-Options","Cross-Origin-Opener-Policy","Cross-Origin-Embedder-Policy","Cross-Origin-Resource-Policy","Cache-Control")) {
            $V = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name $H
            if (-not [string]::IsNullOrWhiteSpace($V)) { Add-Content -Path $HeaderReport -Value "${H}: $V" -Encoding utf8 }
        }
        $Csp = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name "Content-Security-Policy"
        $Xcto = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name "X-Content-Type-Options"
        $Ref = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name "Referrer-Policy"
        $Frame = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name "X-Frame-Options"
        $Cache = Get-HeaderValue -HeaderFile $Probe.HeadersFile -Name "Cache-Control"
        if ($Path -in @("/", "/login")) {
            if ([string]::IsNullOrWhiteSpace($Csp)) { Add-Finding WARN "headers" "$Path missing Content-Security-Policy" }
            elseif ($Csp -match "unsafe-inline") { Add-Finding WARN "headers" "$Path CSP includes unsafe-inline" }
            else { Add-Finding PASS "headers" "$Path has CSP without unsafe-inline" }
            if ($Xcto -match "nosniff") { Add-Finding PASS "headers" "$Path has X-Content-Type-Options nosniff" } else { Add-Finding WARN "headers" "$Path missing X-Content-Type-Options nosniff" }
            if (-not [string]::IsNullOrWhiteSpace($Ref)) { Add-Finding PASS "headers" "$Path has Referrer-Policy" } else { Add-Finding WARN "headers" "$Path missing Referrer-Policy" }
            if (($Frame -match "DENY|SAMEORIGIN") -or ($Csp -match "frame-ancestors")) { Add-Finding PASS "headers" "$Path has frame protection" } else { Add-Finding WARN "headers" "$Path missing X-Frame-Options/frame-ancestors" }
        }
        if ($Path -match '^/api' -or $Path -eq "/health") {
            if ($Cache -match "no-store|no-cache|private") { Add-Finding PASS "cache" "$Path has conservative Cache-Control" } else { Add-Finding WARN "cache" "$Path may be cacheable; API/auth responses should normally be no-store" }
        }
    }
}

# Route auth and CORS tests
Write-Section "Running route auth and CORS tests"
@"
Open-FDD route auth and CORS tests
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Expected:
- Protected API/data paths should NOT return 2xx anonymously.
- 401/403/302 for anonymous protected paths is good.
- 404/405 is a warning only; route may not exist in this build.
- Fake hostile Origin should not be reflected in Access-Control-Allow-Origin.
"@ | Set-Content -Path $RouteReport -Encoding utf8

if (-not $SkipRouteTests -and $CurlOk) {
    foreach ($Path in $ProtectedPaths) {
        $SafeName = ($Path.Trim('/').Replace('/','-'))
        $Url = Join-UrlPath -BaseUrl $TargetUrl -Path $Path
        $Anon = Invoke-CurlProbe -Url $Url -OutPrefix (Join-Path $BaseDir "04-anon-$SafeName")
        Add-Content -Path $RouteReport -Value "ANON protected $Path -> HTTP $($Anon.Status)" -Encoding utf8
        if ($Anon.Status -ge 200 -and $Anon.Status -lt 300) { Add-Finding FAIL "auth" "$Path returned HTTP $($Anon.Status) without auth" }
        elseif ($Anon.Status -in @(301,302,303,307,308,401,403)) { Add-Finding PASS "auth" "$Path denied/redirected anonymous access with HTTP $($Anon.Status)" }
        elseif ($Anon.Status -eq 404 -or $Anon.Status -eq 405) { Add-Finding WARN "auth" "$Path returned HTTP $($Anon.Status); route may not exist in this build" }
        elseif ($Anon.Status -eq 0) { Add-Finding WARN "auth" "$Path did not return an HTTP status" }
        else { Add-Finding WARN "auth" "$Path returned unexpected anonymous HTTP $($Anon.Status)" }

        if ($AuthEnabled) {
            $AuthProbe = Invoke-CurlProbe -Url $Url -OutPrefix (Join-Path $BaseDir "04-auth-$SafeName") -UseAuth
            Add-Content -Path $RouteReport -Value "AUTH protected $Path -> HTTP $($AuthProbe.Status)" -Encoding utf8
        }
    }

    $CorsPaths = @("/", "/health", "/api/health") + $ProtectedPaths[0..([Math]::Min(2, $ProtectedPaths.Count-1))]
    foreach ($Path in $CorsPaths) {
        $SafeName = ($Path.Trim('/').Replace('/','-')); if ($SafeName -eq "") { $SafeName = "root" }
        $Url = Join-UrlPath -BaseUrl $TargetUrl -Path $Path
        $CorsGet = Invoke-CurlProbe -Url $Url -OutPrefix (Join-Path $BaseDir "04-cors-get-$SafeName") -Headers @("Origin: https://evil.example") -UseAuth:($AuthEnabled)
        $Aco = Get-HeaderValue -HeaderFile $CorsGet.HeadersFile -Name "Access-Control-Allow-Origin"
        Add-Content -Path $RouteReport -Value "CORS GET $Path -> HTTP $($CorsGet.Status), ACAO=$Aco" -Encoding utf8
        if ($Aco -eq "*" -or $Aco -eq "https://evil.example") { Add-Finding FAIL "cors" "$Path reflects/allows fake hostile Origin ($Aco)" }
        elseif (-not [string]::IsNullOrWhiteSpace($Aco)) { Add-Finding WARN "cors" "$Path returns Access-Control-Allow-Origin=$Aco; confirm intended" }
        else { Add-Finding PASS "cors" "$Path does not allow fake hostile Origin" }

        $CorsOpt = Invoke-CurlProbe -Url $Url -OutPrefix (Join-Path $BaseDir "04-cors-options-$SafeName") -Method "OPTIONS" -Headers @("Origin: https://evil.example", "Access-Control-Request-Method: GET") -UseAuth:($AuthEnabled)
        $AcoOpt = Get-HeaderValue -HeaderFile $CorsOpt.HeadersFile -Name "Access-Control-Allow-Origin"
        Add-Content -Path $RouteReport -Value "CORS OPTIONS $Path -> HTTP $($CorsOpt.Status), ACAO=$AcoOpt" -Encoding utf8
        if ($AcoOpt -eq "*" -or $AcoOpt -eq "https://evil.example") { Add-Finding FAIL "cors" "$Path preflight allows fake hostile Origin ($AcoOpt)" }
    }
} elseif ($SkipRouteTests) { Add-Finding INFO "routes" "route auth/CORS tests skipped by flag" } else { Add-Finding FAIL "routes" "curl.exe unavailable; route auth/CORS tests skipped" }

# Asset scan
Write-Section "Scanning static assets for hardcoded IPs/absolute URLs"
@"
Open-FDD asset leak summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Patterns that should usually not appear in production UI bundles:
- 192.168.x.x / 10.x.x.x / 172.16-31.x.x private IPs
- 127.0.0.1 / localhost baked into the UI bundle
- ws:// absolute websocket URLs
- http:// absolute URLs for app/API calls
"@ | Set-Content -Path $AssetReport -Encoding utf8

if (-not $SkipAssetScan) {
    $FilesToScan = New-Object System.Collections.Generic.List[string]
    if (Test-Path $WebBodySample) {
        $Html = Get-Content -Raw -Path $WebBodySample -ErrorAction SilentlyContinue
        $AssetMatches = [regex]::Matches($Html, '(?:src|href)=["'']([^"'']+\.(?:js|css))(?:\?[^"'']*)?["'']', 'IgnoreCase')
        $Seen = @{}
        foreach ($M in $AssetMatches) {
            $Asset = $M.Groups[1].Value
            if ($Seen.ContainsKey($Asset)) { continue }
            $Seen[$Asset] = $true
            if ($Seen.Count -gt $MaxAssets) { break }
            $AssetUrl = Resolve-AssetUrl -BaseUrl $TargetUrl -Asset $Asset
            $LocalName = ($Asset -replace '[^a-zA-Z0-9_.-]', '_')
            if ($LocalName.Length -gt 120) { $LocalName = $LocalName.Substring($LocalName.Length - 120) }
            $LocalPath = Join-Path $AssetDir $LocalName
            if ($CurlOk) {
                $Args = @("-k", "-sS", "--max-time", "$HttpTimeoutSec", "-o", $LocalPath)
                $DisplayArgs = $Args.Clone()
                if ($AuthEnabled) { $Args += @("-H", "Authorization: $($script:AuthHeaderResolved)"); $DisplayArgs += @("-H", "Authorization: Basic ***MASKED***") }
                $Args += $AssetUrl; $DisplayArgs += $AssetUrl
                Invoke-NativeToFile -Exe "curl.exe" -Args $Args -DisplayArgs $DisplayArgs -OutputFile (Join-Path $AssetDir "$LocalName.console.txt") | Out-Null
                if (Test-Path $LocalPath) { $FilesToScan.Add($LocalPath) | Out-Null; Add-Content -Path $AssetReport -Value "Downloaded asset: $AssetUrl -> $LocalPath" -Encoding utf8 }
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($BuiltAssetsDir) -and (Test-Path $BuiltAssetsDir)) {
        Get-ChildItem -Path $BuiltAssetsDir -Recurse -Include *.js,*.css,*.html -File -ErrorAction SilentlyContinue | ForEach-Object { $FilesToScan.Add($_.FullName) | Out-Null }
        Add-Content -Path $AssetReport -Value "`nAlso scanning BuiltAssetsDir: $BuiltAssetsDir" -Encoding utf8
    }
    if ($FilesToScan.Count -eq 0) { Add-Finding WARN "assets" "no JS/CSS assets found to scan; provide -BuiltAssetsDir if needed" }
    $PrivateIpPattern = '(?<!\d)(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d)'
    foreach ($File in ($FilesToScan | Select-Object -Unique)) {
        $Text = Get-Content -Raw -Path $File -ErrorAction SilentlyContinue
        if ([string]::IsNullOrWhiteSpace($Text)) { continue }
        $FoundPrivate = [regex]::Matches($Text, $PrivateIpPattern) | ForEach-Object { $_.Value } | Select-Object -Unique
        $FoundLocal = [regex]::Matches($Text, '(localhost|127\.0\.0\.1)') | ForEach-Object { $_.Value } | Select-Object -Unique
        $FoundWs = [regex]::Matches($Text, 'ws://[^\s"''<>]+') | ForEach-Object { $_.Value } | Select-Object -Unique
        $FoundHttp = [regex]::Matches($Text, 'http://[^\s"''<>]+') | ForEach-Object { $_.Value } | Select-Object -Unique
        if ($FoundPrivate) { Add-Finding FAIL "assets" "private IP found in $([System.IO.Path]::GetFileName($File)): $($FoundPrivate -join ', ')"; Add-Content -Path $AssetReport -Value "PRIVATE IP in ${File}: $($FoundPrivate -join ', ')" -Encoding utf8 }
        if ($FoundLocal) { Add-Finding WARN "assets" "localhost/127.0.0.1 found in $([System.IO.Path]::GetFileName($File)); verify not app endpoint"; Add-Content -Path $AssetReport -Value "LOCALHOST in ${File}: $($FoundLocal -join ', ')" -Encoding utf8 }
        if ($FoundWs) { Add-Finding FAIL "assets" "absolute ws:// URL found in $([System.IO.Path]::GetFileName($File))"; Add-Content -Path $AssetReport -Value "WS URL in ${File}: $($FoundWs -join ', ')" -Encoding utf8 }
        if ($FoundHttp) { Add-Finding WARN "assets" "absolute http:// URL found in $([System.IO.Path]::GetFileName($File)); use relative paths for app APIs"; Add-Content -Path $AssetReport -Value "HTTP URL in ${File}: $($FoundHttp -join ', ')" -Encoding utf8 }
    }
} else { Add-Finding INFO "assets" "asset scan skipped by flag" }

# Nmap
if (-not $SkipNmap) {
    Write-Section "Running scoped Nmap web/header scan"
    if (-not $NmapOk) { "SKIPPED: nmap not found." | Set-Content -Path $NmapConsole -Encoding utf8; Add-Finding WARN "nmap" "nmap command not found" }
    else {
        $NmapArgs1 = @("-Pn", "-sT", "-T2", "--reason", "-p", $Ports, $HostIp, "-oN", $NmapServices)
        Invoke-NativeToFile -Exe "nmap" -Args $NmapArgs1 -OutputFile $NmapConsole | Out-Null
        $HttpScripts = "http-title,http-headers,http-security-headers,http-server-header,http-methods,http-cors,http-cookie-flags,ssl-cert"
        if ($DeepTls) { $HttpScripts = "$HttpScripts,ssl-enum-ciphers" }
        $NmapArgs2 = @("-Pn", "-sV", "--version-light", "-T2", "--reason", "--script", $HttpScripts, "-p", $Ports, $HostIp, "-oN", $NmapHttp)
        Invoke-NativeToFile -Exe "nmap" -Args $NmapArgs2 -OutputFile $NmapHttpConsole | Out-Null
    }
} else { "SKIPPED by -SkipNmap." | Set-Content -Path $NmapConsole -Encoding utf8; Add-Finding INFO "nmap" "skipped by flag" }

# ZAP baseline
if (-not $SkipZap) {
    Write-Section "Running ZAP baseline/passive scan"
    if (-not $DockerOk) { "SKIPPED: Docker is not available or Docker Desktop is not running." | Set-Content -Path $ZapConsole -Encoding utf8; Add-Finding WARN "zap" "ZAP skipped because Docker is unavailable" }
    elseif (-not $CurlOk) { "SKIPPED: curl not available; target reachability was not confirmed." | Set-Content -Path $ZapConsole -Encoding utf8; Add-Finding WARN "zap" "ZAP skipped because curl unavailable" }
    else {
        if (-not $SkipZapPull) { Invoke-NativeToFile -Exe "docker" -Args @("pull", "ghcr.io/zaproxy/zaproxy:stable") -OutputFile $ZapConsole | Out-Null } else { "SKIPPED docker pull because -SkipZapPull was used." | Set-Content -Path $ZapConsole -Encoding utf8 }
        $ZapArgs = @("run", "--rm", "-v", "${BaseDir}:/zap/wrk/:rw", "ghcr.io/zaproxy/zaproxy:stable", "zap-baseline.py", "-t", $ZapTargetUrl, "-m", "$ZapSpiderMinutes", "-r", $ZapHtml, "-J", $ZapJson, "-w", $ZapMd, "-I")
        $ZapDisplayArgs = $ZapArgs.Clone()
        if ($AuthEnabled -and -not [string]::IsNullOrWhiteSpace($script:AuthHeaderResolved)) {
            $ZapZ = "-config replacer.full_list(0).description=openfdd-basic-auth -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement=$($script:AuthHeaderResolved)"
            $ZapZMasked = $ZapZ.Replace($script:AuthHeaderResolved, "Basic ***MASKED***")
            $ZapArgs += @("-z", $ZapZ)
            $ZapDisplayArgs += @("-z", $ZapZMasked)
            Add-Finding INFO "zap" "Basic auth header will be injected into ZAP requests"
        }
        Invoke-NativeToFile -Exe "docker" -Args $ZapArgs -DisplayArgs $ZapDisplayArgs -OutputFile $ZapConsole -Append | Out-Null
    }
} else { "SKIPPED by -SkipZap." | Set-Content -Path $ZapConsole -Encoding utf8; Add-Finding INFO "zap" "skipped by flag" }

# Summaries
Write-Section "Writing summaries"
$ExpectedOpenSet = @{}
foreach ($P in ($ExpectedOpenPorts -split ',')) { $T=$P.Trim(); if ($T -match '^\d+$') { $ExpectedOpenSet[[int]$T]=$true } }
$ExpectedClosedSet = @{}
foreach ($P in ($ExpectedClosedPorts -split ',')) { $T=$P.Trim(); if ($T -match '^\d+$') { $ExpectedClosedSet[[int]$T]=$true } }

@"
Nmap findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $HostIp
Ports checked: $Ports
Expected open ports: $ExpectedOpenPorts
Expected closed ports: $ExpectedClosedPorts

Expected for Caddy-fronted Open-FDD:
- 80/443 only if intentionally fronting the app
- 8765 bridge closed from LAN when Caddy fronts it
- 8090 mcp-rag internal/local only
- 5173 Vite dev server closed
- 8000/8080 dev/API ports closed unless intentionally exposed
"@ | Set-Content -Path $NmapFindings -Encoding utf8

$PortRows = Get-NmapPortStates -NmapFile $NmapServices
if ($PortRows.Count -gt 0) {
    "=== Port state lines ===" | Add-Content -Path $NmapFindings -Encoding utf8
    $PortRows | ForEach-Object { $_.Line } | Add-Content -Path $NmapFindings -Encoding utf8
    foreach ($Row in $PortRows) {
        if ($Row.State -eq "open") {
            if ($ExpectedClosedSet.ContainsKey($Row.Port)) { Add-Finding FAIL "nmap" "expected-closed port $($Row.Port) is open: $($Row.Line)" }
            elseif (-not $ExpectedOpenSet.ContainsKey($Row.Port)) { Add-Finding WARN "nmap" "unexpected open port $($Row.Port): $($Row.Line)" }
            else { Add-Finding PASS "nmap" "expected open port $($Row.Port): $($Row.Service)" }
        }
    }
} else { Add-Content -Path $NmapFindings -Value "Nmap services file not found or Nmap skipped." -Encoding utf8 }

if (Test-Path $NmapHttp) {
    "`n=== HTTP/header/TLS details of interest ===" | Add-Content -Path $NmapFindings -Encoding utf8
    Select-String -Path $NmapHttp -Pattern 'http-|Content-Security-Policy|X-Frame|X-Content|Referrer|Permissions-Policy|Strict-Transport|Server:|ssl-cert|ssl-enum|open|filtered|Allow:|cookie' -CaseSensitive:$false | ForEach-Object { $_.Line } | Add-Content -Path $NmapFindings -Encoding utf8
}

@"
ZAP findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Target URL from host: $TargetUrl
Target URL from ZAP container: $ZapTargetUrl
Auth injected: $AuthEnabled

Notes:
- This uses ZAP baseline/passive scan.
- It is not ZAP full/active scan.
"@ | Set-Content -Path $ZapFindings -Encoding utf8

$ZapAlerts = Get-ZapAlertsFromJson -JsonPath $ZapJsonPath
if ($ZapAlerts.Count -gt 0) {
    "=== ZAP alerts by risk/confidence ===" | Add-Content -Path $ZapFindings -Encoding utf8
    $ZapAlerts | Group-Object riskdesc | Sort-Object Count -Descending | ForEach-Object { "{0,4}  {1}" -f $_.Count, $_.Name } | Add-Content -Path $ZapFindings -Encoding utf8
    "`n=== ZAP alert names ===" | Add-Content -Path $ZapFindings -Encoding utf8
    $ZapAlerts | Sort-Object riskdesc, name | ForEach-Object {
        "[$($_.riskdesc)] $($_.name)"
        if ($_.riskdesc -match '^High') { Add-Finding FAIL "zap" "High alert: $($_.name)" }
        elseif ($_.riskdesc -match '^Medium') { if ($MediumIsFail) { Add-Finding FAIL "zap" "Medium alert: $($_.name)" } else { Add-Finding WARN "zap" "Medium alert: $($_.name)" } }
    } | Add-Content -Path $ZapFindings -Encoding utf8
} elseif (Test-Path $ZapMdPath) { "ZAP report exists and JSON parsed with no alerts." | Add-Content -Path $ZapFindings -Encoding utf8; Add-Finding PASS "zap" "no JSON alerts parsed" }
else { "No ZAP report was produced. Review: $ZapConsole" | Add-Content -Path $ZapFindings -Encoding utf8 }

if (Test-Path $ZapMdPath) {
    "`n=== ZAP markdown snippets ===" | Add-Content -Path $ZapFindings -Encoding utf8
    Select-String -Path $ZapMdPath -Pattern 'WARN|FAIL|High|Medium|Low|Informational|Missing|Content Security|CSP|X-Frame|CORS|Cookie|Server|Referrer|Header|Strict-Transport|Private IP' -CaseSensitive:$false | Select-Object -First 200 | ForEach-Object { $_.Line } | Add-Content -Path $ZapFindings -Encoding utf8
}

$script:Findings | Export-Csv -Path $GateCsv -NoTypeInformation -Encoding utf8
$FailCount = @($script:Findings | Where-Object { $_.Severity -eq "FAIL" }).Count
$WarnCount = @($script:Findings | Where-Object { $_.Severity -eq "WARN" }).Count
$PassCount = @($script:Findings | Where-Object { $_.Severity -eq "PASS" }).Count

@"
Open-FDD web app quick findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Gate result:
- PASS checks: $PassCount
- WARN checks: $WarnCount
- FAIL checks: $FailCount

Report folder:
$BaseDir

Read these first:
- 98-security-gate-results.csv
- 04-route-auth-cors-tests.txt
- 05-header-cache-summary.txt
- 06-asset-leak-summary.txt
- 30-nmap-findings-summary.txt
- 31-zap-findings-summary.txt
- 99-review-checklist.txt

Nmap port exposure summary:
"@ | Set-Content -Path $QuickSummary -Encoding utf8
if ($PortRows.Count -gt 0) { $PortRows | ForEach-Object { $_.Line } | Add-Content -Path $QuickSummary -Encoding utf8 } else { "Nmap did not produce a services report." | Add-Content -Path $QuickSummary -Encoding utf8 }
"`nZAP alert summary:" | Add-Content -Path $QuickSummary -Encoding utf8
if ($ZapAlerts.Count -gt 0) { $ZapAlerts | Group-Object riskdesc | Sort-Object Count -Descending | ForEach-Object { "{0,4}  {1}" -f $_.Count, $_.Name } | Add-Content -Path $QuickSummary -Encoding utf8 } else { "No ZAP alerts parsed or ZAP skipped." | Add-Content -Path $QuickSummary -Encoding utf8 }
"`nFAIL/WARN detail:" | Add-Content -Path $QuickSummary -Encoding utf8
$script:Findings | Where-Object { $_.Severity -in @("FAIL","WARN") } | ForEach-Object { "[$($_.Severity)] $($_.Area): $($_.Message)" } | Add-Content -Path $QuickSummary -Encoding utf8

@"
Open-FDD web app security review checklist

Use this report as a web-app smoke/release gate, not as a complete penetration test.

PASS expectations:
[ ] No ZAP High alerts.
[ ] No anonymous protected API/data route returns 2xx.
[ ] Fake hostile Origin is not reflected/allowed by CORS.
[ ] Frontend bundle does not contain hardcoded 192.168.x.x / 10.x.x.x / 172.16-31.x.x addresses.
[ ] Frontend bundle does not contain absolute ws:// app endpoints.
[ ] Expected internal/dev ports are not open from this Windows machine.
[ ] API/auth/data routes are not cacheable.
[ ] CSP/header warnings are triaged or documented.

Not covered here:
[ ] Server-side Docker binding review.
[ ] Dependency/container CVE scan.
[ ] Secret scan of repo/history.
[ ] Role-level authorization tests inside a real browser session.
"@ | Set-Content -Path $Checklist -Encoding utf8

@"
Cursor/Codex prompt for fixing Open-FDD web app security gate findings

Review the generated Open-FDD web app security report folder and fix the gate findings.

Read first:
- 90-quick-findings-summary.txt
- 98-security-gate-results.csv
- 04-route-auth-cors-tests.txt
- 05-header-cache-summary.txt
- 06-asset-leak-summary.txt
- 30-nmap-findings-summary.txt
- 31-zap-findings-summary.txt

Priorities:
1. Fix any protected API/data route that returns 2xx anonymously.
2. Fix any CORS behavior that allows or reflects https://evil.example.
3. Remove hardcoded private IPs, localhost API URLs, http:// app URLs, and ws:// URLs from built frontend assets. Prefer relative URLs.
4. Tighten CSP. Remove style-src unsafe-inline if the UI still works; otherwise document the bench exception.
5. Add no-store or equivalent Cache-Control on auth/API/data responses.
6. Keep 8765, 8090, 5173, 8000, and 8080 closed from the web-app client network unless intentionally exposed.
7. Rebuild the production UI bundle and rerun this PowerShell script.

Do not commit secrets or *.env.local files.
Do not add broad subnet scans, brute force checks, exploit scripts, or active attack scans against the BAS/OT-connected bench.
"@ | Set-Content -Path $FixPrompt -Encoding utf8

Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkGray
if ($FailCount -gt 0) { Write-Host "SECURITY GATE: FAIL ($FailCount fail, $WarnCount warn)" -ForegroundColor Red }
elseif ($WarnCount -gt 0) { Write-Host "SECURITY GATE: WARN ($WarnCount warn)" -ForegroundColor Yellow }
else { Write-Host "SECURITY GATE: PASS" -ForegroundColor Green }
Write-Host "Report: $BaseDir"
Write-Host "Start here: $QuickSummary"
Write-Host "============================================================" -ForegroundColor DarkGray

if ($ExitNonZeroOnFail -and $FailCount -gt 0) { exit 2 }
