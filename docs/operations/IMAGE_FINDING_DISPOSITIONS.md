# Image finding dispositions (Wave U UA-05)

Historical scan: `reports/trivy-wave-u/sha-f44b45f/` (2026-09-20).
Policy: unresolved Critical/High block readiness VERIFIED. Medium needs owner + expiry.

| Component | Finding class | Disposition | Owner | Expiry / next action |
| --- | --- | --- | --- | --- |
| `openfdd-web` | Alpine openssl/libxml2/libpng/expat High/Critical with FixedVersion | **REMEDIATE** | Release | Tip bumps `nginxinc/nginx-unprivileged:1.28-alpine` + `apk upgrade`; rescan next published tip |
| `openfdd-central` / `fieldbus` / `mcp` | Debian bookworm OS High where FixedVersion is `-` | **TRACKED UNFIXED** | Release | Remain OPEN until distroless/rebuild or upstream bookworm fix; do not claim secure |
| `openfdd-mqtt` | 0 High/Critical on tip scan | Accepted for this component | Release | Re-verify on each tip |
| `caddy` (standalone HTTPS) | Not in `sha-f44b45f` suite | **REQUIRED** | Release | Include in `trivy_ghcr_digests.sh all` on next candidate scan |

This file is not a waiver of Critical/High. Soft-OPEN `image-digest-trivy` stays REMEDIATION OPEN until digests meet policy or each residual has an evidence-backed false-positive determination.
