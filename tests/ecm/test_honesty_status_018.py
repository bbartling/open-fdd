"""BUG-ECM-018 — FITTED / BALLPARK / NO_EP / FAIL_SIGN classification."""

from __future__ import annotations

from open_fdd.ecm_engineering.honesty_status import (
    MeasureHonestyStatus,
    classify_measure_status,
    wiring_echo_pct,
)


def test_fitted_never_ballpark_even_when_echo_zero() -> None:
    status = classify_measure_status(
        hours_provenance="FITTED_FROM_EPLUS",
        eplus_kwh=100_000.0,
        fitted_kwh=100_000.0,
        industry_kwh=80_000.0,
        eplus_source="cascade",
    )
    assert status is MeasureHonestyStatus.FITTED
    assert wiring_echo_pct(100_000.0, 100_000.0) == 0.0


def test_screening_is_ballpark() -> None:
    status = classify_measure_status(
        hours_provenance="SCREENING_ASSUMPTION",
        eplus_kwh=69.0,
        fitted_kwh=39.0,
        eplus_source="July MCP pair",
    )
    assert status is MeasureHonestyStatus.BALLPARK


def test_no_ep() -> None:
    assert (
        classify_measure_status(hours_provenance="SCREENING", eplus_source="NO_EP")
        is MeasureHonestyStatus.NO_EP
    )
    assert (
        classify_measure_status(hours_provenance="SCREENING", eplus_kwh=None)
        is MeasureHonestyStatus.NO_EP
    )


def test_fail_sign() -> None:
    assert (
        classify_measure_status(
            hours_provenance="SCREENING_ASSUMPTION",
            eplus_kwh=-7000.0,
            fitted_kwh=120_000.0,
            eplus_source="cascade",
        )
        is MeasureHonestyStatus.FAIL_SIGN
    )
