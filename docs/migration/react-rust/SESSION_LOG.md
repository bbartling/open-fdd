# Session log — React / Rust modernization

Newest first.

## 2026-07-31 — P1-M1 gate (PR #615)

- Fixture catalog + content hashes under `tests/react_parity/`.
- Oracle exporter `tools/react_parity/export_reference_json.py` (byte-stable ×3).
- Interaction baseline: all CAP-* rows marked NONVISUAL (M3 visual) — honest M1 gate.
- Next: P1-M2-01 contract conventions.

## 2026-07-31 — P1-M0-02

- Seeded CAPABILITY_MATRIX, PYTHON_EXIT_MATRIX, API_CONTRACT_MATRIX, PARITY_EVIDENCE from code inventory.
- 16 capability rows; 64 production UI modules + streamlit entry; central `/api` families listed.
- Dispositions remain UNKNOWN pending M1 characterization.

## 2026-07-31 — P1-M0-01

- ADR-001 accepted; instruction hierarchy reconciled; policy CI wired.
- Next: P1-M0-02 capability / Python-exit / API ledgers from code inventory.
