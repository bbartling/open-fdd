# Open-FDD web app security scripts v3.4

This version is intentionally simpler:

- No SSH.
- No `workspace` folder expectation.
- `auth.env.local` should live in the **same folder as the PowerShell scripts**.
- The main scan stops immediately if it cannot load the auth file or selected role credentials.

## Files

```text
Run-OpenFddWebAppSecurityScan-v3.4.ps1
OpenFdd-WebAppPreflight-v3.4.ps1
Rotate-OpenFddAuthEnv-v3.4.ps1
auth.env.local.example
```

## Folder layout

Put these files together in your zapper folder:

```text
C:\Users\ben\OneDrive\Desktop\testing\zapper\
  Run-OpenFddWebAppSecurityScan-v3.4.ps1
  OpenFdd-WebAppPreflight-v3.4.ps1
  Rotate-OpenFddAuthEnv-v3.4.ps1
  auth.env.local
```

The scanner now defaults to:

```text
auth.env.local beside Run-OpenFddWebAppSecurityScan-v3.4.ps1
```

So you do not need `-AuthEnvFile` for the normal case.

## Required auth keys

For the default integrator scan, `auth.env.local` needs:

```text
OFDD_INTEGRATOR_USER=integrator
OFDD_INTEGRATOR_PASSWORD=replace-me
```

It also supports operator and agent roles:

```text
OFDD_OPERATOR_USER=operator
OFDD_OPERATOR_PASSWORD=replace-me

OFDD_AGENT_USER=agent
OFDD_AGENT_PASSWORD=replace-me
```

Do not commit or paste the real file.

## Run preflight

```powershell
powershell -ExecutionPolicy Bypass -File .\OpenFdd-WebAppPreflight-v3.4.ps1 `
  -TargetUrl "http://192.168.204.18"
```

## Run the main scan

```powershell
powershell -ExecutionPolicy Bypass -File .\Run-OpenFddWebAppSecurityScan-v3.4.ps1 `
  -TargetUrl "http://192.168.204.18" `
  -AuthRole Integrator
```

Expected startup line:

```text
Auth loaded: True
```

If auth is missing or malformed, the script exits before running ZAP/Nmap so you do not accidentally get another mostly anonymous scan.

## Rotate local auth file

Because real secrets were pasted earlier, rotate them. This writes a fresh `auth.env.local` beside the scripts by default:

```powershell
powershell -ExecutionPolicy Bypass -File .\Rotate-OpenFddAuthEnv-v3.4.ps1
```

Then copy the same generated values into the actual Open-FDD runtime auth file and restart/reload Open-FDD/Caddy so the app accepts the new credentials.

## Anonymous-only mode

Only use this when you deliberately want a no-login smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File .\Run-OpenFddWebAppSecurityScan-v3.4.ps1 `
  -TargetUrl "http://192.168.204.18" `
  -AuthKind None
```

## Main reports

After the scan, start here:

```text
openfdd-webapp-security-report\90-quick-findings-summary.txt
openfdd-webapp-security-report\98-security-gate-results.csv
openfdd-webapp-security-report\04-route-auth-cors-tests.txt
openfdd-webapp-security-report\06-asset-leak-summary.txt
openfdd-webapp-security-report\31-zap-findings-summary.txt
```
