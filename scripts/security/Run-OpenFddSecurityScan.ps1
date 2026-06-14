<#
Run-OpenFddSecurityScan.ps1

Safe local Open-FDD security smoke test for a single bench host.

What it does:
- Deletes/recreates one fixed report folder: .\openfdd-security-report
- Runs OWASP ZAP baseline scan against one web target URL
- Runs scoped Nmap service/header scans against one host IP
- Writes separate text files for Nmap and ZAP findings
- Does NOT open Notepad or browser windows

Requirements:
- Docker Desktop running for ZAP
- Nmap installed and available as "nmap"
- PowerShell on Windows

Normal Open-FDD/Caddy target:
  .\Run-OpenFddSecurityScan.ps1

Custom target:
  .\Run-OpenFddSecurityScan.ps1 -HostIp "192.168.204.18" -TargetUrl "http://192.168.204.18"

If the bridge is only reachable through an SSH tunnel:
  ssh -L 8765:127.0.0.1:8765 bbartling@192.168.204.18
  .\Run-OpenFddSecurityScan.ps1 -HostIp "192.168.204.18" -TargetUrl "http://127.0.0.1:8765"

This script runs ZAP baseline only, not ZAP full/active scan.
Do not run broad or aggressive scans against live OT/BAS networks or controllers.

See scripts/security/README.md and docs/security/zap-baseline.md.
#>

param(
    [string]$HostIp = "192.168.204.18",

    # Default to Caddy/LAN front door, not bridge direct port 8765.
    [string]$TargetUrl = "http://192.168.204.18",

    [string]$Ports = "80,443,8765,8000,8080,5173,8090",

    # Fixed folder. It is deleted/recreated on every run unless -KeepExisting is used.
    [string]$ReportDir = "openfdd-security-report",

    [switch]$SkipZap,
    [switch]$SkipZapPull,
    [switch]$SkipNmap,
    [switch]$KeepExisting,

    # Optional path to auth.env.local (integrator creds for authenticated probe — never commit).
    [string]$AuthEnvFile = "",

    # Fail gate on ZAP Medium alerts (default: High/missing report/nonzero fatal exit only).
    [switch]$StrictZap
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

function Quote-NativeArg {
    param([string]$Arg)

    if ($null -eq $Arg) {
        return '""'
    }

    if ($Arg -notmatch '[\s"]') {
        return $Arg
    }

    $Escaped = $Arg.Replace('"', '\"')
    return '"' + $Escaped + '"'
}

function Format-LoggedCommand {
    param(
        [string]$Exe,
        [string[]]$Args
    )

    $parts = @($Exe)
    $skipNext = $false
    for ($i = 0; $i -lt $Args.Count; $i++) {
        if ($skipNext) {
            $skipNext = $false
            $parts += "<redacted>"
            continue
        }
        $arg = $Args[$i]
        if ($arg -eq "--env-file" -or $arg -eq "-env-file") {
            $parts += $arg
            $skipNext = $true
            continue
        }
        if ($arg -match '(?i)Bearer\s|Basic\s|password|OFDD_INTEGRATOR|token=') {
            $parts += "<redacted>"
            continue
        }
        $parts += $arg
    }
    return ($parts -join " ")
}

function Invoke-NativeToFile {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$OutputFile,
        [switch]$Append
    )

    $TempOut = [System.IO.Path]::GetTempFileName()
    $TempErr = [System.IO.Path]::GetTempFileName()

    $Header = @(
        "> $(Format-LoggedCommand -Exe $Exe -Args $Args)"
        "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        ""
    )

    if ($Append) {
        Add-Content -Path $OutputFile -Value $Header -Encoding utf8
    } else {
        Set-Content -Path $OutputFile -Value $Header -Encoding utf8
    }

    try {
        $Process = Start-Process `
            -FilePath $Exe `
            -ArgumentList $Args `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $TempOut `
            -RedirectStandardError $TempErr

        $StdOut = ""
        $StdErr = ""

        if (Test-Path $TempOut) {
            $StdOut = Get-Content -Raw -Path $TempOut -ErrorAction SilentlyContinue
        }

        if (Test-Path $TempErr) {
            $StdErr = Get-Content -Raw -Path $TempErr -ErrorAction SilentlyContinue
        }

        Add-Content -Path $OutputFile -Value "ExitCode: $($Process.ExitCode)" -Encoding utf8

        if ($StdOut) {
            Add-Content -Path $OutputFile -Value "`n--- STDOUT ---" -Encoding utf8
            Add-Content -Path $OutputFile -Value $StdOut -Encoding utf8
        }

        if ($StdErr) {
            Add-Content -Path $OutputFile -Value "`n--- STDERR ---" -Encoding utf8
            Add-Content -Path $OutputFile -Value $StdErr -Encoding utf8
        }

        Add-Content -Path $OutputFile -Value "`nFinished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding utf8
        return $Process.ExitCode
    }
    catch {
        Add-Content -Path $OutputFile -Value "ERROR: $($_.Exception.Message)" -Encoding utf8
        return 9999
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $TempOut, $TempErr
    }
}

function Test-CommandAvailable {
    param([string]$Name)

    $Cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return ($null -ne $Cmd)
}

function Get-FirstLines {
    param(
        [string]$Path,
        [int]$Count = 80
    )

    if (Test-Path $Path) {
        Get-Content -Path $Path -TotalCount $Count -ErrorAction SilentlyContinue
    }
}

function Test-SafeReportDir {
    param([string]$Dir)
    if ([string]::IsNullOrWhiteSpace($Dir)) { return $false }
    $leaf = [System.IO.Path]::GetFileName($Dir.TrimEnd('\', '/'))
    if ($leaf -ne "openfdd-security-report") { return $false }
    try {
        $resolved = [System.IO.Path]::GetFullPath($Dir)
    } catch {
        return $false
    }
    if ($resolved -match '^[A-Za-z]:\\$' -or $resolved -eq '/') { return $false }
    return $true
}

$BaseDir = if ([System.IO.Path]::IsPathRooted($ReportDir)) {
    $ReportDir
} else {
    Join-Path (Get-Location).Path $ReportDir
}

if (-not (Test-SafeReportDir -Dir $BaseDir)) {
    Write-Error "Report directory must be named openfdd-security-report (got: $ReportDir)"
    exit 1
}

if ((Test-Path $BaseDir) -and (-not $KeepExisting)) {
    Remove-Item -LiteralPath $BaseDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $BaseDir | Out-Null

$RunInfo = Join-Path $BaseDir "00-run-info.txt"
$ReachabilityFile = Join-Path $BaseDir "01-web-reachability-and-headers.txt"
$WebHeaders = Join-Path $BaseDir "02-web-response-headers.txt"
$WebBodySample = Join-Path $BaseDir "03-web-body-sample.html"

$NmapConsole = Join-Path $BaseDir "10-nmap-console-output.txt"
$NmapServices = Join-Path $BaseDir "11-nmap-openfdd-services.txt"
$NmapServicesXml = Join-Path $BaseDir "11-nmap-openfdd-services.xml"
$NmapServicesGrep = Join-Path $BaseDir "11-nmap-openfdd-services.gnmap"
$NmapHttpConsole = Join-Path $BaseDir "12-nmap-http-console-output.txt"
$NmapHttp = Join-Path $BaseDir "13-nmap-openfdd-http-details.txt"
$NmapFindings = Join-Path $BaseDir "30-nmap-findings-summary.txt"

$ZapConsole = Join-Path $BaseDir "20-zap-console-output.txt"
$ZapHtml = "21-zap-openfdd-baseline.html"
$ZapJson = "21-zap-openfdd-baseline.json"
$ZapMd = "21-zap-openfdd-baseline.md"
$ZapHtmlPath = Join-Path $BaseDir $ZapHtml
$ZapJsonPath = Join-Path $BaseDir $ZapJson
$ZapMdPath = Join-Path $BaseDir $ZapMd
$ZapFindings = Join-Path $BaseDir "31-zap-findings-summary.txt"
$ZapReplacerConfig = Join-Path $BaseDir "32-zap-replacer.prop"
$ZapAuthEnvHost = Join-Path $BaseDir "33-zap-docker-auth.env"

$ZapExitCode = $null
$ZapAuthInjected = $false
$ZapSkipped = $false

function Read-AuthFromEnvFile {
    param([string]$Path)

    $user = $null
    $pass = $null
    if (-not $Path -or -not (Test-Path $Path)) {
        return @{ User = $user; Password = $pass; Loaded = $false }
    }
    foreach ($line in Get-Content -Path $Path -ErrorAction SilentlyContinue) {
        $t = $line.Trim()
        if ($t -match '^\s*#' -or -not $t.Contains('=')) { continue }
        $parts = $t.Split('=', 2)
        $key = $parts[0].Trim()
        $val = $parts[1].Trim().Trim("'").Trim('"')
        if ($key -eq 'OFDD_INTEGRATOR_USER' -and $val) { $user = $val }
        if ($key -eq 'OFDD_INTEGRATOR_PASSWORD' -and $val) { $pass = $val }
    }
    $loaded = [bool]($user -and $pass)
    return @{ User = $user; Password = $pass; Loaded = $loaded }
}

function Test-ProductionAssetLeak {
    param(
        [string]$HtmlPath,
        [string]$BaseUrl
    )

    $issues = [System.Collections.Generic.List[string]]::new()
    $banned = @(
        '192.168.204.11',
        '192.168.204.18',
        'Bench Station 9065',
        'OPENFDD_NIAGARA_ADMIN_PASSWORD',
        'BENS$20BENCHTEST$20BOX'
    )
    $privateIp = [regex]'192\.168\.\d{1,3}\.\d{1,3}'

    $scriptUrls = @()
    if (Test-Path $HtmlPath) {
        $html = Get-Content -Raw -Path $HtmlPath -ErrorAction SilentlyContinue
        if ($html) {
            foreach ($literal in $banned) {
                if ($html.Contains($literal)) {
                    $issues.Add("HTML contains banned literal: $literal")
                }
            }
            $scriptUrls = [regex]::Matches($html, 'src="(/assets/[^"]+\.js)"') |
                ForEach-Object { $_.Groups[1].Value }
        }
    }

    foreach ($rel in $scriptUrls) {
        $jsUrl = if ($BaseUrl.EndsWith('/')) { $BaseUrl.TrimEnd('/') + $rel } else { $BaseUrl + $rel }
        $tmpJs = Join-Path $env:TEMP ("ofdd-asset-" + [guid]::NewGuid().ToString() + ".js")
        try {
            & curl.exe -k -sS -L --max-time 30 -o $tmpJs $jsUrl 2>$null
            if (Test-Path $tmpJs) {
                $js = Get-Content -Raw -Path $tmpJs -ErrorAction SilentlyContinue
                if ($js) {
                    foreach ($literal in $banned) {
                        if ($js.Contains($literal)) {
                            $issues.Add("JS $rel contains banned literal: $literal")
                        }
                    }
                    foreach ($m in $privateIp.Matches($js)) {
                        $issues.Add("JS $rel contains private IP: $($m.Value)")
                    }
                }
            }
        } finally {
            Remove-Item -Force -ErrorAction SilentlyContinue $tmpJs
        }
    }

    return $issues
}

function Get-IntegratorToken {
    param(
        [string]$BaseUrl,
        [string]$User,
        [string]$Password
    )

    if (-not $User -or -not $Password) {
        return $null
    }
    $loginUrl = ($BaseUrl.TrimEnd('/') + '/api/auth/login')
    $bodyFile = [System.IO.Path]::GetTempFileName()
    $respFile = [System.IO.Path]::GetTempFileName()
    try {
        $payload = @{ username = $User; password = $Password } | ConvertTo-Json -Compress
        Set-Content -Path $bodyFile -Value $payload -Encoding utf8 -NoNewline
        & curl.exe -k -sS -X POST -H "Content-Type: application/json" --data-binary "@$bodyFile" -o $respFile --max-time 20 $loginUrl 2>$null
        $resp = Get-Content -Raw -Path $respFile -ErrorAction SilentlyContinue
        if ($resp -match '"token"\s*:\s*"([^"]+)"') {
            return $Matches[1]
        }
        return $null
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $bodyFile, $respFile
    }
}

function Write-ZapReplacerConfig {
    param(
        [string]$Path,
        [string]$BearerToken
    )

    $replacement = "Bearer $BearerToken"
    @(
        "replacer.full_list(0).description=ofdd-bearer"
        "replacer.full_list(0).enabled=true"
        "replacer.full_list(0).matchtype=REQ_HEADER"
        "replacer.full_list(0).matchstr=Authorization"
        "replacer.full_list(0).regex=false"
        "replacer.full_list(0).replacement=$replacement"
    ) | Set-Content -Path $Path -Encoding ascii
}

function Get-ZapAlertCounts {
    param([string]$JsonPath)

    $counts = @{ High = 0; Medium = 0; Low = 0; Informational = 0 }
    if (-not (Test-Path $JsonPath)) {
        return $counts
    }
    try {
        $raw = Get-Content -Raw -Path $JsonPath -ErrorAction Stop | ConvertFrom-Json
    } catch {
        return $counts
    }
    $alerts = @()
    if ($raw.PSObject.Properties.Name -contains "site") {
        foreach ($site in @($raw.site)) {
            if ($site.alerts) { $alerts += $site.alerts }
        }
    } elseif ($raw.PSObject.Properties.Name -contains "alerts") {
        $alerts += $raw.alerts
    }
    foreach ($alert in $alerts) {
        $risk = [string]($alert.riskcode)
        if (-not $risk -and $alert.risk) { $risk = [string]$alert.risk }
        switch ($risk) {
            "3" { $counts.High++ }
            "2" { $counts.Medium++ }
            "1" { $counts.Low++ }
            default {
                $name = [string]$alert.riskdesc
                if ($name -match '(?i)high') { $counts.High++ }
                elseif ($name -match '(?i)medium') { $counts.Medium++ }
                elseif ($name -match '(?i)low') { $counts.Low++ }
                else { $counts.Informational++ }
            }
        }
    }
    return $counts
}

function Test-AnonymousRoute {
    param(
        [string]$BaseUrl,
        [string]$Path,
        [int[]]$ExpectedStatus
    )

    $url = $BaseUrl.TrimEnd('/') + $Path
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        $codeText = & curl.exe -k -sS -o $tmp -w "%{http_code}" --max-time 15 $url 2>$null
        $code = [int]$codeText
        $ok = $ExpectedStatus -contains $code
        return @{ Ok = $ok; Status = $code; Path = $Path }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tmp
    }
}

function Test-ProtectedRoutesAnonymous {
    param([string]$BaseUrl)

    $protected = @(
        "/api/auth/me",
        "/api/fdd/results",
        "/health/stack",
        "/api/host/stats",
        "/api/model/health",
        "/api/bacnet/driver/tree"
    )
    $public = @(
        "/health",
        "/api/auth/status"
    )
    $issues = [System.Collections.Generic.List[string]]::new()
    foreach ($path in $protected) {
        $r = Test-AnonymousRoute -BaseUrl $BaseUrl -Path $path -ExpectedStatus @(401, 403)
        if (-not $r.Ok) {
            $issues.Add("Anonymous $($r.Path) returned $($r.Status) (expected 401/403)")
        }
    }
    foreach ($path in $public) {
        $r = Test-AnonymousRoute -BaseUrl $BaseUrl -Path $path -ExpectedStatus @(200)
        if (-not $r.Ok) {
            $issues.Add("Public $($r.Path) returned $($r.Status) (expected 200)")
        }
    }
    return $issues
}

function Test-HostileCorsRejected {
    param([string]$BaseUrl)

    $url = $BaseUrl.TrimEnd('/') + '/api/auth/status'
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & curl.exe -k -sS -D $tmp -o NUL -H "Origin: https://evil.example.test" --max-time 15 $url 2>$null
        if (-not (Test-Path $tmp)) {
            return @{ Ok = $false; Detail = "no response headers" }
        }
        $headers = Get-Content -Path $tmp -ErrorAction SilentlyContinue
        $acao = ($headers | Where-Object { $_ -match '^Access-Control-Allow-Origin:\s*(.+)$' } | Select-Object -First 1)
        if ($acao -and $acao -match 'evil\.example\.test') {
            return @{ Ok = $false; Detail = "hostile origin reflected in ACAO" }
        }
        return @{ Ok = $true; Detail = "hostile origin not allowed" }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tmp
    }
}

function Invoke-AuthProbe {
    param(
        [string]$BaseUrl,
        [string]$User,
        [string]$Password
    )

    if (-not $User -or -not $Password) {
        return @{ Ok = $false; Detail = "credentials not provided" }
    }
    $token = Get-IntegratorToken -BaseUrl $BaseUrl -User $User -Password $Password
    if ($token) {
        return @{ Ok = $true; Detail = "integrator login returned token" }
    }
    return @{ Ok = $false; Detail = "login did not return token (check OFDD_INTEGRATOR_USER / OFDD_INTEGRATOR_PASSWORD)" }
}

$QuickSummary = Join-Path $BaseDir "90-quick-findings-summary.txt"
$Checklist = Join-Path $BaseDir "99-review-checklist.txt"
$GateReport = Join-Path $BaseDir "40-release-gate-summary.txt"

$integratorUser = $env:OFDD_INTEGRATOR_USER
$integratorPass = $env:OFDD_INTEGRATOR_PASSWORD
$authLoaded = $false
if ($AuthEnvFile) {
    $parsedAuthEarly = Read-AuthFromEnvFile -Path $AuthEnvFile
    if ($parsedAuthEarly.Loaded) {
        $integratorUser = $parsedAuthEarly.User
        $integratorPass = $parsedAuthEarly.Password
        $authLoaded = $true
    }
} elseif ($integratorUser -and $integratorPass) {
    $authLoaded = $true
}

Write-Section "Open-FDD local security scan"
Write-Host "Report folder: $BaseDir"
Write-Host "Host IP:       $HostIp"
Write-Host "Target URL:    $TargetUrl"
Write-Host "Ports:         $Ports"

@"
Open-FDD local security scan
Run time:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host IP:     $HostIp
Target URL:  $TargetUrl
Ports:       $Ports
Machine:     $env:COMPUTERNAME
User:        $env:USERNAME

Notes:
- ZAP baseline is passive/baseline web testing.
- Nmap scan is scoped to one host only: $HostIp
- This script deletes/recreates this report folder on each run unless -KeepExisting is used.
- Do not run broad active/vulnerability scans on live OT/BAS networks without approval.
"@ | Set-Content -Path $RunInfo -Encoding utf8

Write-Section "Checking tools"

$DockerOk = $false
$NmapOk = $false

if (Test-CommandAvailable "docker") {
    Invoke-NativeToFile -Exe "docker" -Args @("--version") -OutputFile $RunInfo -Append | Out-Null
    $DockerInfoExit = Invoke-NativeToFile -Exe "docker" -Args @("info") -OutputFile (Join-Path $BaseDir "00-docker-info.txt")
    if ($DockerInfoExit -eq 0) {
        $DockerOk = $true
        Write-Host "Docker is available."
    } else {
        Write-Host "Docker command exists, but Docker Desktop may not be running."
        Add-Content -Path $RunInfo -Value "WARNING: Docker command exists, but docker info failed." -Encoding utf8
    }
} else {
    Write-Host "Docker not found."
    Add-Content -Path $RunInfo -Value "WARNING: Docker not found." -Encoding utf8
}

if (Test-CommandAvailable "nmap") {
    Invoke-NativeToFile -Exe "nmap" -Args @("--version") -OutputFile $RunInfo -Append | Out-Null
    $NmapOk = $true
    Write-Host "Nmap is available."
} else {
    Write-Host "Nmap not found."
    Add-Content -Path $RunInfo -Value "WARNING: Nmap not found. Install with: winget install -e --id Insecure.Nmap" -Encoding utf8
}

Write-Section "Testing web target"

# Use GET instead of HEAD because some FastAPI/Caddy routes return 405 for HEAD.
$CurlExit = Invoke-NativeToFile `
    -Exe "curl.exe" `
    -Args @("-k", "-sS", "-L", "--max-time", "20", "-D", $WebHeaders, "-o", $WebBodySample, $TargetUrl) `
    -OutputFile $ReachabilityFile

$TargetReachable = $false
if ($CurlExit -eq 0 -and (Test-Path $WebHeaders)) {
    $TargetReachable = $true
    Write-Host "Target web URL responded."
} else {
    Write-Host "Target web URL did not respond cleanly. ZAP will be skipped unless you force/fix the TargetUrl."
}

"`n=== Response headers ===" | Add-Content -Path $ReachabilityFile -Encoding utf8
Get-FirstLines -Path $WebHeaders -Count 120 | Add-Content -Path $ReachabilityFile -Encoding utf8

"`n=== Body sample first lines ===" | Add-Content -Path $ReachabilityFile -Encoding utf8
Get-FirstLines -Path $WebBodySample -Count 80 | Add-Content -Path $ReachabilityFile -Encoding utf8

if (-not $SkipZap) {
    Write-Section "Running OWASP ZAP baseline"

    if (-not $DockerOk) {
        "SKIPPED: Docker is not available or Docker Desktop is not running." | Set-Content -Path $ZapConsole -Encoding utf8
        Write-Host "Skipping ZAP because Docker is unavailable."
        $ZapSkipped = $true
    }
    elseif (-not $TargetReachable) {
        @"
SKIPPED: Target URL did not respond to curl GET.

TargetUrl: $TargetUrl

Common fixes:
- If Open-FDD is behind Caddy, use:  http://$HostIp
- If using Caddy TLS, use:          https://$HostIp
- If bridge is localhost-only on the VM, open an SSH tunnel:
    ssh -L 8765:127.0.0.1:8765 bbartling@$HostIp
    .\Run-OpenFddSecurityScan.ps1 -HostIp "$HostIp" -TargetUrl "http://127.0.0.1:8765"

"@ | Set-Content -Path $ZapConsole -Encoding utf8
        Write-Host "Skipping ZAP because target is not reachable."
        $ZapSkipped = $true
    }
    else {
        if (-not $SkipZapPull) {
            Write-Host "Pulling latest stable ZAP image..."
            Invoke-NativeToFile -Exe "docker" -Args @("pull", "ghcr.io/zaproxy/zaproxy:stable") -OutputFile $ZapConsole | Out-Null
        } else {
            "SKIPPED docker pull because -SkipZapPull was used." | Set-Content -Path $ZapConsole -Encoding utf8
        }

        Write-Host "Running ZAP baseline. Output goes to report folder."
        $zapToken = $null
        if ($authLoaded) {
            $zapToken = Get-IntegratorToken -BaseUrl $TargetUrl -User $integratorUser -Password $integratorPass
            if ($zapToken) {
                Write-ZapReplacerConfig -Path $ZapReplacerConfig -BearerToken $zapToken
                "ZAP_AUTH_HEADER_VALUE=Bearer $zapToken" | Set-Content -Path $ZapAuthEnvHost -Encoding ascii -NoNewline
                $ZapAuthInjected = $true
                Write-Host "ZAP auth: Bearer token loaded (not logged)."
            } else {
                Write-Host "WARN: auth.env loaded but integrator login failed — running unauthenticated ZAP."
            }
        }

        $ZapArgs = @(
            "run", "--rm",
            "-v", "${BaseDir}:/zap/wrk/:rw",
            "-t", "ghcr.io/zaproxy/zaproxy:stable",
            "zap-baseline.py",
            "-t", $TargetUrl,
            "-r", $ZapHtml,
            "-J", $ZapJson,
            "-w", $ZapMd,
            "-I"
        )
        if ($ZapAuthInjected) {
            $ZapArgs = @(
                "run", "--rm",
                "--env-file", $ZapAuthEnvHost,
                "-v", "${BaseDir}:/zap/wrk/:rw",
                "-t", "ghcr.io/zaproxy/zaproxy:stable",
                "zap-baseline.py",
                "-t", $TargetUrl,
                "-r", $ZapHtml,
                "-J", $ZapJson,
                "-w", $ZapMd,
                "-I",
                "-z", "-configfile /zap/wrk/32-zap-replacer.prop"
            )
        }

        $ZapExitCode = Invoke-NativeToFile -Exe "docker" -Args $ZapArgs -OutputFile $ZapConsole -Append
        Remove-Item -Force -ErrorAction SilentlyContinue $ZapAuthEnvHost
    }
} else {
    "SKIPPED by -SkipZap." | Set-Content -Path $ZapConsole -Encoding utf8
    $ZapSkipped = $true
}

if (-not $SkipNmap) {
    Write-Section "Running Nmap scans"

    if (-not $NmapOk) {
        "SKIPPED: Nmap not available. Install with: winget install -e --id Insecure.Nmap" | Set-Content -Path $NmapConsole -Encoding utf8
        Write-Host "Skipping Nmap because it is not installed."
    } else {
        Write-Host "Running Nmap service/version scan."
        $NmapArgs1 = @(
            "-Pn", "-sV", "-T2",
            "-p", $Ports,
            $HostIp,
            "-oN", $NmapServices,
            "-oX", $NmapServicesXml,
            "-oG", $NmapServicesGrep
        )
        Invoke-NativeToFile -Exe "nmap" -Args $NmapArgs1 -OutputFile $NmapConsole | Out-Null

        Write-Host "Running Nmap HTTP/header/TLS helper scripts."
        $NmapArgs2 = @(
            "-Pn", "-sV", "-T2",
            "--script", "http-title,http-headers,ssl-cert",
            "-p", $Ports,
            $HostIp,
            "-oN", $NmapHttp
        )
        Invoke-NativeToFile -Exe "nmap" -Args $NmapArgs2 -OutputFile $NmapHttpConsole | Out-Null
    }
} else {
    "SKIPPED by -SkipNmap." | Set-Content -Path $NmapConsole -Encoding utf8
}

Write-Section "Writing summaries"

@"
Nmap findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $HostIp
Ports checked: $Ports

Interpretation:
- open    = service accepted a TCP connection
- closed  = host replied but no service is listening
- filtered = firewall or filtering prevented a clear answer

Expected for a Caddy-fronted Open-FDD bench:
- 80 open if HTTP Caddy mode is enabled
- 443 open if TLS Caddy mode is enabled
- 8765 closed from LAN if bridge is only exposed behind Caddy
- 8090 closed/filtered from LAN if mcp-rag is internal-only
- 5173 closed because Vite dev server should not be exposed

"@ | Set-Content -Path $NmapFindings -Encoding utf8

if (Test-Path $NmapServices) {
    "`n=== Port state lines ===" | Add-Content -Path $NmapFindings -Encoding utf8
    Select-String -Path $NmapServices -Pattern '^\d+/tcp\s+' |
        ForEach-Object { $_.Line } |
        Add-Content -Path $NmapFindings -Encoding utf8

    "`n=== Open or filtered ports to review ===" | Add-Content -Path $NmapFindings -Encoding utf8
    Select-String -Path $NmapServices -Pattern '^\d+/tcp\s+(open|filtered)\s+' |
        ForEach-Object { $_.Line } |
        Add-Content -Path $NmapFindings -Encoding utf8
} else {
    "Nmap services file not found." | Add-Content -Path $NmapFindings -Encoding utf8
}

if (Test-Path $NmapHttp) {
    "`n=== HTTP/header details of interest ===" | Add-Content -Path $NmapFindings -Encoding utf8
    Select-String -Path $NmapHttp -Pattern 'http-|Content-Security-Policy|X-Frame|X-Content|Referrer|Server:|ssl-cert|open|filtered' -CaseSensitive:$false |
        ForEach-Object { $_.Line } |
        Add-Content -Path $NmapFindings -Encoding utf8
}

@"
ZAP findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Target: $TargetUrl
Auth injected: $ZapAuthInjected
ZAP exit code: $(if ($null -eq $ZapExitCode) { 'n/a' } else { $ZapExitCode })
Reports: HTML=$(Test-Path $ZapHtmlPath) JSON=$(Test-Path $ZapJsonPath) MD=$(Test-Path $ZapMdPath)

Notes:
- Authenticated ZAP uses integrator Bearer token via docker --env-file + replacer config (secrets never logged).
- Baseline scan checks public pages, response headers, and shallow protected routes when auth is injected.
- Use -StrictZap to fail the release gate on Medium alerts.

"@ | Set-Content -Path $ZapFindings -Encoding utf8

if (Test-Path $ZapMdPath) {
    "`n=== ZAP markdown alert snippets ===" | Add-Content -Path $ZapFindings -Encoding utf8
    Select-String -Path $ZapMdPath -Pattern 'WARN|FAIL|High|Medium|Low|Informational|Missing|Content Security|CSP|X-Frame|CORS|Cookie|Server|Referrer|Header' -CaseSensitive:$false |
        ForEach-Object { $_.Line } |
        Add-Content -Path $ZapFindings -Encoding utf8

    "`nFull markdown report: $ZapMdPath" | Add-Content -Path $ZapFindings -Encoding utf8
    "`nHTML report: $ZapHtmlPath" | Add-Content -Path $ZapFindings -Encoding utf8
}
else {
    @"
No ZAP markdown report was created.

Auth injected: $ZapAuthInjected
ZAP exit code: $(if ($null -eq $ZapExitCode) { 'n/a' } else { $ZapExitCode })
ZAP skipped: $ZapSkipped

Most likely reasons:
- Target URL was not reachable from the ZAP Docker container.
- Docker Desktop was not running.
- ZAP failed before report generation (check exit code 3 in 20-zap-console-output.txt).

Review:
- $ZapConsole
- $ReachabilityFile

"@ | Add-Content -Path $ZapFindings -Encoding utf8
}

@"
Open-FDD quick findings summary
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Report folder:
$BaseDir

Primary files:
- 30-nmap-findings-summary.txt
- 31-zap-findings-summary.txt
- 99-review-checklist.txt

Nmap port exposure summary:
"@ | Set-Content -Path $QuickSummary -Encoding utf8

if (Test-Path $NmapServices) {
    Select-String -Path $NmapServices -Pattern '^\d+/tcp\s+' |
        ForEach-Object { $_.Line } |
        Add-Content -Path $QuickSummary -Encoding utf8
} else {
    "Nmap did not produce a services report." | Add-Content -Path $QuickSummary -Encoding utf8
}

"`nZAP summary:" | Add-Content -Path $QuickSummary -Encoding utf8
if (Test-Path $ZapMdPath) {
    "ZAP report produced: $ZapMd" | Add-Content -Path $QuickSummary -Encoding utf8
    Select-String -Path $ZapMdPath -Pattern 'WARN|FAIL|High|Medium|Low|Missing|Content Security|CSP|X-Frame|CORS|Cookie|Server|Referrer|Header' -CaseSensitive:$false |
        Select-Object -First 80 |
        ForEach-Object { $_.Line } |
        Add-Content -Path $QuickSummary -Encoding utf8
} else {
    "No ZAP markdown report produced. Check 20-zap-console-output.txt." | Add-Content -Path $QuickSummary -Encoding utf8
}

@"
Open-FDD local security review checklist

Target:
- Host: $HostIp
- URL:  $TargetUrl

Files to review:
- 01-web-reachability-and-headers.txt
- 02-web-response-headers.txt
- 10-nmap-console-output.txt
- 11-nmap-openfdd-services.txt
- 13-nmap-openfdd-http-details.txt
- 20-zap-console-output.txt
- 21-zap-openfdd-baseline.html
- 21-zap-openfdd-baseline.md
- 21-zap-openfdd-baseline.json
- 30-nmap-findings-summary.txt
- 31-zap-findings-summary.txt
- 90-quick-findings-summary.txt

Nmap things to fix or confirm:
- 80 open is expected only if Caddy HTTP mode is enabled.
- 443 should be open if Caddy TLS mode is enabled.
- 8765 bridge should stay closed from LAN when Caddy fronts it.
- 8090 mcp-rag should usually stay internal-only.
- 5173 Vite dev server should be closed.
- 8000/8080 dev/API ports should be closed unless intentionally exposed.
- Any unexpected open service should be investigated.

ZAP things to fix or confirm:
- Missing or weak Content-Security-Policy.
- Duplicate security headers from both Caddy and FastAPI.
- Conflicting X-Frame-Options values.
- Missing X-Content-Type-Options.
- Missing Referrer-Policy.
- Permissive CORS.
- Server errors / stack traces.
- Unauthenticated access to routes that should require login.
- Cache-control issues on authenticated pages.
- Cookie issues if cookies are used.

Important:
- This script runs ZAP baseline, not ZAP full active scan.
- If Open-FDD requires login, this unauthenticated scan is useful but shallow.
- Later, do authenticated ZAP only on a fake/test site.
- Do not run broad scans against live OT/BAS networks or controllers.
"@ | Set-Content -Path $Checklist -Encoding utf8

Write-Section "Release gate (production asset leak + auth + ZAP)"

$gateFails = 0
$gateWarnings = 0
$gatePasses = 0

$gateLines = @(
    "Release gate summary",
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Target: $TargetUrl",
    "Auth loaded: $authLoaded",
    "ZAP auth injected: $ZapAuthInjected",
    ""
)

if ($TargetReachable) {
    $assetIssues = Test-ProductionAssetLeak -HtmlPath $WebBodySample -BaseUrl $TargetUrl
    if ($assetIssues.Count -eq 0) {
        $gatePasses += 1
        $gateLines += "PASS: production JS bundle — no private LAN / bench literals detected"
    } else {
        $gateFails += $assetIssues.Count
        $gateLines += "FAIL: production asset leak ($($assetIssues.Count) issue(s)):"
        $gateLines += $assetIssues
    }

    $authResult = Invoke-AuthProbe -BaseUrl $TargetUrl -User $integratorUser -Password $integratorPass
    if ($authLoaded -and $authResult.Ok) {
        $gatePasses += 1
        $gateLines += "PASS: integrator auth probe — $($authResult.Detail)"
    } elseif ($authLoaded) {
        $gateFails += 1
        $gateLines += "FAIL: auth file/env loaded but login probe failed — $($authResult.Detail)"
    } else {
        $gateWarnings += 1
        $gateLines += "WARN: Auth loaded: False — pass -AuthEnvFile <path-to-auth.env.local> or set OFDD_INTEGRATOR_USER / OFDD_INTEGRATOR_PASSWORD in the shell (values are never logged)."
    }

    $routeIssues = Test-ProtectedRoutesAnonymous -BaseUrl $TargetUrl
    if ($routeIssues.Count -eq 0) {
        $gatePasses += 1
        $gateLines += "PASS: anonymous protected API routes return 401/403 (public /health and /api/auth/status return 200)"
    } else {
        $gateFails += $routeIssues.Count
        $gateLines += "FAIL: route auth probe ($($routeIssues.Count) issue(s)):"
        $gateLines += $routeIssues
    }

    $cors = Test-HostileCorsRejected -BaseUrl $TargetUrl
    if ($cors.Ok) {
        $gatePasses += 1
        $gateLines += "PASS: hostile CORS origin rejected — $($cors.Detail)"
    } else {
        $gateFails += 1
        $gateLines += "FAIL: CORS probe — $($cors.Detail)"
    }
} else {
    $gateFails += 1
    $gateLines += "FAIL: target not reachable — cannot run asset leak or auth probes"
}

if (-not $SkipZap -and -not $ZapSkipped) {
    $reportsOk = (Test-Path $ZapHtmlPath) -and (Test-Path $ZapJsonPath) -and (Test-Path $ZapMdPath)
    $zapCounts = Get-ZapAlertCounts -JsonPath $ZapJsonPath
    $gateLines += ""
    $gateLines += "ZAP baseline:"
    $gateLines += "  exit code: $(if ($null -eq $ZapExitCode) { 'n/a' } else { $ZapExitCode })"
    $gateLines += "  reports produced: $reportsOk"
    $gateLines += "  alerts: High=$($zapCounts.High) Medium=$($zapCounts.Medium) Low=$($zapCounts.Low)"

    if (-not $reportsOk) {
        $gateFails += 1
        $gateLines += "FAIL: ZAP reports missing (expected 21-zap-openfdd-baseline.html/json/md)"
    } elseif ($null -ne $ZapExitCode -and $ZapExitCode -eq 3) {
        $gateFails += 1
        $gateLines += "FAIL: ZAP exited with code 3 — scan did not complete (see 20-zap-console-output.txt)"
    } elseif ($null -ne $ZapExitCode -and $ZapExitCode -ne 0) {
        $gateFails += 1
        $gateLines += "FAIL: ZAP exited with code $ZapExitCode"
    } elseif ($zapCounts.High -gt 0) {
        $gateFails += 1
        $gateLines += "FAIL: ZAP High alerts = $($zapCounts.High)"
    } elseif ($StrictZap -and $zapCounts.Medium -gt 0) {
        $gateFails += 1
        $gateLines += "FAIL: ZAP Medium alerts = $($zapCounts.Medium) (-StrictZap)"
    } else {
        $gatePasses += 1
        $gateLines += "PASS: ZAP baseline completed with reports"
        if ($zapCounts.Medium -gt 0) {
            $gateWarnings += 1
            $gateLines += "WARN: ZAP Medium alerts = $($zapCounts.Medium) (accepted unless -StrictZap)"
        }
    }
} elseif ($SkipZap) {
    $gateWarnings += 1
    $gateLines += ""
    $gateLines += "WARN: ZAP skipped (-SkipZap) — release gate does not include passive web scan"
} else {
    $gateFails += 1
    $gateLines += ""
    $gateLines += "FAIL: ZAP did not run (Docker down or target unreachable)"
}

$gateLines += ""
$gateLines += "Summary: $gatePasses pass / $gateWarnings warn / $gateFails fail"
if ($gateFails -gt 0) {
    $gateLines += "SECURITY GATE: FAIL ($gateFails fail, $gateWarnings warn)"
} else {
    $gateLines += "SECURITY GATE: PASS ($gateWarnings warn)"
}

$gateLines | Set-Content -Path $GateReport -Encoding utf8
Write-Host ($gateLines -join "`n")

Write-Section "Done"
Write-Host "Reports saved to:"
Write-Host $BaseDir
Write-Host ""
Write-Host "Read these first:"
Write-Host "  $GateReport"
Write-Host "  $QuickSummary"
Write-Host "  $NmapFindings"
Write-Host "  $ZapFindings"
Write-Host "  $Checklist"
Write-Host ""
Write-Host "No files were opened automatically."

if ($gateFails -gt 0) {
    exit 1
}
