# Image finding dispositions (Wave U UA-05)

Historical scan: `reports/trivy-wave-u/sha-f44b45f/` (2026-09-20).
Tip rescan: `reports/trivy-wave-u/sha-1677c33/` (2026-09-21) — mqtt **0** High/Critical; web nginx FixedVersion present; Debian TRACKED UNFIXED; caddy High residual.
Tip rescan: `reports/trivy-wave-u/sha-af4086f/` (2026-09-21) — mqtt **0**; web nginx still **1.28.2-r1** (modules blocked apk upgrade); Debian TRACKED UNFIXED; caddy High residual. **V1 / 3.5.39:** `apk del nginx-module-*` then `nginx>=1.28.3` in `frontend/web/Dockerfile`.
Tip rescan: `reports/trivy-wave-u/sha-7ad6479/` (2026-09-22) — **W1** on OPS PINNED tip 3.5.43; web **0** High/Critical (`nginx 1.28.3-r7`); mqtt **0**; Debian TRACKED UNFIXED; caddy High residual. **3.5.44 / `d959def` GHCR lag** (publish cancelled by superseding master push; W0 publish in flight).
Policy: unresolved Critical/High block readiness VERIFIED. Medium needs owner + expiry.

| Component | Finding class | Disposition | Owner | Expiry / next action |
| --- | --- | --- | --- | --- |
| `openfdd-web` | Alpine `nginx` 1.28.2-r1 → FixedVersion 1.28.3-* | **CLEARED on tip** (`sha-7ad6479` / 3.5.43; installed `1.28.3-r7`; web H/C **0/0**) | Release | Re-verify on next published tip (3.5.44+ when GHCR lands) |
| `openfdd-central` / `fieldbus` / `mcp` | Debian bookworm OS High where FixedVersion is `-` | **TRACKED UNFIXED** | Release | Remain OPEN until distroless/rebuild or upstream bookworm fix; do not claim secure |
| `openfdd-mqtt` | 0 High/Critical on `sha-7ad6479` | Accepted for this component | Release | Re-verify on each tip |
| `caddy` (standalone HTTPS) | High/Critical on `caddy:2.8-alpine` (and 2.10 probe still High) | **TRACKED / REMEDIATE** | Release | Compose-aligned `2.8-alpine` in Trivy all-scope; continue base bumps; do not greenwash |

This file is not a waiver of Critical/High. Soft-OPEN `image-digest-trivy` stays PARTIAL while Debian/caddy Critical/High remain unresolved — nginx remediable class is closed on the cited tip, not the whole image-finding Soft-OPEN.
