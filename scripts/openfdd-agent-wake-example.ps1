# Example: wake the built-in Open-FDD agent on a schedule (Task Scheduler / cron).
# Prereqs: bridge running, `codex login` done on that host, OFDD_DESKTOP_BRIDGE_BASE in env if not 8765.
param(
  [string]$BridgeBase = "http://127.0.0.1:8765",
  [string]$Workdir = "",
  [string]$Prompt = "Summarize bridge health and MCP manifest reachability; suggest one next action for FDD ops.",
  [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"

$uri = ($BridgeBase.TrimEnd("/") + "/openfdd-agent/chat")
$body = @{
  message      = $Prompt
  workdir      = $(if ($Workdir) { $Workdir } else { $null })
  task_summary = $Prompt
} | ConvertTo-Json

try {
  Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec $TimeoutSec -ErrorAction Stop
} catch {
  Write-Error "openfdd-agent wake failed: $($_.Exception.Message)"
  if ($_.Exception.InnerException) {
    Write-Error "Inner: $($_.Exception.InnerException.Message)"
  }
  exit 1
}
