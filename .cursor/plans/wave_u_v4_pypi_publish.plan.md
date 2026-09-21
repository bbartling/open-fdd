---
name: Wave U V4 PyPI publish
overview: "Publish open-fdd 4.4.3 to PyPI; Camber unfinished families Soft-OPEN honesty. Soft-OPEN wave-s3-pypi-mv-oracle / wu-pypi-publish-4.4.3."
todos:
  - id: v4-wheel-verify
    content: Local wheel build/test for 4.4.3 per openfdd-pypi-oracle skill
    status: pending
  - id: v4-publish
    content: Publish open-fdd 4.4.3 to PyPI; verify pip install version
    status: pending
  - id: v4-docs
    content: BUG_REPORT Soft-OPEN close publish row; Camber residual honesty
    status: pending
isProject: false
---

# V4 — PyPI 4.4.3 publish

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)  
**Child detail:** [`wave_s3_pypi_mv_camber_oracle.plan.md`](wave_s3_pypi_mv_camber_oracle.plan.md)

## Soft-OPEN closed by this cycle

- `wu-pypi-publish-4.4.3` (publish tip)
- `wave-s3-pypi-mv-oracle` PARTIAL → math+publish CLOSED; unfinished Camber families remain Soft-OPEN honesty

## Work

1. Follow maintainer PyPI / `openfdd-pypi-oracle` skill: build, test, publish **4.4.3**.
2. Verify `pip index versions open-fdd` shows 4.4.3.
3. Do **not** greenwash unfinished Camber families — leave Soft-OPEN note.
4. No GHCR product tip required unless docs-only Pages change. **No MEGA.**

## Exit

- PyPI 4.4.3 live; BUG_REPORT row CLOSED for publish; Camber residual listed.
