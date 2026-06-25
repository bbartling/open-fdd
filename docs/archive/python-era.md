# Python-era Open-FDD (archived)

Open-FDD **3.2** on `master` is a **Rust-only** edge stack. This note documents the retired Python line for historians searching old release notes.

## What changed

| Python era (≤3.1) | Rust edge (3.2+) |
| --- | --- |
| PyPI package `open-fdd` | GHCR image `ghcr.io/bbartling/openfdd-edge-rust` |
| Python bridge on port 8765 | Rust bridge on port 8080 |
| Separate Python GHCR images | Single multi-arch Rust image (`SERVICE_MODE`) |
| PyArrow rule functions in edge | DataFusion SQL on Arrow historian |
| Python DOCX report scripts | React report builder + PDF endpoints |

## Not supported on master

- `pip install open-fdd`
- PyPI publish workflow (removed)
- Legacy Python GHCR publish workflows (disabled)

## Where to look in git history

Tags and branches before the Rust rewrite contain Python sources, cookbooks, and migration scripts. Do not use them for new deployments.
