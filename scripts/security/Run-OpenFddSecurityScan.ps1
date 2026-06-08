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
    [switch]$KeepExisting
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

function Invoke-NativeToFile {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$OutputFile,
        [switch]$Append
    )

    $ArgLine = ($Args | ForEach-Object { Quote-NativeArg $_ }) -join " "
    $TempOut = [System.IO.Path]::GetTempFileName()
    $TempErr = [System.IO.Path]::GetTempFileName()

    $Header = @(
        "> $Exe $ArgLine"
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
            -ArgumentList $ArgLine `
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

$QuickSummary = Join-Path $BaseDir "90-quick-findings-summary.txt"
$Checklist = Join-Path $BaseDir "99-review-checklist.txt"

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
    }
    else {
        if (-not $SkipZapPull) {
            Write-Host "Pulling latest stable ZAP image..."
            Invoke-NativeToFile -Exe "docker" -Args @("pull", "ghcr.io/zaproxy/zaproxy:stable") -OutputFile $ZapConsole | Out-Null
        } else {
            "SKIPPED docker pull because -SkipZapPull was used." | Set-Content -Path $ZapConsole -Encoding utf8
        }

        Write-Host "Running ZAP baseline. Output goes to report folder."
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

        Invoke-NativeToFile -Exe "docker" -Args $ZapArgs -OutputFile $ZapConsole -Append | Out-Null
    }
} else {
    "SKIPPED by -SkipZap." | Set-Content -Path $ZapConsole -Encoding utf8
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

Notes:
- This is unauthenticated ZAP baseline.
- If Open-FDD requires login, this still checks public pages and headers, but it will not deeply test protected dashboard/API routes.
- Use authenticated ZAP later only on a fake/test bench.

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

Most likely reasons:
- Target URL was not reachable from the ZAP Docker container.
- Docker Desktop was not running.
- ZAP failed before report generation.

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

Write-Section "Done"
Write-Host "Reports saved to:"
Write-Host $BaseDir
Write-Host ""
Write-Host "Read these first:"
Write-Host "  $QuickSummary"
Write-Host "  $NmapFindings"
Write-Host "  $ZapFindings"
Write-Host "  $Checklist"
Write-Host ""
Write-Host "No files were opened automatically."
