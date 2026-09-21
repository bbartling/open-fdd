# Image finding dispositions (Wave U UA-05)

Historical scan: `reports/trivy-wave-u/sha-f44b45f/` (2026-09-20).
Tip rescan: `reports/trivy-wave-u/sha-1677c33/` (2026-09-21) — mqtt **0** High/Critical; web nginx FixedVersion present; Debian TRACKED UNFIXED; caddy High residual.
Policy: unresolved Critical/High block readiness VERIFIED. Medium needs owner + expiry.

| Component | Finding class | Disposition | Owner | Expiry / next action |
| --- | --- | --- | --- | --- |
| `openfdd-web` | Alpine `nginx` 1.28.2-r1 → FixedVersion 1.28.3-* | **REMEDIATE** | Release | Tip **3.5.38** `apk add --upgrade nginx` after `apk upgrade`; rescan published tip |
| `openfdd-central` / `fieldbus` / `mcp` | Debian bookworm OS High where FixedVersion is `-` | **TRACKED UNFIXED** | Release | Remain OPEN until distroless/rebuild or upstream bookworm fix; do not claim secure |
| `openfdd-mqtt` | 0 High/Critical on `sha-1677c33` | Accepted for this component | Release | Re-verify on each tip |
| `caddy` (standalone HTTPS) | High/Critical on `caddy:2.8-alpine` (and 2.10 probe still High) | **TRACKED / REMEDIATE** | Release | Compose-aligned `2.8-alpine` in Trivy all-scope; continue base bumps; do not greenwash |

This file is not a waiver of Critical/High. Soft-OPEN `image-digest-trivy` stays REMEDIATION OPEN until digests meet policy or each residual has an evidence-backed false-positive determination.
