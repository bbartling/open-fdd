"""Packaged Liberty full-parity example ships with the wheel."""

from __future__ import annotations

from importlib.resources import files


def test_liberty_full_parity_example_xlsx_present() -> None:
    root = files("open_fdd.ecm_engineering").joinpath("examples/liberty_dual_ahu")
    xlsx = root.joinpath("ECM_FULL_PARITY.xlsx")
    assert xlsx.is_file(), f"missing golden example: {xlsx}"
    # Sanity: real workbook, not an empty placeholder
    assert xlsx.stat().st_size > 10_000
