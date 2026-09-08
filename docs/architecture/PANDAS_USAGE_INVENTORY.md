# SUPERSEDED — 2026-07-28 pandas UI inventory

**Status:** historical tombstone (Wave J Stage A, 2026-09-08).

This inventory classified `frontend/web/app/*.py` files as React product runtime.
On tip those paths **do not exist**. The product UI is TypeScript under
`frontend/web/src/`; FDD/analytics run in central (Rust/DataFusion).

**Current contract:** [compute_boundary_ownership.md](compute_boundary_ownership.md) ·
[compute_boundary_ownership.yaml](compute_boundary_ownership.yaml) ·
[datafusion-first.md](datafusion-first.md).

Do **not** recreate deleted Python SPA paths to “satisfy” this table.
Do **not** treat rows below as live call-graph evidence.

---

(Original table body intentionally omitted from the active doc surface — see git
history at commit predating Wave J Stage A if you need the 2026-07-28 listing.)
