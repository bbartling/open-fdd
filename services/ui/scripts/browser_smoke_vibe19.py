#!/usr/bin/env python3
"""Playwright browser smoke for Vibe 19 mechanical-cooling Overview.

Exercises visual cases via synthetic openfdd packages (and optional --package):
  - one running device
  - overlapping multiple devices
  - no eligible compressor
  - eligible zero-runtime compressor
  - chilled-water AHU valve exclusion

Usage:
  python scripts/browser_smoke_vibe19.py --url http://localhost:8501 \\
      --screenshots .artifacts/browser/native

  python scripts/browser_smoke_vibe19.py --url http://localhost:8502 \\
      --package path/to/BUILDING_100.zip --screenshots .artifacts/browser/docker
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FATAL_PAGE_PATTERNS = (
    "Traceback",
    "StreamlitAPIException",
    "PlotlyError",
    "Exception:",
    "ModuleNotFoundError",
    "AttributeError:",
    "TypeError:",
    "ValueError:",
)


@dataclass(frozen=True)
class VisualCase:
    case_id: str
    building_id: str
    expect_any: tuple[str, ...]
    expect_none: tuple[str, ...] = ()
    description: str = ""


def _manifest(building_id: str, *, grid_minutes: int = 60) -> str:
    return json.dumps(
        {
            "schema_version": "openfdd_package_v1",
            "building_id": building_id,
            "grid_minutes": grid_minutes,
            "timezone": "UTC",
            "notes": "browser_smoke_vibe19 synthetic",
        },
        indent=2,
    )


def _sidecar(equip_type: str, points: dict[str, str]) -> str:
    return json.dumps({"equipType": equip_type, "points": points}, indent=2)


def _csv(header: str, rows: list[str]) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def _weather_rows(n: int = 10, oat_start: float = 55.0) -> list[str]:
    return [
        f"2024-07-01T{h:02d}:00:00Z,{oat_start + h * 3.0}" for h in range(n)
    ]


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def build_case_package(case_id: str) -> tuple[bytes, VisualCase]:
    """Return (zip_bytes, VisualCase) for a required visual scenario."""
    weather = _csv("timestamp_utc,oa_t", _weather_rows())

    if case_id == "one_running":
        # CHILLER_2 runs; CHILLER_1 mapped but flat-off → also covers zero-runtime in same pkg
        # Keep separate case for zero_runtime below; this focuses on sole-running message.
        ch2 = _csv(
            "timestamp_utc,chiller_run_status,oa_t",
            [f"2024-07-01T{h:02d}:00:00Z,1,{55 + h * 3}" for h in range(10)],
        )
        files = {
            "manifest.json": _manifest("SMOKE_ONE_RUNNING"),
            "session_config.json": json.dumps(
                {
                    "schema_version": "openfdd_session_v1",
                    "unit_system": "imperial",
                    "prefer_web_oat": False,
                    "role_map": {
                        "CHILLER_2": {"chiller-status": "chiller_run_status"},
                    },
                }
            ),
            "CHILLER_2/history_wide.csv": ch2,
            "CHILLER_2/column_map.json": _sidecar(
                "chiller", {"chiller-status": "chiller_run_status"}
            ),
            "weather/history_wide.csv": weather,
        }
        case = VisualCase(
            case_id=case_id,
            building_id="SMOKE_ONE_RUNNING",
            expect_any=(
                "Only CHILLER_2 had observed compressor runtime",
                "Total compressor device-hours therefore equal CHILLER_2",
                "Mechanical cooling hours by OAT bin",
                "Total compressor device-hours",
                "Any compressor active",
            ),
            description="one running compressor device",
        )
        return _zip_bytes(files), case

    if case_id == "overlapping":
        # Two chillers both on overlapping hours → device-hours > active-hours
        ch1 = _csv(
            "timestamp_utc,chiller_run_status,oa_t",
            [f"2024-07-01T{h:02d}:00:00Z,1,{55 + h * 3}" for h in range(10)],
        )
        ch2 = _csv(
            "timestamp_utc,chiller_run_status,oa_t",
            [
                f"2024-07-01T{h:02d}:00:00Z,{1 if h >= 3 else 0},{55 + h * 3}"
                for h in range(10)
            ],
        )
        files = {
            "manifest.json": _manifest("SMOKE_OVERLAP"),
            "session_config.json": json.dumps(
                {
                    "schema_version": "openfdd_session_v1",
                    "unit_system": "imperial",
                    "prefer_web_oat": False,
                    "role_map": {
                        "CHILLER_1": {"chiller-status": "chiller_run_status"},
                        "CHILLER_2": {"chiller-status": "chiller_run_status"},
                    },
                }
            ),
            "CHILLER_1/history_wide.csv": ch1,
            "CHILLER_1/column_map.json": _sidecar(
                "chiller", {"chiller-status": "chiller_run_status"}
            ),
            "CHILLER_2/history_wide.csv": ch2,
            "CHILLER_2/column_map.json": _sidecar(
                "chiller", {"chiller-status": "chiller_run_status"}
            ),
            "weather/history_wide.csv": weather,
        }
        case = VisualCase(
            case_id=case_id,
            building_id="SMOKE_OVERLAP",
            expect_any=(
                "Mechanical cooling hours by OAT bin",
                "Total compressor device-hours",
                "Any compressor active",
                "CHILLER_1",
                "CHILLER_2",
            ),
            expect_none=("Only CHILLER_",),
            description="overlapping multiple compressor devices",
        )
        return _zip_bytes(files), case

    if case_id == "no_eligible":
        # AHU CHW valve only — excluded, no compressor proof
        ahu = _csv(
            "timestamp_utc,cooling_valve,oa_t,fan_status",
            [f"2024-07-01T{h:02d}:00:00Z,{80 if h % 2 else 0},{55 + h * 3},1" for h in range(10)],
        )
        files = {
            "manifest.json": _manifest("SMOKE_NO_ELIGIBLE"),
            "session_config.json": json.dumps(
                {
                    "schema_version": "openfdd_session_v1",
                    "unit_system": "imperial",
                    "prefer_web_oat": False,
                    "role_map": {
                        "AHU_1": {
                            "cooling-valve": "cooling_valve",
                            "fan-status": "fan_status",
                            "outside-air-temp": "oa_t",
                        }
                    },
                }
            ),
            "AHU_1/history_wide.csv": ahu,
            "AHU_1/column_map.json": _sidecar(
                "ahu",
                {
                    "cooling-valve": "cooling_valve",
                    "fan-status": "fan_status",
                    "outside-air-temp": "oa_t",
                },
            ),
            "weather/history_wide.csv": weather,
        }
        case = VisualCase(
            case_id=case_id,
            building_id="SMOKE_NO_ELIGIBLE",
            expect_any=(
                "No eligible compressor devices with mapped compressor proof",
                "CHW pump status or cooling-valve signals alone do not count",
            ),
            description="no eligible compressor devices",
        )
        return _zip_bytes(files), case

    if case_id == "zero_runtime":
        ch1 = _csv(
            "timestamp_utc,chiller_run_status,chiller_amps,oa_t",
            [f"2024-07-01T{h:02d}:00:00Z,0,0.0,{55 + h * 3}" for h in range(10)],
        )
        files = {
            "manifest.json": _manifest("SMOKE_ZERO_RUNTIME"),
            "session_config.json": json.dumps(
                {
                    "schema_version": "openfdd_session_v1",
                    "unit_system": "imperial",
                    "prefer_web_oat": False,
                    "role_map": {
                        "CHILLER_1": {
                            "chiller-status": "chiller_run_status",
                            "chiller-amps": "chiller_amps",
                        }
                    },
                }
            ),
            "CHILLER_1/history_wide.csv": ch1,
            "CHILLER_1/column_map.json": _sidecar(
                "chiller",
                {
                    "chiller-status": "chiller_run_status",
                    "chiller-amps": "chiller_amps",
                },
            ),
            "weather/history_wide.csv": weather,
        }
        case = VisualCase(
            case_id=case_id,
            building_id="SMOKE_ZERO_RUNTIME",
            expect_any=(
                "No runtime observed",
                "Mechanical cooling devices",
                "eligible",
            ),
            description="eligible zero-runtime compressor",
        )
        return _zip_bytes(files), case

    if case_id == "ahu_valve_exclusion":
        ahu = _csv(
            "timestamp_utc,cooling_valve,oa_t,fan_status",
            [f"2024-07-01T{h:02d}:00:00Z,100,{55 + h * 3},1" for h in range(10)],
        )
        ch = _csv(
            "timestamp_utc,chiller_run_status,oa_t",
            [f"2024-07-01T{h:02d}:00:00Z,1,{55 + h * 3}" for h in range(10)],
        )
        files = {
            "manifest.json": _manifest("SMOKE_AHU_VALVE"),
            "session_config.json": json.dumps(
                {
                    "schema_version": "openfdd_session_v1",
                    "unit_system": "imperial",
                    "prefer_web_oat": False,
                    "role_map": {
                        "AHU_1": {
                            "cooling-valve": "cooling_valve",
                            "fan-status": "fan_status",
                        },
                        "CHILLER_2": {"chiller-status": "chiller_run_status"},
                    },
                }
            ),
            "AHU_1/history_wide.csv": ahu,
            "AHU_1/column_map.json": _sidecar(
                "ahu",
                {
                    "cooling-valve": "cooling_valve",
                    "fan-status": "fan_status",
                },
            ),
            "CHILLER_2/history_wide.csv": ch,
            "CHILLER_2/column_map.json": _sidecar(
                "chiller", {"chiller-status": "chiller_run_status"}
            ),
            "weather/history_wide.csv": weather,
        }
        case = VisualCase(
            case_id=case_id,
            building_id="SMOKE_AHU_VALVE",
            expect_any=(
                "AHU_1",
                "excluded",
                "Mechanical cooling devices",
                "CHILLER_2",
                "Never CHW cooling valves",
            ),
            description="chilled-water AHU valve exclusion",
        )
        return _zip_bytes(files), case

    raise ValueError(f"unknown visual case: {case_id}")


ALL_CASE_IDS = (
    "one_running",
    "overlapping",
    "no_eligible",
    "zero_runtime",
    "ahu_valve_exclusion",
)


def _write_case_zips(out_dir: Path) -> list[tuple[Path, VisualCase]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, VisualCase]] = []
    for case_id in ALL_CASE_IDS:
        blob, case = build_case_package(case_id)
        path = out_dir / f"{case_id}.zip"
        path.write_bytes(blob)
        written.append((path, case))
    return written


def _wait_streamlit_ready(page, timeout_ms: int = 90_000) -> None:
    page.wait_for_selector(
        "text=Building data",
        timeout=timeout_ms,
    )


def _switch_to_zip_package(page) -> None:
    """Ensure Zip package data source is selected (local mode defaults to Folder)."""
    zip_radio = page.get_by_role("radio", name="Zip package")
    if zip_radio.count() and not zip_radio.first.is_checked():
        zip_radio.first.click()
        page.wait_for_timeout(500)


def _clear_session(page) -> None:
    btn = page.get_by_role("button", name="Clear session")
    if btn.count():
        try:
            if btn.first.is_enabled():
                btn.first.click()
                page.wait_for_timeout(800)
        except Exception:
            pass


def _upload_and_load(page, zip_path: Path) -> None:
    _switch_to_zip_package(page)
    file_input = page.locator('input[type="file"]').first
    file_input.wait_for(state="attached", timeout=30_000)
    file_input.set_input_files(str(zip_path))
    # Streamlit needs a beat to enable the Load button after file selection.
    page.wait_for_timeout(1200)
    load_btn = page.get_by_role("button", name="Load zip(s)")
    load_btn.wait_for(state="visible", timeout=30_000)
    # Retry briefly while Streamlit enables the button.
    for _ in range(20):
        if load_btn.is_enabled():
            break
        page.wait_for_timeout(250)
    if not load_btn.is_enabled():
        raise AssertionError("Load zip(s) remained disabled after file upload")
    load_btn.click()
    page.wait_for_timeout(1500)
    # Success caption or mechanical-cooling section after reload.
    ready = (
        page.get_by_text("Mechanical cooling hours by OAT bin")
        .or_(page.get_by_text("Loaded"))
        .or_(page.get_by_text("No eligible compressor"))
    )
    ready.first.wait_for(state="visible", timeout=120_000)


def _goto_overview(page) -> None:
    overview = page.get_by_role("radio", name="Overview")
    if overview.count():
        if not overview.first.is_checked():
            overview.first.click()
            page.wait_for_timeout(1000)
    page.wait_for_selector("text=Mechanical cooling hours by OAT bin", timeout=60_000)


def _toggle_proof_filter(page) -> None:
    """Rerun after a filter change (status-proof checkbox or Prefer web OAT)."""
    label = page.locator("label").filter(
        has_text="Use mapped mechanical-cooling status proof"
    )
    if label.count():
        label.first.scroll_into_view_if_needed()
        label.first.click(force=True)
        page.wait_for_timeout(1500)
        label.first.click(force=True)
        page.wait_for_timeout(1500)
        return
    # Fallback filter that also triggers a Streamlit rerun.
    oat = page.locator("label").filter(has_text="Prefer web OAT")
    if oat.count():
        oat.first.click(force=True)
        page.wait_for_timeout(1500)
        oat.first.click(force=True)
        page.wait_for_timeout(1500)
        return
    # Last resort: change Equipment select if present.
    eq = page.get_by_label("Equipment")
    if eq.count():
        eq.first.click()
        page.wait_for_timeout(400)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)


def _page_text(page) -> str:
    return page.locator("body").inner_text(timeout=30_000)


def _assert_no_fatal(text: str, console_errors: list[str], page_errors: list[str]) -> None:
    for pat in FATAL_PAGE_PATTERNS:
        if pat in text:
            raise AssertionError(f"fatal page content matched {pat!r}")
    bad_console = [
        e
        for e in console_errors
        if any(
            x in e.lower()
            for x in (
                "traceback",
                "streamlitapiexception",
                "plotly",
                "uncaught",
                "typeerror",
                "referenceerror",
            )
        )
        and "favicon" not in e.lower()
    ]
    if bad_console:
        raise AssertionError("console errors:\n" + "\n".join(bad_console[:20]))
    if page_errors:
        raise AssertionError("page errors:\n" + "\n".join(page_errors[:20]))


def _assert_expectations(text: str, case: VisualCase) -> None:
    hay = text.lower()
    missing = [s for s in case.expect_any if s.lower() not in hay]
    if missing:
        raise AssertionError(
            f"case {case.case_id}: missing expected text {missing!r}\n"
            f"(page length={len(text)})"
        )
    forbidden = [s for s in case.expect_none if s.lower() in hay]
    if forbidden:
        raise AssertionError(
            f"case {case.case_id}: unexpected text {forbidden!r}"
        )


def run_smoke(
    *,
    url: str,
    screenshots: Path,
    package: Path | None,
    headless: bool = True,
) -> dict:
    from playwright.sync_api import sync_playwright

    screenshots.mkdir(parents=True, exist_ok=True)
    pkg_dir = screenshots / "_packages"
    cases = _write_case_zips(pkg_dir)
    results: dict = {"cases": [], "package": str(package) if package else None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        console_errors: list[str] = []
        page_errors: list[str] = []

        def _on_console(msg) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        def _on_page_error(exc) -> None:
            page_errors.append(str(exc))

        page.on("console", _on_console)
        page.on("pageerror", _on_page_error)

        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        _wait_streamlit_ready(page)
        page.screenshot(path=str(screenshots / "00_startup.png"), full_page=True)

        for zip_path, case in cases:
            console_errors.clear()
            page_errors.clear()
            print(f"== case {case.case_id}: {case.description}")
            _clear_session(page)
            _upload_and_load(page, zip_path)
            _goto_overview(page)
            # Allow Plotly / dataframes to settle.
            page.wait_for_timeout(2000)
            text = _page_text(page)
            _assert_no_fatal(text, console_errors, page_errors)
            _assert_expectations(text, case)
            shot = screenshots / f"{case.case_id}.png"
            page.screenshot(path=str(shot), full_page=True)
            _toggle_proof_filter(page)
            text2 = _page_text(page)
            _assert_no_fatal(text2, console_errors, page_errors)
            page.screenshot(
                path=str(screenshots / f"{case.case_id}_after_filter.png"),
                full_page=True,
            )
            results["cases"].append(
                {
                    "case_id": case.case_id,
                    "building_id": case.building_id,
                    "screenshot": str(shot),
                    "ok": True,
                }
            )
            print(f"   OK {case.case_id} -> {shot}")

        if package is not None and package.is_file():
            console_errors.clear()
            page_errors.clear()
            print(f"== optional package {package.name}")
            _clear_session(page)
            _upload_and_load(page, package)
            _goto_overview(page)
            page.wait_for_timeout(3000)
            text = _page_text(page)
            _assert_no_fatal(text, console_errors, page_errors)
            for needle in (
                "Mechanical cooling hours by OAT bin",
                "Mechanical cooling devices",
            ):
                if needle not in text:
                    raise AssertionError(f"package overview missing {needle!r}")
            shot = screenshots / "building_package.png"
            page.screenshot(path=str(shot), full_page=True)
            results["package_screenshot"] = str(shot)
            print(f"   OK package -> {shot}")

        browser.close()

    results["ok"] = True
    results["screenshots_dir"] = str(screenshots)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="Streamlit base URL")
    ap.add_argument(
        "--screenshots",
        type=Path,
        default=ROOT / ".artifacts" / "browser" / "native",
        help="Directory for PNG screenshots",
    )
    ap.add_argument(
        "--package",
        type=Path,
        default=None,
        help="Optional real openfdd zip (e.g. BUILDING_100.zip) for an extra case",
    )
    ap.add_argument("--headed", action="store_true", help="Show browser window")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    try:
        summary = run_smoke(
            url=args.url.rstrip("/"),
            screenshots=args.screenshots,
            package=args.package,
            headless=not args.headed,
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0
    print(
        f"OK browser smoke: {len(summary['cases'])} cases in {elapsed:.1f}s -> "
        f"{summary['screenshots_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
