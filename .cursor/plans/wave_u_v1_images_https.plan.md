---
name: Wave U V1 images HTTPS
overview: "Tip Trivy on published 3.5.38+ digests; product-image standalone HTTPS candidate soak (not stub). Soft-OPEN image-digest-trivy + standalone-https-bootstrap."
todos:
  - id: v1-tip-trivy
    content: Confirm sha-af4086f (or newest); Trivy all-scope; nginx High cleared or disposition
    status: pending
  - id: v1-candidate-https
    content: Peer probe candidate mode with real GHCR images + trusted TLS
    status: pending
  - id: v1-smoke
    content: GHCR tip check + Railway backup/re-pin smoke if product tip changes
    status: pending
isProject: false
---

# V1 — Images + product HTTPS

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)

## Soft-OPEN closed by this cycle

- `image-digest-trivy` / UA-05 (acceptance on tip digests; Debian/caddy may remain TRACKED UNFIXED)
- `standalone-https-bootstrap` / UA-02 (product-image candidate soak)

## Work

1. Resolve tip: `./scripts/ghcr_newest_by_created.py` — expect `sha-af4086f` / 3.5.38 or newer.
2. `ARTIFACT_DIR=<abs> ./scripts/security/trivy_ghcr_digests.sh sha-<7> all` → `reports/trivy-wave-u/sha-<7>/SUMMARY.md`.
3. Verify web nginx FixedVersion findings cleared vs `sha-1677c33`; update [`IMAGE_FINDING_DISPOSITIONS.md`](../../docs/operations/IMAGE_FINDING_DISPOSITIONS.md).
4. Extend [`scripts/security/peer_probe_https.py`](../../scripts/security/peer_probe_https.py) with **candidate** mode (real central/web/mqtt/caddy GHCR images); immutable `reports/security/standalone_https_peer_<UTC>/`.
5. Permanent tests: candidate mode rejects stub-as-product; trusted CA required.
6. If tip already published with nginx fix only: smoke Railway after backup/re-pin; **no MEGA**.

## Exit

- Trivy SUMMARY cited in BUG_REPORT; web remediable High/Critical closed or dispositioned.
- Product candidate HTTPS soak PASS artifact path recorded.
- Soft-OPEN rows updated; Debian/caddy honesty retained if unfixed.
