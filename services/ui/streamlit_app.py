"""Open-FDD Streamlit lab — zip → Feather/SQL; Run Rules via central DataFusion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.cache import (  # noqa: E402
    cached_building_folder,
    cached_rule_defaults,
    cached_weather,
)
from app.analytics import (  # noqa: E402
    PLANT_AIR,
    PLANT_BOILER,
    PLANT_CHILLER,
    dataset_time_span,
    economizer_weather_summary,
    mech_cooling_coverage,
    mech_cooling_oat_bins,
    motor_run_hours_table,
    motor_run_hours_totals,
    motor_run_hours_weekly,
    sensor_fault_summary,
    sensor_health_matrix,
)
from app.charts import (  # noqa: E402
    bas_vs_web_oat_histogram,
    bas_vs_web_oat_overlay,
    energy_degree_day_scatter,
    equipment_inspection_chart,
    format_mech_cooling_coverage_display,
    max_plot_points,
    mech_cooling_oat_histogram,
    mech_cooling_runtime_message,
    mech_cooling_zero_eligible_warning,
    monthly_energy_bar,
    motor_weekly_runtime_chart,
    plotly_config,
    rule_result_chart,
    sensor_fault_chart,
)
from app.config import AppConfig  # noqa: E402
from app.dashboard_contract import REQUIRED_MAIN_SECTIONS  # noqa: E402
from app.data_loader import infer_poll_seconds, list_building_candidates, validate_dataframe  # noqa: E402
from app.occupancy import DAYS, DAY_LABELS, OccupancySchedule, apply_schedule_occ_mode, occupied_hours_per_week  # noqa: E402
from app.ui_rcx_tab import render_rcx_plots_tab  # noqa: E402
from app.unit_system import c_to_f, f_to_c, units_map_for_system  # noqa: E402
from app.mapping_wizard import (  # noqa: E402
    DEFAULT_BUILDING_ID,
    DEFAULT_SITE_ID,
    equipment_context,
    flat_role_map_from_sites,
    load_site_mapping,
    save_site_mapping,
    upsert_equipment_roles,
    wrap_flat_role_map,
)
from app.reports import results_summary_table, to_csv_bytes  # noqa: E402
from app import column_map_json as _column_map_json_mod  # noqa: E402
from app import role_map as _role_map_mod  # noqa: E402

FAMILY_ORDER = _column_map_json_mod.FAMILY_ORDER
LLM_COLUMN_MAP_PROMPT = _column_map_json_mod.LLM_COLUMN_MAP_PROMPT
build_column_map_from_equipment_frames = _column_map_json_mod.build_column_map_from_equipment_frames
build_llm_prompt_for_frames = _column_map_json_mod.build_llm_prompt_for_frames
column_map_to_role_map = _column_map_json_mod.column_map_to_role_map
family_label = _column_map_json_mod.family_label
load_column_map_json = _column_map_json_mod.load_column_map_json
merge_column_map_into_role_map = _column_map_json_mod.merge_column_map_into_role_map
natural_key = _column_map_json_mod.natural_key
normalize_column_map = _column_map_json_mod.normalize_column_map
save_column_map_json = _column_map_json_mod.save_column_map_json
to_haystack_document = _column_map_json_mod.to_haystack_document
validate_column_map_against_frames = _column_map_json_mod.validate_column_map_against_frames

apply_role_map = _role_map_mod.apply_role_map
enrich_role_map_from_equipment = _role_map_mod.enrich_role_map_from_equipment
load_role_map = _role_map_mod.load_role_map
roles_from_columns_csv = _role_map_mod.roles_from_columns_csv
save_role_map = _role_map_mod.save_role_map
suggest_roles = _role_map_mod.suggest_roles
from app.rules import CANONICAL_RULE_COUNT, RULES, RULES_BY_ID, run_rule  # noqa: E402
from app.rules.operational_gate import RULE_GATES  # noqa: E402
from app.rules.runner import infer_equipment_kind  # noqa: E402
from app.site_model import (  # noqa: E402
    EQUIPMENT_TYPES,
    Building,
    Site,
    resolve_equipment_type,
    stamp_equipment_type,
)

try:
    from shared.branding import APP_TITLE
except ImportError:  # pragma: no cover
    APP_TITLE = "Open FDD Vibe Coder"

st.set_page_config(page_title=APP_TITLE, layout="wide")

_AGENTS_MD_URL = (
    "https://github.com/bbartling/py-bacnet-stacks-playground/blob/develop/"
    "vibe_code_apps_19/AGENTS.md"
)
_OPENFDD_DOCS_URL = "https://bbartling.github.io/open-fdd/"
_OPENFDD_REPO_URL = "https://github.com/bbartling/open-fdd"
_HERO_IMG = APP_ROOT / "assets" / "image_new_chiller.png"


def _render_app_hero() -> None:
    """Brand header: title → subtitle → compact logo → how-it-works."""
    st.title(APP_TITLE)
    st.markdown(
        "Streamlit lab for Open-FDD: Load zip → central Feather store; Run Rules → DataFusion SQL. "
        "Rule-tuning sliders map to SQL registry params (confirm delay = confirm_min → confirm_seconds). "
        "CSVs stay as-is — you only map columns to roles."
    )
    if _HERO_IMG.is_file():
        # Narrower than full-bleed stretch so the logo sits under the brand, not above it
        _logo_l, _logo_m, _logo_r = st.columns([1, 2, 1])
        with _logo_m:
            st.image(str(_HERO_IMG), width="stretch")
    st.markdown(
        """
**How it works (2 pieces + run)**

1. **Data package** — Folder or `openfdd_package_v1` zip of historian CSVs  
2. **Data model** — JSON column→role map (Mapping tab) or `session_config.json` role_map in the zip  
3. **Run** — **Run Rules** → **FDD Plots** / **RCx Plots**
        """.strip()
    )
    st.markdown(
        f"[AGENTS.md]({_AGENTS_MD_URL}) · "
        f"[Open-FDD docs]({_OPENFDD_DOCS_URL}) · "
        f"[Open-FDD repo]({_OPENFDD_REPO_URL})"
    )


_render_app_hero()


def _empty_state_directions() -> None:
    st.info(
        "**Start here:** sidebar → **Building package zip(s)** (or Folder locally). "
        "Each equipment CSV needs a sibling Haystack map JSON. Then **Run Rules** → **FDD Plots** / **RCx**."
    )
    st.markdown(
        f"Agent brief: [AGENTS.md]({_AGENTS_MD_URL}) · "
        f"Package contract: `docs/PACKAGE_SPEC.md` · "
        f"[Open-FDD docs]({_OPENFDD_DOCS_URL})"
    )


@st.cache_data
def load_inventory(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _init_state() -> None:
    cfg = AppConfig.load()
    if "site_mapping" not in st.session_state:
        st.session_state.site_mapping = load_site_mapping(cfg.role_map_path)
    demo_building = cfg.data_root / cfg.building_id
    if demo_building.is_dir():
        default_folder = str(demo_building)
    elif cfg.data_root.is_dir():
        default_folder = str(cfg.data_root)
    else:
        default_folder = ""
    for k, v in {
        "equipment_frames": {},
        "selected_equipment": None,
        "batch_results": [],
        "prerun_status": "",
        "package_warnings": [],
        "params": {},
        "engineer_notes": {},
        "role_map": flat_role_map_from_sites(st.session_state.site_mapping),
        "weather": None,
        "building_id": "",
        "site_id": DEFAULT_SITE_ID,
        "building_folder": "" if (cfg.is_cloud or not cfg.allow_server_paths) else default_folder,
        "data_root": str(cfg.data_root),
        "data_source": "",
        "column_map": {},
        "column_map_path": "",
        "vav_to_ahu": {},
        "require_operational_gates": True,
        "unit_system": "imperial",
        "prefer_web_oat": True,
        "chw_leave_max_f": 48.0,
        "use_mech_cooling_status_proof": True,
        "include_ahu_chw_valve": False,  # hard-coded; never offer in UI
        "occupancy_schedule": OccupancySchedule().to_dict(),
        "apply_occupancy_calendar": True,  # always on; Overview calendar → occ_mode
        "zone_lo_f": 70.0,
        "zone_hi_f": 75.0,
        "upload_workdir": None,
        "package_report": None,
        "zip_uploader_key": 0,
        "fault_settings_source": "defaults",
        "session_config_source": "",
        "bootstrap_applied": False,
        "bootstrap_status": "",
        "mapping_rev": "",
        "rules_mapping_rev": "",
        "mapping_stale": False,
    }.items():
        st.session_state.setdefault(k, v)


def _apply_agent_bootstrap_once() -> None:
    """Load ``VIBE19_BOOTSTRAP`` / ``.last_agent_session.json`` into this browser session once."""
    if st.session_state.get("bootstrap_applied"):
        return
    if st.session_state.get("equipment_frames"):
        # User already has data — don't clobber
        st.session_state.bootstrap_applied = True
        return
    try:
        from app.bootstrap import read_bootstrap
        from app.package_io import PackageError, SessionConfig, apply_session_config, load_package_zip
    except Exception as exc:  # pragma: no cover
        st.session_state.bootstrap_status = f"bootstrap import failed: {exc}"
        st.session_state.bootstrap_applied = True
        return

    try:
        boot = read_bootstrap()
    except Exception as exc:
        st.session_state.bootstrap_status = f"bootstrap read failed: {exc}"
        st.session_state.bootstrap_applied = True
        return
    if not boot:
        st.session_state.bootstrap_applied = True
        return

    pkg = boot.get("package_path")
    folder = boot.get("building_folder")
    try:
        if pkg and Path(str(pkg)).is_file():
            result = load_package_zip(Path(str(pkg)).read_bytes())
            # Keep a stable source label for the UI
            result.report["bootstrap_package"] = str(pkg)
            _commit_package_result(result)
            st.session_state.data_source = f"bootstrap:{Path(str(pkg)).name}"
        elif folder and Path(str(folder)).is_dir():
            from app.cache import cached_building_folder, cached_weather

            chosen = Path(str(folder))
            frames = cached_building_folder(str(chosen.resolve()))
            weather = None
            try:
                weather = cached_weather(str(chosen.parent), "weather")
            except Exception:
                weather = None
            _commit_frames(
                frames,
                site_id=st.session_state.site_id or DEFAULT_SITE_ID,
                building_id=chosen.name,
                source=f"bootstrap:{chosen.name}",
                weather=weather,
            )
            st.session_state.building_folder = str(chosen)
            st.session_state.data_input_mode = "Folder"
        else:
            # Missing host paths (typical Docker) — stay on Zip; do not prefill dead Folder paths
            st.session_state.building_folder = ""
            if st.session_state.get("data_input_mode") == "Folder":
                st.session_state.data_input_mode = "Zip package"
            st.session_state.bootstrap_status = (
                "Bootstrap path not on this host — upload a zip package (or mount data + APP_MODE=local)."
            )
            st.session_state.bootstrap_applied = True
            return

        # Overlay dialed-in session / fault settings from agent export
        sess = boot.get("session_config") or {}
        fs_path = boot.get("fault_settings_path")
        if fs_path and Path(str(fs_path)).is_file():
            raw = json.loads(Path(str(fs_path)).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                params = dict(st.session_state.get("params") or {})
                for rid, p in raw.items():
                    if isinstance(p, dict):
                        params[str(rid)] = {**params.get(str(rid), {}), **p}
                st.session_state.params = params
                st.session_state.fault_settings_source = f"bootstrap:{Path(str(fs_path)).name}"
                sess = {**sess, "params": params}
        if sess:
            cfg_obj = SessionConfig.model_validate(
                {**sess, "schema_version": sess.get("schema_version") or "openfdd_session_v1"}
            )
            frames = st.session_state.get("equipment_frames") or {}
            for w in apply_session_config(cfg_obj, equipment_ids=set(frames)):
                st.warning(w)
            st.session_state.session_config_source = "bootstrap"

        cm_path = boot.get("column_map_path")
        if cm_path and Path(str(cm_path)).is_file():
            data = load_column_map_json(str(cm_path))
            _apply_column_map_json(data)
            st.session_state.column_map_path = str(cm_path)

        if boot.get("auto_run_rules") and st.session_state.get("equipment_frames"):
            import os as _os

            if (_os.environ.get("VIBE19_BOOTSTRAP_SKIP_RULES") or "").strip() in {"1", "true", "yes"}:
                st.session_state.bootstrap_status = (
                    "Loaded bootstrap (data + settings); rules skipped (VIBE19_BOOTSTRAP_SKIP_RULES)"
                )
            else:
                frames = st.session_state.equipment_frames
                st.session_state.batch_results = _run_rule_list(sorted(frames), RULES, frames)
                st.session_state.bootstrap_status = (
                    f"Loaded bootstrap + ran {len(st.session_state.batch_results)} rule evaluations"
                )
        else:
            st.session_state.bootstrap_status = "Loaded bootstrap (data + settings); run rules when ready"
    except PackageError as exc:
        st.session_state.bootstrap_status = f"bootstrap package error: {exc}"
    except Exception as exc:
        st.session_state.bootstrap_status = f"bootstrap failed: {exc}"
    finally:
        st.session_state.bootstrap_applied = True


def _clear_uploaded_session() -> None:
    """Wipe temp package dir + session data derived from an upload."""
    from app.browser_session import clear_browser_session_pointer
    from app.package_io import wipe_workdir

    wipe_workdir(st.session_state.get("upload_workdir"))
    clear_browser_session_pointer()
    st.session_state.upload_workdir = None
    st.session_state.package_report = None
    st.session_state.equipment_frames = {}
    st.session_state.weather = None
    st.session_state.batch_results = []
    st.session_state.selected_equipment = None
    st.session_state.data_source = ""
    st.session_state.building_id = ""
    st.session_state.pop("central_dataset_id", None)
    # Rotate uploader widget so Streamlit drops cached file bytes
    st.session_state.zip_uploader_key = int(st.session_state.get("zip_uploader_key", 0)) + 1


def _delete_dataset_and_clear() -> None:
    """Delete Feather/parquet/csv data for the loaded Haystack building id; keep session (sliders, maps)."""
    from app import central_client

    dataset_id = (
        st.session_state.get("central_dataset_id")
        or st.session_state.get("building_id")
        or ""
    ).strip()
    if not dataset_id:
        st.sidebar.warning("No Haystack / building id loaded — nothing to delete on central")
        return
    result = central_client.delete_dataset(dataset_id)
    if result.get("central_down"):
        st.sidebar.warning(result.get("error") or "central unreachable")
        return
    if not result.get("ok", False):
        st.sidebar.warning(result.get("error") or f"delete failed for `{dataset_id}`")
        return
    # Drop in-memory history only — retain params, role_map, unit_system, fault sliders.
    from app.browser_session import clear_browser_session_pointer
    from app.package_io import wipe_workdir

    wipe_workdir(st.session_state.get("upload_workdir"))
    clear_browser_session_pointer()
    st.session_state.upload_workdir = None
    st.session_state.package_report = None
    st.session_state.equipment_frames = {}
    st.session_state.weather = None
    st.session_state.batch_results = []
    st.session_state.selected_equipment = None
    st.session_state.data_source = ""
    st.session_state.building_id = ""
    st.session_state.pop("central_dataset_id", None)
    st.session_state.zip_uploader_key = int(st.session_state.get("zip_uploader_key", 0)) + 1
    st.sidebar.success(f"Deleted dataset `{dataset_id}` (session / fault sliders kept)")


def _push_package_to_central(zip_bytes: bytes, filename: str = "package.zip") -> None:
    """Ingest zip into central Feather + parquet; required for SQL FDD."""
    from app import central_client

    result = central_client.post_package_zip(zip_bytes, filename=filename)
    if result.get("central_down"):
        st.sidebar.error(result.get("error") or "central unreachable — SQL FDD needs central")
        return
    if not result.get("ok", False):
        st.sidebar.error(f"central ingest: {result.get('error') or result}")
        return
    building_id = str(result.get("building_id") or st.session_state.get("building_id") or "")
    if building_id:
        st.session_state.central_dataset_id = building_id
        st.session_state.building_id = building_id
    feather_n = result.get("feather_files") or result.get("feather_written")
    note = f" · feather×{feather_n}" if feather_n is not None else ""
    st.sidebar.caption(
        f"Central Feather/SQL store: `{building_id}` · {result.get('equipment_written', '?')} equip · "
        f"{result.get('total_rows', '?')} rows{note}"
    )


def _sql_rows_to_rule_results(rows: list, rule_meta: dict[str, object] | None = None) -> list:
    """Adapt central DataFusion result rows into RuleResult for existing Streamlit tables/plots."""
    from app.rules.base import RuleResult

    meta = rule_meta or {r.id: r for r in RULES}
    out: list = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("rule_id") or "")
        eq = str(row.get("equipment_id") or "")
        if not rid or not eq:
            continue
        rule = meta.get(rid)
        title = str(row.get("title") or (getattr(rule, "title", "") if rule else "") or rid)
        status = str(row.get("status") or "PASS")
        fh = row.get("fault_hours")
        fp = row.get("fault_pct")
        notes = row.get("notes")
        if notes is not None and not isinstance(notes, str):
            notes = str(notes)
        out.append(
            RuleResult(
                rule_id=rid,
                equipment_id=eq,
                status=status,  # type: ignore[arg-type]
                applicable=status not in {"NOT_APPLICABLE_EQUIPMENT_TYPE"},
                equipment_type=str(row.get("equipment_type") or ""),
                building_id=str(st.session_state.get("building_id") or ""),
                missing_roles=list(row.get("missing_roles") or []),
                fault_hours=float(fh) if fh is not None else None,
                fault_pct=float(fp) if fp is not None else None,
                notes=notes or f"DataFusion SQL · {title}",
            )
        )
    return out


def _run_rule_list(
    eq_ids: list[str],
    rules: list,
    frames: dict[str, pd.DataFrame],
) -> list:
    """Run FDD via central DataFusion SQL (Feather/parquet store) — no pandas rule math."""
    from app import central_client

    _ = frames  # frames still used for Overview/plots UI; FDD engine is SQL
    rule_ids = [r.id for r in rules]
    params: dict[str, dict[str, float]] = {}
    raw_params = st.session_state.get("params") or {}
    for rid in rule_ids:
        p = raw_params.get(rid)
        if isinstance(p, dict) and p:
            params[rid] = {str(k): float(v) for k, v in p.items() if isinstance(v, (int, float))}
    equipment_id = eq_ids[0] if len(eq_ids) == 1 else None
    body = central_client.run_fdd(rule_ids=rule_ids, params=params or None, equipment_id=equipment_id)
    if not body.get("ok", False):
        err = body.get("error") or "SQL FDD run failed"
        st.error(err)
        return []
    rows = body.get("results") or []
    if not isinstance(rows, list):
        rows = []
    # If API omitted embedded results, fetch cache.
    if not rows:
        cached = central_client.fdd_results()
        rows = cached.get("results") or []
    allow = set(eq_ids)
    if allow:
        rows = [r for r in rows if isinstance(r, dict) and r.get("equipment_id") in allow]
    meta = {r.id: r for r in rules}
    return _sql_rows_to_rule_results(rows, meta)


def _apply_browser_autoload_once() -> None:
    """Reload last zip package from disk pointer if session_state was wiped by a refresh."""
    if st.session_state.get("_browser_autoload_done"):
        return
    st.session_state._browser_autoload_done = True
    if st.session_state.get("equipment_frames"):
        return
    try:
        from app.browser_session import (
            browser_autoload_enabled,
            pointer_paths_exist,
            read_browser_session_pointer,
            touch_path,
        )
        from app.package_io import PackageError, load_package_from_dir
    except Exception as exc:  # pragma: no cover
        st.session_state.bootstrap_status = (
            (st.session_state.get("bootstrap_status") or "") + f" · browser autoload import failed: {exc}"
        ).strip(" ·")
        return

    if not browser_autoload_enabled():
        return

    pointer = read_browser_session_pointer()
    if not pointer or not pointer_paths_exist(pointer):
        return
    workdir = Path(str(pointer["workdir"]))
    building_root = Path(str(pointer["building_root"]))
    try:
        touch_path(workdir)
        result = load_package_from_dir(building_root, workdir=workdir)
        result.report["source"] = "browser_autoload"
        result.report["autoload_building_id"] = pointer.get("building_id") or ""
        _commit_package_result(result)
        # Preserve original source label when available
        if pointer.get("source"):
            st.session_state.data_source = str(pointer["source"])
        st.session_state.bootstrap_status = (
            (st.session_state.get("bootstrap_status") or "")
            + f" · Restored last upload (`{pointer.get('building_id') or building_root.name}`) — "
            "survives refresh until **Delete dataset**"
        ).strip(" ·")
    except PackageError as exc:
        from app.browser_session import clear_browser_session_pointer

        clear_browser_session_pointer()
        st.session_state.bootstrap_status = (
            (st.session_state.get("bootstrap_status") or "") + f" · browser autoload failed: {exc}"
        ).strip(" ·")
    except Exception as exc:
        st.session_state.bootstrap_status = (
            (st.session_state.get("bootstrap_status") or "") + f" · browser autoload error: {exc}"
        ).strip(" ·")


def _session_config_payload() -> dict:
    """Build ``openfdd_session_v1`` from current session_state (Cloud-safe export)."""
    from app.agent_api import make_session_config

    return make_session_config(
        st.session_state.get("role_map") or {},
        st.session_state.get("params") or {},
        unit_system=st.session_state.get("unit_system", "imperial"),
        prefer_web_oat=bool(st.session_state.get("prefer_web_oat", True)),
        chw_leave_max_f=float(st.session_state.get("chw_leave_max_f", 48.0)),
        use_mech_cooling_status_proof=bool(
            st.session_state.get("use_mech_cooling_status_proof", True)
        ),
        include_ahu_chw_valve=False,  # never export legacy valve→mech-cooling path
    )


def _build_wattlab_dump_zip(*, profile: str = "summary") -> tuple[bytes, str]:
    """Run a complete cookbook + agent-bundle export and zip it (in memory).

    Always re-runs the full active cookbook across all mapped equipment so the
    dump never reuses a partial session `batch_results` set. The fresh complete
    result set replaces session `batch_results` for vibe20 handoff.
    """
    import io
    import tempfile
    import zipfile

    from app.agent_api import AgentDataset, export_agent_bundle, run_rules

    building_id = st.session_state.get("building_id") or "BUILDING"
    dataset = AgentDataset(
        building_id=building_id,
        frames=st.session_state.get("equipment_frames") or {},
        weather=st.session_state.get("weather"),
        role_map=st.session_state.get("role_map") or {},
        params=st.session_state.get("params") or {},
        unit_system=st.session_state.get("unit_system", "imperial"),
        prefer_web_oat=bool(st.session_state.get("prefer_web_oat", True)),
        chw_leave_max_f=float(st.session_state.get("chw_leave_max_f", 48.0)),
        use_mech_cooling_status_proof=bool(
            st.session_state.get("use_mech_cooling_status_proof", True)
        ),
        column_map=st.session_state.get("column_map"),
        package_report=st.session_state.get("package_report") or {},
        source_path=str(st.session_state.get("data_source") or ""),
    )
    # Never reuse potentially partial session results for the vibe20 handoff.
    run = run_rules(dataset)
    st.session_state["batch_results"] = run.results
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="wattlab_dump_") as td:
        export_agent_bundle(
            dataset,
            run,
            td,
            include_bootstrap=False,
            profile=profile,
        )
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(Path(td).rglob("*")):
                if p.is_file():
                    # Spec: forward-slash arcnames (PACKAGE_SPEC.md)
                    zf.write(p, arcname=p.relative_to(td).as_posix())
    return buf.getvalue(), f"wattlab_dump_{building_id}.zip"


def _apply_session_config_bytes(raw: bytes, *, source_label: str) -> list[str]:
    """Validate + apply session_config JSON bytes into session_state. Returns warnings."""
    from app.package_io import SessionConfig, apply_session_config

    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("session_config JSON must be an object")
    if not data.get("schema_version"):
        data = {**data, "schema_version": "openfdd_session_v1"}
    cfg_obj = SessionConfig.model_validate(data)
    frames = st.session_state.get("equipment_frames") or {}
    warnings = apply_session_config(cfg_obj, equipment_ids=set(frames))
    st.session_state.session_config_source = source_label
    if cfg_obj.params:
        st.session_state.fault_settings_source = f"session:{source_label}"
    return warnings


def _render_session_config_io(*, key_prefix: str) -> None:
    """Download / upload tuned session_config (+ distinct fault_settings) — no server path."""
    st.caption(
        f"Active fault settings: `{st.session_state.get('fault_settings_source') or 'defaults'}`"
    )
    if st.session_state.get("session_config_source"):
        st.caption(f"Session config: `{st.session_state.session_config_source}`")

    try:
        session_payload = _session_config_payload()
    except Exception as exc:
        st.warning(f"Session config export unavailable: {exc}")
        session_payload = {
            "schema_version": "openfdd_session_v1",
            "unit_system": st.session_state.get("unit_system", "imperial"),
            "prefer_web_oat": bool(st.session_state.get("prefer_web_oat", True)),
            "use_mech_cooling_status_proof": bool(
                st.session_state.get("use_mech_cooling_status_proof", True)
            ),
            "role_map": st.session_state.get("role_map") or {},
            "params": st.session_state.get("params") or {},
        }

    st.download_button(
        "Download session config",
        data=json.dumps(session_payload, indent=2).encode("utf-8"),
        file_name="session_config.json",
        mime="application/json",
        key=f"{key_prefix}_dl_session_config",
        help="openfdd_session_v1: units, prefer_web_oat, role_map, params, plant toggles.",
    )
    fault_json = json.dumps(st.session_state.get("params") or {}, indent=2)
    st.download_button(
        "Download fault settings",
        data=fault_json.encode("utf-8"),
        file_name="fault_settings.json",
        mime="application/json",
        key=f"{key_prefix}_dl_fault_settings",
        help="rule_id → params only (subset of session_config.params).",
    )

    up_sess = st.file_uploader(
        "Upload session config",
        type=["json"],
        key=f"{key_prefix}_upload_session_config",
        help="Restore params + role_map into this browser session (Cloud-safe).",
    )
    if up_sess is not None and st.button(
        "Apply uploaded session config", key=f"{key_prefix}_apply_session_upload"
    ):
        try:
            warnings = _apply_session_config_bytes(
                up_sess.getvalue(), source_label=f"upload:{up_sess.name}"
            )
            for w in warnings:
                st.warning(w)
            st.success("Session config applied — re-run rules to refresh results.")
            st.rerun()
        except Exception as exc:
            st.error(f"Session config upload failed: {exc}")

    up_fault = st.file_uploader(
        "Upload fault settings",
        type=["json"],
        key=f"{key_prefix}_upload_fault_settings",
    )
    if up_fault is not None and st.button(
        "Apply uploaded fault settings", key=f"{key_prefix}_apply_fault_upload"
    ):
        try:
            raw = json.loads(up_fault.getvalue().decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("JSON must be an object of rule_id → params")
            params = dict(st.session_state.get("params") or {})
            for rid, p in raw.items():
                if isinstance(p, dict):
                    params[str(rid)] = {**params.get(str(rid), {}), **p}
            st.session_state.params = params
            st.session_state.fault_settings_source = f"upload:{up_fault.name}"
            st.success("Fault settings applied — re-run rules to refresh results.")
            st.rerun()
        except Exception as exc:
            st.error(f"Fault settings upload failed: {exc}")


def _sync_role_map_from_sites() -> None:
    st.session_state.role_map = flat_role_map_from_sites(st.session_state.site_mapping)


def _role_map_fingerprint(role_map: dict | None = None) -> str:
    """Stable hash of equipment→role→column mappings (ignores meta keys)."""
    import hashlib
    import json

    rm = role_map if role_map is not None else st.session_state.get("role_map") or {}
    cleaned: dict[str, dict[str, str]] = {}
    for eq_id, roles in sorted((rm or {}).items()):
        if not isinstance(roles, dict):
            continue
        cleaned[str(eq_id)] = {
            str(k): str(v)
            for k, v in sorted(roles.items())
            if k not in {"equipment_type", "plant_group"} and v
        }
    blob = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _commit_role_map_edit(equipment_id: str, roles: dict[str, str]) -> bool:
    """Apply in-session role edits, sync sites/frame attrs, invalidate stale results.

    Returns True when the mapping actually changed.
    """
    prev = _role_map_fingerprint()
    clean = {k: v for k, v in roles.items() if v}
    etype = resolve_equipment_type(
        equipment_id,
        role_map=st.session_state.role_map,
        column_map=st.session_state.get("column_map"),
        sites=st.session_state.site_mapping,
    )
    meta = dict(st.session_state.role_map.get(equipment_id) or {})
    # Drop previous role keys then apply clean map (keep equipment_type/plant_group).
    keep_meta = {k: meta[k] for k in ("equipment_type", "plant_group") if k in meta}
    keep_meta["equipment_type"] = etype
    st.session_state.role_map[equipment_id] = {**keep_meta, **clean}
    upsert_equipment_roles(
        st.session_state.site_mapping,
        site_id=st.session_state.site_id or DEFAULT_SITE_ID,
        building_id=st.session_state.building_id or "BUILDING",
        equipment_id=equipment_id,
        equipment_type=etype,
        roles=clean,
    )
    _sync_role_map_from_sites()
    # Re-apply this equipment's edit after sync (sites flatten may drop in-session-only keys).
    synced = dict(st.session_state.role_map.get(equipment_id) or {})
    synced.update(clean)
    synced["equipment_type"] = etype
    st.session_state.role_map[equipment_id] = synced
    if st.session_state.equipment_frames:
        _attach_frames_meta(st.session_state.equipment_frames)
    new_fp = _role_map_fingerprint()
    st.session_state.mapping_rev = new_fp
    if new_fp != prev:
        # Drop cached results for this equipment so FDD Plots re-evaluate.
        st.session_state.batch_results = [
            r for r in st.session_state.batch_results if getattr(r, "equipment_id", None) != equipment_id
        ]
        st.session_state.mapping_stale = True
        st.session_state.rules_mapping_rev = ""
        return True
    return False


def _apply_column_map_json(data: dict) -> None:
    """Merge JSON column map into session role_map + site mapping."""
    normalized = normalize_column_map(data)
    st.session_state.column_map = normalized
    st.session_state.role_map = merge_column_map_into_role_map(
        st.session_state.role_map, normalized, prefer_json=True
    )
    for eq_id, block in (normalized.get("equipment") or {}).items():
        roles = dict(block.get("column_roles") or {})
        etype = resolve_equipment_type(
            eq_id,
            role_map=st.session_state.role_map,
            column_map=normalized,
            explicit=str(block.get("equipment_type") or ""),
        )
        # Persist type in role_map meta for session_config round-trip
        meta = dict(st.session_state.role_map.get(eq_id) or {})
        meta.update(roles)
        meta["equipment_type"] = etype
        st.session_state.role_map[eq_id] = meta
        upsert_equipment_roles(
            st.session_state.site_mapping,
            site_id=st.session_state.site_id,
            building_id=st.session_state.building_id,
            equipment_id=eq_id,
            equipment_type=etype,
            roles=roles,
        )
    _sync_role_map_from_sites()
    if st.session_state.equipment_frames:
        _attach_frames_meta(st.session_state.equipment_frames)


def _rules_by_family() -> dict[str, list]:
    buckets: dict[str, list] = {f: [] for f in FAMILY_ORDER}
    for rule in RULES:
        fam = rule.family if rule.family in buckets else "other"
        buckets[fam].append(rule)
    for fam in buckets:
        buckets[fam].sort(key=lambda r: natural_key(r.id))
    return buckets


def _results_by_family(summary: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if summary.empty:
        return {}
    out: dict[str, pd.DataFrame] = {}
    fam_lookup = {r.id: r.family for r in RULES}
    df = summary.copy()
    df["family"] = df["rule_id"].map(lambda rid: fam_lookup.get(rid, "other"))
    for fam in FAMILY_ORDER:
        part = df[df["family"] == fam].copy()
        if part.empty:
            continue
        part = part.loc[
            sorted(
                part.index,
                key=lambda i: (natural_key(str(part.at[i, "rule_id"])), str(part.at[i, "equipment_id"])),
            )
        ]
        out[fam] = part
    return out


_STATUS_SORT = {
    "FAULT": 0,
    "WARNING": 1,
    "PASS": 2,
    "SKIPPED_MISSING_ROLES": 3,
    "SKIPPED_EQUIPMENT_OFF": 4,
    "ERROR": 5,
    "NOT_APPLICABLE_EQUIPMENT_TYPE": 6,
    "NOT_RUN": 7,
}


def _device_results_table(summary: pd.DataFrame, equipment_id: str) -> pd.DataFrame:
    """Compact per-device results: FAULT/PASS first, N/A last; include rule title."""
    part = summary[summary["equipment_id"] == equipment_id].copy()
    if part.empty:
        return part
    titles = {r.id: r.title for r in RULES}
    fams = {r.id: r.family for r in RULES}
    part["title"] = part["rule_id"].map(lambda rid: titles.get(str(rid), ""))
    part["rule_family"] = part["rule_id"].map(lambda rid: fams.get(str(rid), "other"))
    # natural_key returns a list — cannot use sort_values on list cells (unhashable).
    part = part.loc[
        sorted(
            part.index,
            key=lambda i: (
                _STATUS_SORT.get(str(part.at[i, "status"]), 99),
                natural_key(str(part.at[i, "rule_id"])),
            ),
        )
    ]
    cols = [
        "rule_id",
        "title",
        "rule_family",
        "status",
        "fault_hours",
        "fault_pct",
        "oat_mean_abs_diff_f",
        "oat_max_abs_diff_f",
        "missing_roles",
        "notes",
    ]
    out = part[[c for c in cols if c in part.columns]].reset_index(drop=True)
    # OAT-METEO: % of window is not meaningful (always-gate); show mean/max °F deviation.
    if "rule_id" in out.columns and "fault_pct" in out.columns:
        oat_mask = out["rule_id"].astype(str) == "OAT-METEO"
        if oat_mask.any():
            out.loc[oat_mask, "fault_pct"] = pd.NA
    return out


def _status_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "status" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df["status"].value_counts().items()}


def _attach_frames_meta(frames: dict[str, pd.DataFrame]) -> None:
    rm = st.session_state.role_map
    cm = st.session_state.get("column_map")
    sites = st.session_state.site_mapping
    for eq_id, df in frames.items():
        sid, bid, etype = equipment_context(sites, eq_id)
        df.attrs.setdefault("site_id", sid)
        df.attrs.setdefault("building_id", bid)
        stamp_equipment_type(
            df,
            eq_id,
            role_map=rm,
            column_map=cm if isinstance(cm, dict) else None,
            sites=sites,
            explicit=etype,
        )
        # Optional plant_group meta from role_map
        pg = (rm.get(eq_id) or {}).get("plant_group")
        if pg:
            df.attrs["plant_group"] = str(pg)
        df.attrs["_role_map"] = rm


_CONFIRM_META = {
    "label": "Fault confirm delay",
    "default": 5.0,
    "min": 0.0,
    "max": 60.0,
    "step": 1.0,
    "unit": "min",
    "direction": "fewer",
    "help": (
        "Minutes a raw fault must persist before it is confirmed. "
        "Default matches each rule's declared confirm window; 0 = first sample; max 60. "
        "Increasing this usually flags fewer faults."
    ),
}


def _direction_help(meta: dict) -> str:
    help_txt = str(meta.get("help") or meta.get("label") or "")
    direction = str(meta.get("direction") or "")
    if direction == "fewer" and "fewer faults" not in help_txt.lower():
        help_txt = (help_txt + " — increasing this usually flags fewer faults.").strip(" —")
    elif direction == "stricter" and "more faults" not in help_txt.lower():
        help_txt = (
            help_txt + " — increasing this usually flags more faults (stricter / wider detection)."
        ).strip(" —")
    return help_txt


@st.fragment
def _render_sv_rate_config() -> None:
    """Grouped profile editor for SV-RATE (screening defaults — not code limits)."""
    from app.rules.sensor_rate_profiles import (
        DEFAULT_PROFILES,
        c_per_h_to_f_per_h,
        f_per_h_to_c_per_h,
        profiles_by_quantity,
    )

    st.info(
        "These thresholds are configurable engineering screening defaults. They are not "
        "universal code limits and should be tuned to equipment, sensor response, sampling "
        "interval, and site operation."
    )
    metric = st.session_state.get("unit_system", "imperial") == "metric"
    params = st.session_state.setdefault("params", {})
    rp_in = dict(params.get("SV-RATE") or {})
    c1, c2, c3 = st.columns(3)
    persistence_min = c1.number_input(
        "Default persistence (min)",
        min_value=5.0,
        max_value=60.0,
        value=float(rp_in.get("persistence_min", 10.0)),
        step=1.0,
        key="svrate_persist",
    )
    transition_window_min = c2.number_input(
        "Default transition window (min)",
        min_value=5.0,
        max_value=60.0,
        value=float(rp_in.get("transition_window_min", 20.0)),
        step=5.0,
        key="svrate_trans",
    )
    missing_state_fallback = c3.selectbox(
        "Missing operating-state fallback",
        ["conservative_steady", "skip_point"],
        index=0 if rp_in.get("missing_state_fallback", "conservative_steady") == "conservative_steady" else 1,
        key="svrate_fallback",
        help="When fan/pump proof is missing, use reduced-confidence steady thresholds (default).",
    )
    by_q = profiles_by_quantity()
    labels = {
        "temperature": "Temperature",
        "relative_humidity": "Humidity",
        "co2": "CO₂",
        "air_pressure": "Air pressure",
        "hydronic_pressure": "Hydronic pressure",
        "flow": "Flow",
        "command_position": "Commands / positions",
    }
    profile_overrides: dict[str, float] = {}
    for qty, title in labels.items():
        profiles = by_q.get(qty) or []
        if not profiles:
            continue
        with st.expander(title, expanded=False):
            rows = []
            for p in profiles:
                sw_c, sf_c, tw_c, tf_c = (
                    p.steady_warning_per_hour,
                    p.steady_fault_per_hour,
                    p.transient_warning_per_hour,
                    p.transient_fault_per_hour,
                )
                prefix = f"svrate__{p.profile_id}__"
                # Stored values are always canonical (°F/h for temperature).
                sw_s = float(rp_in.get(prefix + "steady_warning_per_hour", sw_c))
                sf_s = float(rp_in.get(prefix + "steady_fault_per_hour", sf_c))
                tw_s = float(rp_in.get(prefix + "transient_warning_per_hour", tw_c))
                tf_s = float(rp_in.get(prefix + "transient_fault_per_hour", tf_c))
                unit = p.canonical_unit
                if metric and qty == "temperature":
                    sw_d, sf_d, tw_d, tf_d = map(f_per_h_to_c_per_h, (sw_s, sf_s, tw_s, tf_s))
                    unit = "°C/h"
                else:
                    sw_d, sf_d, tw_d, tf_d = sw_s, sf_s, tw_s, tf_s
                rows.append(
                    {
                        "profile_id": p.profile_id,
                        "unit": unit,
                        "steady_warning": sw_d,
                        "steady_fault": sf_d,
                        "transient_warning": tw_d,
                        "transient_fault": tf_d,
                        "persist_min": int(rp_in.get(prefix + "persistence_minutes", p.persistence_minutes)),
                    }
                )
            edited = st.data_editor(
                pd.DataFrame(rows),
                hide_index=True,
                use_container_width=True,
                key=f"svrate_editor_{qty}",
                disabled=["profile_id", "unit"],
            )
            for _, row in edited.iterrows():
                pid = str(row["profile_id"])
                base = DEFAULT_PROFILES[pid]
                prefix = f"svrate__{pid}__"
                sw = float(row["steady_warning"])
                sf = float(row["steady_fault"])
                tw = float(row["transient_warning"])
                tf = float(row["transient_fault"])
                if metric and qty == "temperature":
                    sw, sf, tw, tf = map(c_per_h_to_f_per_h, (sw, sf, tw, tf))
                persist = int(row["persist_min"])
                candidates = {
                    "steady_warning_per_hour": sw,
                    "steady_fault_per_hour": sf,
                    "transient_warning_per_hour": tw,
                    "transient_fault_per_hour": tf,
                    "persistence_minutes": float(persist),
                }
                for key, val in candidates.items():
                    default_v = float(getattr(base, key))
                    if abs(val - default_v) > 1e-9:
                        profile_overrides[prefix + key] = val
    rp_out: dict = {
        "persistence_min": float(persistence_min),
        "transition_window_min": float(transition_window_min),
        "missing_state_fallback": missing_state_fallback,
    }
    for k, v in rp_in.items():
        if k.startswith("svrate__"):
            continue
        if k in {"persistence_min", "transition_window_min", "missing_state_fallback"}:
            continue
        rp_out[k] = v
    rp_out.update(profile_overrides)

    b1, b2 = st.columns(2)
    if b1.button("Restore SV-RATE defaults", key="svrate_restore"):
        params.pop("SV-RATE", None)
        st.session_state.params = params
        for k in list(st.session_state.keys()):
            if str(k).startswith("svrate_"):
                del st.session_state[k]
        st.rerun()
    params["SV-RATE"] = rp_out
    st.session_state.params = params
    if b2.download_button(
        "Export SV-RATE config JSON",
        data=json.dumps({"SV-RATE": rp_out}, indent=2),
        file_name="sv_rate_config.json",
        mime="application/json",
        key="svrate_export",
    ):
        pass
    frames = st.session_state.get("equipment_frames") or {}
    selected = st.session_state.get("selected_equipment")
    if selected and selected in frames:
        from app.rules.sensor_rate_profiles import ROLE_TO_PROFILE, resolve_profile

        mapped = apply_role_map(frames[selected], selected, st.session_state.get("role_map") or {})
        peek = []
        for role in ROLE_TO_PROFILE:
            if role in mapped.columns and mapped[role].notna().any():
                prof, src = resolve_profile(role=role)
                if prof:
                    peek.append(
                        {
                            "role": role,
                            "profile_id": prof.profile_id,
                            "source": src,
                            "steady_fault": prof.steady_fault_per_hour,
                            "unit": prof.canonical_unit,
                        }
                    )
        if peek:
            st.caption(f"Resolved profiles on **{selected}** (after next Run):")
            st.dataframe(pd.DataFrame(peek), hide_index=True, use_container_width=True)


@st.fragment
def _sidebar_sliders(defaults_cfg: dict) -> None:
    """Left-rail rule tuning. Fragment-isolated so slider moves do not re-run rules/plots."""
    out = dict(st.session_state.params)
    st.sidebar.subheader("Rule tuning")
    st.sidebar.caption(
        "Sliders only change thresholds. Rules update when you click **Run** (Run Rules tab) or **Rerun cat.**"
    )
    st.session_state.require_operational_gates = st.sidebar.checkbox(
        "Require operational proof (fan/pump status)",
        value=st.session_state.get("require_operational_gates", True),
        help=(
            "When checked, RUN rules only evaluate while fan/pump/compressor is proven on "
            "(status preferred over command). Off-period samples become SKIPPED_EQUIPMENT_OFF, not PASS."
        ),
        key="ops_gate_global",
    )
    fam_labels = [family_label(f) for f in FAMILY_ORDER if _rules_by_family().get(f)]
    fam_pick = st.sidebar.selectbox(
        "Category",
        ["(all)"] + fam_labels,
        key="tune_fam",
    )
    fam_lookup = {family_label(f): f for f in FAMILY_ORDER}
    allow_ids = None
    fam_key = None
    if fam_pick != "(all)":
        fam_key = fam_lookup[fam_pick]
        allow_ids = {r.id for r in _rules_by_family().get(fam_key, [])}

    for rule in RULES:
        if allow_ids is not None and rule.id not in allow_ids:
            continue
        block = dict(defaults_cfg.get(rule.id, {}))
        # Prefer live catalog defaults (confirm_min synced to confirm_seconds).
        for p in rule.params:
            meta = dict(block.get(p.key) or {})
            meta.setdefault("label", p.label)
            meta.setdefault("min", p.min)
            meta.setdefault("max", p.max)
            meta.setdefault("step", p.step)
            meta.setdefault("unit", p.unit)
            meta["default"] = p.default
            if getattr(p, "direction", ""):
                meta["direction"] = p.direction
            meta["help"] = p.help_text() if hasattr(p, "help_text") else meta.get("help", p.label)
            block[p.key] = meta
        if "confirm_min" not in block:
            conf_default = float(rule.confirm_seconds) / 60.0
            block["confirm_min"] = {**_CONFIRM_META, "default": conf_default}
        gate = RULE_GATES.get(rule.id)
        if gate and gate.kind != "always":
            block.setdefault(
                "require_operational_gate",
                {
                    "label": "Require operational proof",
                    "default": 1.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 1.0,
                    "unit": "0/1",
                    "help": "1 = gate on for this rule (fan/pump proven). 0 = evaluate all samples.",
                },
            )
            block.setdefault(
                "startup_delay_min",
                {
                    "label": "Startup delay",
                    "default": gate.startup_delay_seconds / 60.0,
                    "min": 0.0,
                    "max": 30.0,
                    "step": 1.0,
                    "unit": "min",
                    "help": (
                        "Ignore samples until equipment has been proven on this long. "
                        "Raising this shrinks the active-hours denominator, so fault % can rise "
                        "even when fault hours stay flat — compare fault hours, not only %."
                    ),
                },
            )
            block.setdefault(
                "minimum_active_coverage_pct",
                {
                    "label": "Min active coverage",
                    "default": gate.minimum_active_coverage_pct,
                    "min": 0.0,
                    "max": 100.0,
                    "step": 1.0,
                    "unit": "%",
                    "help": (
                        "Skip as EQUIPMENT_OFF when proven-on coverage is below this percent "
                        "(default 5% = essentially off)."
                    ),
                },
            )
        stored = dict(out.get(rule.id, {}))
        modified = False
        for k, meta in block.items():
            if k in stored and abs(float(stored[k]) - float(meta["default"])) > 1e-9:
                modified = True
                break
        badge = " · modified" if modified else ""
        with st.sidebar.expander(f"{rule.id} — {rule.title[:36]}{badge}", expanded=False):
            if rule.id == "SV-RATE":
                st.caption(
                    "Persistence, transition windows, and profile thresholds are edited under "
                    "**Run Rules → SV-RATE** (single source of truth)."
                )
            if rule.id in {"SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE"}:
                from app.rules.cookbook_catalog import FLATLINE_SENSOR_ROLES, SWEEP_SENSOR_ROLES

                roles = FLATLINE_SENSOR_ROLES if rule.id in {"SV-FLATLINE", "SV-STALE"} else SWEEP_SENSOR_ROLES
                frames_sb = st.session_state.get("equipment_frames") or {}
                eq_pick = (
                    st.session_state.get("plot_device")
                    or st.session_state.get("selected_equipment")
                    or st.session_state.get("selected_device")
                )
                present_roles: list[str] = []
                if eq_pick and eq_pick in frames_sb:
                    from app.role_map import apply_role_map

                    mapped_sb = apply_role_map(frames_sb[eq_pick], eq_pick, st.session_state.get("role_map") or {})
                    present_roles = [r for r in roles if r in mapped_sb.columns and mapped_sb[r].notna().any()]
                st.caption(
                    f"Sweeps mapped roles: {', '.join(present_roles) if present_roles else '(none on selected device)'}. "
                    + (
                        "Per-type **range/spike scale** sliders widen/tighten limits by Temperature / Humidity / Pressure."
                        if rule.id in {"SV-RANGE", "SV-SPIKE"}
                        else ""
                    )
                )
            preferred = ["confirm_min", "require_operational_gate", "startup_delay_min", "minimum_active_coverage_pct"]
            skip_keys = {"persistence_min", "transition_window_min"} if rule.id == "SV-RATE" else set()
            ordered = [k for k in preferred if k in block] + [
                k for k in block if k not in preferred and k not in skip_keys
            ]
            changed: dict[str, float] = {}
            for pname in ordered:
                meta = block[pname]
                default = float(meta["default"])
                val = st.slider(
                    meta.get("label", pname),
                    min_value=float(meta["min"]),
                    max_value=float(meta["max"]),
                    value=float(stored.get(pname, default)),
                    step=float(meta.get("step", 0.5)),
                    help=_direction_help(meta),
                    key=f"s_{rule.id}_{pname}",
                )
                if abs(float(val) - default) > 1e-9:
                    changed[pname] = float(val)
            # Preserve SV-RATE editor params already in session (profile overrides, etc.)
            if rule.id == "SV-RATE":
                prev = dict(out.get("SV-RATE") or {})
                for k, v in prev.items():
                    if k in skip_keys or str(k).startswith("svrate__"):
                        changed[k] = v
            if changed:
                out[rule.id] = changed
            else:
                out.pop(rule.id, None)
            if st.button("Reset rule", key=f"reset_{rule.id}"):
                out.pop(rule.id, None)
                for pname in ordered:
                    st.session_state.pop(f"s_{rule.id}_{pname}", None)
                st.session_state.params = out
                st.rerun()

    c1, c2 = st.sidebar.columns(2)
    if c1.button("Reset", key="reset_tune"):
        st.session_state.params = {}
        st.rerun()
    st.session_state.params = out
    st.session_state["_sidebar_fam_key"] = fam_key
    if c2.button("Rerun cat.", key="rerun_cat_sidebar", help="Rerun the selected mechanical category on all equipment"):
        st.session_state["_pending_rerun_family"] = fam_key  # None = all
        st.rerun()


def _units_map() -> dict[str, str]:
    cm = st.session_state.get("column_map") or {}
    units = cm.get("units") if isinstance(cm, dict) else None
    base = dict(units) if isinstance(units, dict) else {}
    return units_map_for_system(base, st.session_state.get("unit_system", "imperial"))


def _equip_by_type(frames: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {}
    rm = st.session_state.get("role_map") or {}
    for eq_id, df in frames.items():
        et = resolve_equipment_type(eq_id, df=df, role_map=rm)
        buckets.setdefault(et, []).append(eq_id)
    return {k: sorted(v, key=natural_key) for k, v in sorted(buckets.items())}


_PLANT_CHART_META: tuple[tuple[str, str, str], ...] = (
    (PLANT_AIR, "Air side — supply fans", "AHU supply fan status preferred over command."),
    (
        PLANT_BOILER,
        "Boiler plant — HW pumps",
        "One series per HW pump (status preferred over command).",
    ),
    (
        PLANT_CHILLER,
        "Chiller plant — chillers, CHW/CW pumps, towers",
        "Chiller plant prefers **mapped pump status**; if no pump, falls back to "
        "chiller_status / compressor_status / equipment_enable — never leave-temp fake runtime."
    ),
)


def _render_plant_motor_weekly(
    motor_weekly: pd.DataFrame,
    *,
    key_prefix: str,
    show_table: bool = True,
    show_download: bool = False,
    min_air_hours: float | None = None,
) -> None:
    """Render three plant-grouped weekly motor charts (avg OAT on secondary axis)."""
    st.markdown("##### Motor run hours by week")
    st.caption(
        "Bars = run hours by week (Mon start). Dotted line = **avg OAT °F while that motor was on**. "
        "Chiller plant prefers **pump status**, then chiller/compressor enable "
        "(no leave-temp fake hours). "
        "Air side: dashed orange = bare-min occupied hours/week from the building schedule."
    )
    if motor_weekly is None or motor_weekly.empty:
        st.info("No supply-fan / pump / chiller / tower motor signals found yet.")
        return
    any_chart = False
    for plant, title, caption in _PLANT_CHART_META:
        if "plant_group" in motor_weekly.columns:
            sub = motor_weekly.loc[motor_weekly["plant_group"] == plant]
        else:
            sub = motor_weekly.iloc[0:0]
        st.markdown(f"**{title}**")
        st.caption(caption)
        fig = motor_weekly_runtime_chart(
            sub,
            title=title,
            min_hours_line=min_air_hours if plant == "air" else None,
            show_avg_oat=True,
        )
        if fig is None:
            st.info(f"No series for {title.split('—')[0].strip().lower()}.")
            continue
        any_chart = True
        st.plotly_chart(
            fig,
            width="stretch",
            config=plotly_config(filename=f"motor_runtime_weekly_{plant}"),
            key=f"{key_prefix}_motor_weekly_{plant}",
        )
    if not any_chart:
        return
    if show_download:
        st.download_button(
            "Download weekly motor hours CSV",
            to_csv_bytes(motor_weekly),
            "motor_run_hours_weekly.csv",
            key=f"{key_prefix}_dl_motor_weekly",
        )
    if show_table:
        with st.expander("Weekly motor hours table"):
            st.dataframe(motor_weekly, hide_index=True, width="stretch", height=280)


def _mapped_equipment(eq_id: str, frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, float]:
    raw = frames[eq_id]
    mapped = apply_role_map(raw, eq_id, st.session_state.role_map)
    # Topology enrich: parent AHU SAT may live only on the raw VAV frame
    if "ahu-discharge-air-temp" in raw.columns and "ahu-discharge-air-temp" not in mapped.columns:
        mapped["ahu-discharge-air-temp"] = raw["ahu-discharge-air-temp"]
    elif "ahu-discharge-air-temp" in raw.columns:
        mapped["ahu-discharge-air-temp"] = raw["ahu-discharge-air-temp"]
    # Canonical: Overview weekly calendar always drives occ_mode for SCHED-1.
    sched = OccupancySchedule.from_dict(st.session_state.get("occupancy_schedule"))
    mapped = apply_schedule_occ_mode(mapped, sched, overwrite=True)
    mapped.attrs.update({k: v for k, v in raw.attrs.items() if not isinstance(v, Path)})
    mapped.attrs["equipment_id"] = eq_id
    if raw.attrs.get("columns_path") is not None:
        mapped.attrs["columns_path"] = str(raw.attrs["columns_path"])
    poll = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw))
    return mapped, poll


def _ensure_ahu_feed_enrichment(frames: dict[str, pd.DataFrame]) -> None:
    """Refresh ahu_sat / feed attrs from session topology before running rules."""
    from app.topology_enrich import enrich_frames_with_ahu_feeds, stamp_feed_attrs

    topo = st.session_state.get("vav_to_ahu") or {}
    if not topo:
        return
    stamp_feed_attrs(frames, topo)
    enrich_frames_with_ahu_feeds(frames, topo, role_map=st.session_state.get("role_map") or {})


def _result_lookup(results: list) -> dict[tuple[str, str], object]:
    return {(r.equipment_id, r.rule_id): r for r in results}


def _preferred_plot_rule_id(applicable: list, lookup: dict, device: str) -> str | None:
    """First FAULT/WARNING rule, else first with a result, else first applicable."""
    if not applicable:
        return None
    ranked: list[tuple[int, str]] = []
    for rule in applicable:
        res = lookup.get((device, rule.id))
        status = str(getattr(res, "status", "") or "")
        if status in {"FAULT", "WARNING"}:
            ranked.append((0, rule.id))
        elif status in {"PASS", "SKIPPED_MISSING_ROLES", "SKIPPED_EQUIPMENT_OFF", "ERROR"}:
            ranked.append((1, rule.id))
        elif res is not None:
            ranked.append((2, rule.id))
        else:
            ranked.append((3, rule.id))
    ranked.sort(key=lambda t: t[0])
    return ranked[0][1]


def _ensure_device_rules_run(device: str, applicable: list, frames: dict[str, pd.DataFrame]) -> bool:
    """Run applicable rules for device if missing or mapping changed. Returns True when a rerun happened."""
    lookup = _result_lookup(st.session_state.batch_results)
    mapping_fp = st.session_state.get("mapping_rev") or _role_map_fingerprint()
    st.session_state.mapping_rev = mapping_fp
    rules_fp = st.session_state.get("rules_mapping_rev") or ""
    mapping_changed = bool(rules_fp) and rules_fp != mapping_fp
    has_results = any(eq == device for eq, _rid in lookup)
    if has_results and not mapping_changed and not st.session_state.get("mapping_stale"):
        return False
    if not applicable:
        return False
    new_res = _run_rule_list([device], applicable, frames)
    keep = [r for r in st.session_state.batch_results if r.equipment_id != device]
    st.session_state.batch_results = keep + new_res
    st.session_state.rules_mapping_rev = mapping_fp
    st.session_state.mapping_stale = False
    focus_key = f"plot_chart_rule_{device}"
    pref = _preferred_plot_rule_id(applicable, _result_lookup(st.session_state.batch_results), device)
    if pref:
        label = next((f"{r.id} — {r.title}" for r in applicable if r.id == pref), None)
        if label:
            st.session_state[focus_key] = label
    return True


def _pick_local_folder() -> str | None:
    """Native OS folder dialog (local Streamlit only). Returns None if cancelled/unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        chosen = filedialog.askdirectory(title="Select building folder (or parent of buildings)")
        root.destroy()
        return chosen or None
    except Exception:
        return None


def _materialize_uploaded_tree(files: list) -> Path | None:
    """Write a browser-picked directory upload into a temp tree and return its root."""
    import tempfile

    if not files:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="vibe19_building_"))
    for f in files:
        rel = getattr(f, "name", None) or "file.csv"
        # Streamlit directory uploads use forward-slash relative paths.
        dest = tmp / Path(*Path(str(rel).replace("\\", "/")).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.getvalue())
    candidates = list_building_candidates(tmp)
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        # Multiple buildings under one upload — prefer deepest common parent already tmp
        return tmp
    return tmp if any(tmp.rglob("history_wide.csv")) else None


def _commit_frames(
    frames: dict[str, pd.DataFrame],
    *,
    site_id: str,
    building_id: str,
    source: str,
    weather,
) -> None:
    if not frames:
        return
    st.session_state.equipment_frames = frames
    st.session_state.weather = weather
    st.session_state.data_source = source
    st.session_state.building_id = building_id
    rm = dict(st.session_state.role_map)
    for eq_id, raw_df in frames.items():
        enrich_role_map_from_equipment(
            rm,
            eq_id,
            Path(raw_df.attrs["columns_path"]) if raw_df.attrs.get("columns_path") else None,
            list(raw_df.columns),
        )
        upsert_equipment_roles(
            st.session_state.site_mapping,
            site_id=str(raw_df.attrs.get("site_id", site_id)),
            building_id=str(raw_df.attrs.get("building_id", building_id)),
            equipment_id=eq_id,
            equipment_type=resolve_equipment_type(eq_id, df=raw_df, role_map=rm),
            roles=rm.get(eq_id, {}),
        )
    st.session_state.role_map = rm
    _sync_role_map_from_sites()
    _attach_frames_meta(frames)
    if st.session_state.selected_equipment not in frames:
        st.session_state.selected_equipment = sorted(frames)[0]


def _render_package_health_sidebar(report: dict | None, warnings: list[str] | None = None) -> None:
    """Dataset details expander — health notes at the bottom (never a red error banner)."""
    report = report or {}
    warnings = list(warnings or [])
    health = report.get("package_health") if isinstance(report.get("package_health"), dict) else None
    summary = list(report.get("package_health_summary") or [])
    grade = str(report.get("package_health_grade") or (health or {}).get("grade") or "").lower()
    detail = list((health or {}).get("detail_lines") or [])
    other = [w for w in warnings if w not in detail and w not in summary]

    has_size = report.get("zip_mb") is not None or report.get("uncompressed_mb") is not None
    if not (health or summary or detail or other or has_size or report.get("building_id")):
        return

    label = "Dataset details"
    if grade and grade not in {"", "ok"}:
        label = f"Dataset details · {grade}"

    with st.sidebar.expander(label, expanded=False):
        bits: list[str] = []
        if report.get("building_id"):
            bits.append(f"`{report.get('building_id')}`")
        if report.get("equipment_count") is not None:
            bits.append(f"{report.get('equipment_count')} equip")
        if report.get("source"):
            bits.append(str(report.get("source")))
        if bits:
            st.caption(" · ".join(bits))
        if has_size:
            from app.package_io import dataset_size_caption

            st.caption(dataset_size_caption(report))

        if detail:
            st.caption("Contract findings (load still succeeded):")
            for line in detail[:40]:
                st.text(line)
            if len(detail) > 40:
                st.caption(f"… +{len(detail) - 40} more (see Export / package_health.json)")

        for w in other[:15]:
            st.caption(w)
        if len(other) > 15:
            st.caption(f"… +{len(other) - 15} more")

        # Health summary last — informational, not an error banner
        if summary or grade:
            st.divider()
            st.caption("Dataset health (non-fatal)")
            for line in summary:
                # Strip markdown bold so caption stays muted
                st.caption(str(line).replace("**", ""))
            if not summary and grade:
                st.caption(
                    f"Dataset health: {grade.upper()} "
                    "(non-fatal — load succeeded; topology/metadata may be incomplete)."
                )

        with st.expander("Raw package report JSON", expanded=False):
            st.json(report)


def _commit_package_result(result) -> None:
    """Commit zip package frames + optional session_config into session_state."""
    from app.data_contract import load_vav_to_ahu_map
    from app.package_io import apply_session_config
    from app.topology_enrich import enrich_frames_with_ahu_feeds, stamp_feed_attrs

    site_id = st.session_state.site_id or DEFAULT_SITE_ID
    for _eq_id, df in result.frames.items():
        df.attrs.setdefault("site_id", site_id)
        df.attrs.setdefault("building_id", result.manifest.building_id)
        if df.attrs.get("columns_path") is not None:
            df.attrs["columns_path"] = str(df.attrs["columns_path"])

    topo = load_vav_to_ahu_map(result.building_root)
    st.session_state.vav_to_ahu = topo
    result.report["vav_to_ahu"] = dict(topo)
    result.report["vav_to_ahu_count"] = len(topo)
    stamp_feed_attrs(result.frames, topo)
    enrich_frames_with_ahu_feeds(
        result.frames, topo, role_map=st.session_state.get("role_map") or {}
    )

    st.session_state.upload_workdir = str(result.workdir)
    st.session_state.package_report = result.report
    # Do not assign ``data_input_mode`` here — it is a radio widget key. Setting it
    # after the radio is drawn (Load zip / path load) raises StreamlitAPIException.
    # Prefer Zip package on the *next* run via a pending flag applied before the radio.
    st.session_state["_pending_data_input_mode"] = "Zip package"
    _commit_frames(
        result.frames,
        site_id=site_id,
        building_id=result.manifest.building_id,
        source=f"zip:{result.manifest.building_id}",
        weather=result.weather,
    )
    if result.session_config is not None:
        for w in apply_session_config(result.session_config, equipment_ids=set(result.frames)):
            st.sidebar.warning(w)
        st.session_state.session_config_source = "package session_config.json"
        if result.session_config.params:
            st.session_state.fault_settings_source = "package session_config.params"
    if result.column_map:
        _apply_column_map_json(result.column_map)
        st.session_state.session_config_source = (
            (st.session_state.get("session_config_source") or "") + " + package column_map.json"
        ).strip(" +")
        # Re-enrich after role_map merge so ahu_sat uses updated mappings
        enrich_frames_with_ahu_feeds(
            st.session_state.equipment_frames,
            st.session_state.get("vav_to_ahu") or topo,
            role_map=st.session_state.get("role_map") or {},
        )
    # Sidebar Dataset details is rendered from _load_data on each run (not here —
    # avoids a red banner flash and duplicate expanders before st.rerun).
    st.session_state.package_warnings = list(
        (result.report or {}).get("package_health_summary") or result.warnings
    )
    # Persist pointer so a browser refresh can reload without re-upload
    try:
        from app.browser_session import write_browser_session_pointer

        write_browser_session_pointer(
            workdir=result.workdir,
            building_root=result.building_root,
            building_id=result.manifest.building_id,
            source=st.session_state.get("data_source") or f"zip:{result.manifest.building_id}",
        )
    except Exception:
        pass


def _load_from_folder(cfg: AppConfig, folder_text: str) -> None:
    """Load building folder via cached path loaders (local / server paths only).

    Does not wipe an existing zip/folder session when the path is empty or invalid.
    """
    from app.package_io import wipe_workdir

    frames: dict[str, pd.DataFrame] = {}
    weather = None
    building_id = ""
    source = ""
    site_id = st.session_state.site_id or DEFAULT_SITE_ID
    path = Path(folder_text).expanduser() if folder_text else None
    if not folder_text:
        # Keep whatever is already loaded (e.g. user switched source briefly)
        return
    if path and path.is_dir():
        candidates = list_building_candidates(path)
        if not candidates:
            st.sidebar.warning("No `history_wide.csv` under that path.")
            return
        labels = [c.name for c in candidates]
        if len(candidates) == 1 and candidates[0].resolve() == path.resolve():
            chosen = candidates[0]
        else:
            pick = st.sidebar.selectbox("Building", labels, index=0)
            chosen = next(c for c in candidates if c.name == pick)
        building_id = chosen.name
        st.session_state.data_root = str(chosen.parent)
        try:
            frames = cached_building_folder(str(chosen.resolve()))
        except Exception as exc:  # pragma: no cover
            st.sidebar.error(str(exc))
            return
        if not frames:
            st.sidebar.warning("Folder loaded but no equipment frames found.")
            return
        # Successful folder load replaces any prior zip session
        if st.session_state.get("upload_workdir"):
            wipe_workdir(st.session_state.get("upload_workdir"))
            st.session_state.upload_workdir = None
            st.session_state.package_report = None
        for eq_id in frames:
            frames[eq_id].attrs.setdefault("site_id", site_id)
            frames[eq_id].attrs.setdefault("building_id", building_id)
            if frames[eq_id].attrs.get("columns_path") is not None:
                frames[eq_id].attrs["columns_path"] = str(frames[eq_id].attrs["columns_path"])
        weather = cached_weather(str(chosen.parent), cfg.weather_subdir)
        source = str(chosen.resolve())
        from app.package_io import bytes_as_mb, directory_size_bytes, effective_package_caps

        unc = directory_size_bytes(chosen)
        caps = effective_package_caps()
        st.session_state.package_report = {
            "source": "folder",
            "building_id": building_id,
            "equipment_count": len(frames),
            "uncompressed_bytes": unc,
            "uncompressed_mb": bytes_as_mb(unc),
            "max_zip_mb": caps.max_zip_mb,
            "max_uncompressed_mb": caps.max_uncompressed_mb,
        }
        st.sidebar.caption(f"{len(frames)} equip · `{building_id}`")
        _commit_frames(frames, site_id=site_id, building_id=building_id, source=source, weather=weather)
        return
    st.sidebar.caption(
        "Folder path not on this host — use Browse folder…, or switch to Zip package."
    )


def _docker_image_caption() -> str | None:
    """Human-readable GHCR/local image identity (avoids bare content hashes in the UI)."""
    import os

    ref = (os.environ.get("VIBE19_IMAGE_REF") or "").strip()
    tag = (os.environ.get("VIBE19_IMAGE_TAG") or "").strip()
    sha = (os.environ.get("VIBE19_GIT_SHA") or "").strip()
    if not ref and not tag and not sha:
        return None
    name = f"{ref}:{tag}" if ref and tag else (ref or tag or "vibe19")
    short = sha[:12] if sha and sha != "unknown" else ""
    return f"Image: `{name}`" + (f" · sha `{short}`" if short else "")


def _load_data(cfg: AppConfig) -> None:
    """Unified data picker: Folder (when allowed) + Zip package (always)."""
    from app.package_io import PackageError, load_package_zip, sweep_old_temp_dirs, wipe_workdir

    sweep_old_temp_dirs()
    st.sidebar.markdown("**Building data**")
    img_cap = _docker_image_caption()
    if img_cap:
        st.sidebar.caption(img_cap)
    mode_label = "Cloud-capable" if cfg.is_cloud else "Local + Cloud-capable"
    st.sidebar.caption(
        f"{mode_label} · same `openfdd_package_v1` zip everywhere "
        f"(`docs/PACKAGE_SPEC.md`). Non-sensitive demo data on shared hosts."
    )

    source_options = ["Zip package"]
    if cfg.allow_server_paths:
        source_options = ["Folder", "Zip package"]
    default_src = "Zip package" if cfg.is_cloud or not cfg.allow_server_paths else "Folder"
    pending = st.session_state.pop("_pending_data_input_mode", None)
    if pending in source_options:
        st.session_state.data_input_mode = pending
    if "data_input_mode" not in st.session_state:
        st.session_state.data_input_mode = default_src
    if st.session_state.data_input_mode not in source_options:
        st.session_state.data_input_mode = source_options[0]
    # Drop a prefilled Folder path that does not exist (Docker / Cloud / missing mount)
    if cfg.allow_server_paths:
        _bf = str(st.session_state.get("building_folder") or "").strip()
        if _bf and not Path(_bf).expanduser().is_dir():
            st.session_state.building_folder = ""
            if st.session_state.data_input_mode == "Folder" and not st.session_state.get("equipment_frames"):
                st.session_state.data_input_mode = "Zip package"
                st.sidebar.caption("Configured folder not found — switched to Zip package.")


    st.sidebar.radio(
        "Data source",
        source_options,
        horizontal=True,
        key="data_input_mode",
        help="Folder = local historian tree. Zip = pre-processed openfdd_package_v1 (Cloud + local).",
    )
    source = st.session_state.data_input_mode

    if source == "Folder" and cfg.allow_server_paths:
        if st.sidebar.button("Browse folder…", help="Pick a building folder on this PC"):
            picked = _pick_local_folder()
            if picked:
                st.session_state.building_folder = picked
                st.rerun()
        folder_text = st.sidebar.text_input(
            "Folder path",
            help="Building folder (AHU_*/… with history_wide.csv), or parent of several buildings.",
            key="building_folder",
        )
        _load_from_folder(cfg, folder_text)
        from app.package_io import dataset_size_caption

        _folder_report = st.session_state.get("package_report")
        if _folder_report:
            st.sidebar.caption(dataset_size_caption(_folder_report))
            _render_package_health_sidebar(
                _folder_report,
                st.session_state.get("package_warnings") or [],
            )
        if st.session_state.get("equipment_frames") and st.sidebar.button(
            "Clear loaded data", key="clear_folder_session"
        ):
            _clear_uploaded_session()
            st.session_state.building_folder = ""
            st.rerun()
    else:
        from app.package_io import (
            BROWSER_UPLOAD_MB,
            dataset_size_caption,
            effective_package_caps,
        )

        browser_caps = effective_package_caps(for_browser_upload=True)
        agent_caps = effective_package_caps()
        zip_files = st.sidebar.file_uploader(
            "Building package zip(s)",
            type=["zip"],
            accept_multiple_files=True,
            key=f"building_zip_{st.session_state.get('zip_uploader_key', 0)}",
            help=(
                f"Upload one building openfdd zip, or several part-zips "
                f"(each ≤{BROWSER_UPLOAD_MB} MB; assembled ≤{agent_caps.max_zip_mb} MB). "
                f"Optional extra weather.zip is merged/ignored safely. "
                f"Limits also count zip items (each file/folder inside the archive), "
                f"not just megabytes — max {agent_caps.max_entries} items / "
                f"{agent_caps.max_equipment} equipment folders. "
                f"See vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md"
            ),
        )
        n_parts = len(zip_files or [])
        parts_mb = (
            round(sum(getattr(f, "size", 0) or len(f.getvalue()) for f in zip_files) / (1024 * 1024), 2)
            if zip_files
            else 0.0
        )
        st.sidebar.caption(
            f"**{n_parts}** file(s) · **{parts_mb} MB** selected · "
            f"per-file ≤**{BROWSER_UPLOAD_MB} MB** · assembled job ≤**{agent_caps.max_zip_mb} MB**"
        )
        st.sidebar.caption(
            f"Build check: zip-item limit **{agent_caps.max_entries}** "
            f"(each file/folder inside the archive) · equip ≤**{agent_caps.max_equipment}**. "
            f"If you still see **200**, `docker pull` the latest "
            f"`ghcr.io/bbartling/vibe19:develop` — that machine is on an old image."
        )
        c1, c2 = st.sidebar.columns(2)
        load_clicked = c1.button(
            "Load zip(s)",
            type="primary",
            disabled=not zip_files,
            key="load_zip_unified",
        )
        delete_clicked = c2.button(
            "Delete dataset",
            key="delete_dataset_unified",
            help="Delete Feather/parquet for the loaded Haystack building id. Keeps fault sliders & session maps.",
        )
        if delete_clicked:
            _delete_dataset_and_clear()
            st.rerun()
        if load_clicked and zip_files:
            wipe_workdir(st.session_state.get("upload_workdir"))
            st.session_state.upload_workdir = None
            try:
                if len(zip_files) == 1:
                    zip_bytes = zip_files[0].getvalue()
                    zip_name = getattr(zip_files[0], "name", None) or "package.zip"
                    result = load_package_zip(zip_bytes, caps=browser_caps)
                else:
                    from app.multi_zip import load_package_from_zip_parts, parts_from_uploads

                    parts = parts_from_uploads(list(zip_files))
                    result = load_package_from_zip_parts(
                        parts,
                        merge_caps=agent_caps,
                        per_part_caps=browser_caps,
                    )
                    # Prefer assembled bytes for central when multi-zip produced a workdir zip.
                    zip_bytes = b""
                    zip_name = "package.zip"
                    for f in zip_files:
                        zip_bytes = f.getvalue()
                        zip_name = getattr(f, "name", None) or zip_name
                        break
            except PackageError as exc:
                st.sidebar.error(str(exc))
            except Exception as exc:  # pragma: no cover
                st.sidebar.error(f"Package load failed: {exc}")
            else:
                _commit_package_result(result)
                part_note = (
                    f" · {result.report.get('zip_part_count', 1)} zip part(s)"
                    if result.report.get("source") == "multi_zip"
                    else ""
                )
                st.sidebar.success(
                    f"Loaded {len(result.frames)} equip · `{result.manifest.building_id}`{part_note}"
                )
                # Best-effort central Feather/parquet ingest — does not replace local pandas session.
                if len(zip_files) == 1:
                    _push_package_to_central(zip_bytes, filename=str(zip_name))
                else:
                    # Multi-part: push each part; central accepts one zip — push first / merged if available.
                    workdir = result.report.get("workdir") or st.session_state.get("upload_workdir")
                    pushed = False
                    if workdir:
                        from pathlib import Path as _P

                        for cand in _P(str(workdir)).rglob("*.zip"):
                            _push_package_to_central(cand.read_bytes(), filename=cand.name)
                            pushed = True
                            break
                    if not pushed and zip_bytes:
                        _push_package_to_central(zip_bytes, filename=str(zip_name))
                st.rerun()

        if cfg.allow_server_paths:
            st.sidebar.markdown("**Agent path load (local)**")
            st.sidebar.text_input(
                "Package zip path",
                help="Absolute path to an openfdd_package_v1 zip (Codex/Cursor — no browser upload).",
                key="package_zip_path",
            )
            if st.sidebar.button("Load zip from path", key="load_zip_from_path"):
                zip_path = Path(str(st.session_state.get("package_zip_path") or "").strip())
                if not zip_path.is_file():
                    st.sidebar.error(f"Zip not found: {zip_path}")
                else:
                    wipe_workdir(st.session_state.get("upload_workdir"))
                    st.session_state.upload_workdir = None
                    try:
                        zip_bytes = zip_path.read_bytes()
                        result = load_package_zip(zip_bytes)
                    except PackageError as exc:
                        st.sidebar.error(str(exc))
                    except Exception as exc:  # pragma: no cover
                        st.sidebar.error(f"Package load failed: {exc}")
                    else:
                        _commit_package_result(result)
                        st.sidebar.success(
                            f"Loaded {len(result.frames)} equip · `{result.manifest.building_id}`"
                        )
                        _push_package_to_central(zip_bytes, filename=zip_path.name)
                        st.rerun()

            st.sidebar.text_input(
                "Fault settings JSON path",
                help="Agent-produced fault_settings.json (rule_id → params).",
                key="fault_settings_path",
            )
            if st.sidebar.button("Load fault settings from path", key="load_fault_settings_path"):
                fpath = Path(str(st.session_state.get("fault_settings_path") or "").strip())
                if not fpath.is_file():
                    st.sidebar.error(f"Not found: {fpath}")
                else:
                    try:
                        raw = json.loads(fpath.read_text(encoding="utf-8"))
                        if not isinstance(raw, dict):
                            raise ValueError("JSON must be an object")
                        params = dict(st.session_state.get("params") or {})
                        for rid, p in raw.items():
                            if isinstance(p, dict):
                                params[str(rid)] = {**params.get(str(rid), {}), **p}
                        st.session_state.params = params
                        st.session_state.fault_settings_source = f"path:{fpath.name}"
                        st.sidebar.success(f"Applied fault settings from {fpath.name}")
                        st.rerun()
                    except Exception as exc:
                        st.sidebar.error(f"Fault settings load failed: {exc}")
            st.sidebar.text_input(
                "Session config JSON path",
                help="openfdd_session_v1 JSON (units / role_map / params).",
                key="session_config_path",
            )
            if st.sidebar.button("Load session config from path", key="load_session_config_path"):
                spath = Path(str(st.session_state.get("session_config_path") or "").strip())
                if not spath.is_file():
                    st.sidebar.error(f"Not found: {spath}")
                else:
                    try:
                        warnings = _apply_session_config_bytes(
                            spath.read_bytes(), source_label=f"path:{spath.name}"
                        )
                        for w in warnings:
                            st.sidebar.warning(w)
                        st.sidebar.success(f"Applied session config from {spath.name}")
                        st.rerun()
                    except Exception as exc:
                        st.sidebar.error(f"Session config load failed: {exc}")

        st.sidebar.caption(dataset_size_caption(None, caps=agent_caps))
        report = st.session_state.get("package_report")
        if report:
            st.sidebar.caption(dataset_size_caption(report, caps=agent_caps))
            _render_package_health_sidebar(
                report,
                st.session_state.get("package_warnings") or [],
            )
        frames = st.session_state.get("equipment_frames") or {}
        if frames and st.session_state.get("upload_workdir"):
            st.sidebar.caption(
                f"{len(frames)} equip · `{st.session_state.get('building_id') or '—'}` (zip session)"
            )
        elif frames:
            # Folder data still in session while Zip tab is selected — don't drop it
            st.sidebar.caption(
                f"{len(frames)} equip · `{st.session_state.get('building_id') or '—'}` (session)"
            )

    st.sidebar.markdown("**Session restore (Cloud-safe)**")
    st.sidebar.caption(
        "Download after mapping/tuning; later upload zip + this JSON — no server path."
    )
    with st.sidebar:
        _render_session_config_io(key_prefix="sidebar")

    frames_ready = bool(st.session_state.get("equipment_frames"))
    if frames_ready:
        st.sidebar.markdown("**Agent prerun**")
        st.sidebar.caption(
            "After zip(s) load: auto-build column map if needed, then run all rules "
            "so Plots/RCx are ready for human review."
        )
        if st.sidebar.button("Map + prerun all faults", type="primary", key="agent_prerun_btn"):
            from app.agent_prerun import ensure_column_map

            frames = st.session_state.equipment_frames
            cmap, built, warns = ensure_column_map(
                frames,
                existing_map=st.session_state.get("column_map_json"),
                building_id=str(st.session_state.get("building_id") or ""),
            )
            for w in warns:
                st.sidebar.info(w)
            if built and cmap:
                _apply_column_map_json(cmap)
                st.session_state.column_map_json = cmap
            st.session_state.batch_results = _run_rule_list(
                sorted(frames), RULES, frames
            )
            n = len(st.session_state.batch_results)
            err = sum(1 for r in st.session_state.batch_results if r.status == "ERROR")
            fault = sum(1 for r in st.session_state.batch_results if r.status == "FAULT")
            st.session_state.prerun_status = (
                f"Prerun {n} evals · {fault} FAULT · {err} ERROR"
            )
            if err:
                st.sidebar.error(st.session_state.prerun_status)
            else:
                st.sidebar.success(st.session_state.prerun_status)
            st.rerun()
        if st.session_state.get("prerun_status"):
            st.sidebar.caption(st.session_state.prerun_status)

    with st.sidebar.expander("AI agent / package help", expanded=False):
        from app.package_io import BROWSER_UPLOAD_MB, DEFAULT_PACKAGE_MB
        from app.package_io import effective_package_caps as _caps_fn

        _c = _caps_fn()
        st.markdown(
            f"""
**Human + agent flow (large jobs)**
1. Agent preprocesses CSVs → one or many `openfdd_package_v1` **part zips**
   (each ≤ **{BROWSER_UPLOAD_MB} MB** for the browser). Spec:
   `vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md`
2. Human uploads **all part zips** here → **Load zip(s)** (merged ≤ **{DEFAULT_PACKAGE_MB} MB**).
3. Click **Map + prerun all faults** (or agent CLI) so rules/errors are checked.
4. Human reviews **Plots / RCx**; download session config to restore later.

**Single zip** still works. Path/CLI bypasses the upload widget for full-size packages.

Agent brief: {_AGENTS_MD_URL}
            """.strip()
        )
        demo = APP_ROOT / "data" / "demo_package_v1.zip"
        if demo.is_file():
            st.caption(f"Demo package on disk: `{demo.name}`")
            st.download_button(
                "Download demo_package_v1.zip",
                data=demo.read_bytes(),
                file_name="demo_package_v1.zip",
                mime="application/zip",
                key="dl_demo_package",
                help="Synthetic non-sensitive package for Cloud / agent dry-runs.",
            )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Display & site")
    st.sidebar.radio(
        "Units",
        ["imperial", "metric"],
        horizontal=True,
        help="Rules stay imperial internally; charts/tables and temp proof sliders convert for display.",
        key="unit_system",
    )
    st.sidebar.checkbox(
        "Prefer web OAT (Open-Meteo)",
        help="OAT-dependent views use weather CSV / wx_oa_t before BAS oa_t.",
        key="prefer_web_oat",
    )
    use_status_proof = st.sidebar.checkbox(
        "Use mapped mechanical-cooling status proof",
        help=(
            "Checked: compressor/chiller status → verified command → amps/power "
            "(CHW pump alone is never compressor proof). "
            "Unchecked: CHW plants use the leaving-water threshold below; "
            "temperature runtime is inferred and may include flow through an idle chiller."
        ),
        key="use_mech_cooling_status_proof",
    )
    _temp_threshold_slider(
        label_base="CHW leave proof max",
        stored_key="chw_leave_max_f",
        min_f=35.0,
        max_f=50.0,
        step_f=0.5,
        help=(
            "When mapped status proof is unchecked, treat valid CHW supply below "
            "this threshold as inferred mechanical cooling. Stored as °F; Units "
            "radio switches this slider between °F and °C."
        ),
        location=st.sidebar,
        disabled=bool(use_status_proof),
    )
    st.session_state.include_ahu_chw_valve = False
    st.session_state.apply_occupancy_calendar = True
    st.sidebar.caption(
        "Occupancy: Overview weekly calendar always sets `occ_mode` (SCHED-1). "
        "Mech-cooling OAT bins: chillers + DX only (no AHU CHW valve)."
    )


def _temp_threshold_slider(
    *,
    label_base: str,
    stored_key: str,
    min_f: float,
    max_f: float,
    step_f: float = 0.5,
    help: str = "",
    location=None,
    disabled: bool = False,
) -> float:
    """Temp slider that follows Units (°F/°C); always persists imperial °F in ``stored_key``."""
    loc = location if location is not None else st
    system = st.session_state.get("unit_system", "imperial")
    stored = float(st.session_state.get(stored_key, (min_f + max_f) / 2.0))
    stored = max(min_f, min(max_f, stored))
    st.session_state[stored_key] = stored

    unit_marker = f"_{stored_key}_ui_unit"
    widget_key = f"_{stored_key}_ui"

    if system == "metric":
        lo, hi = round(f_to_c(min_f), 1), round(f_to_c(max_f), 1)
        step = max(0.1, round(step_f * 5.0 / 9.0, 1))
        label = f"{label_base} °C"
        if st.session_state.get(unit_marker) != "metric":
            st.session_state[widget_key] = round(f_to_c(stored), 1)
            st.session_state[unit_marker] = "metric"
        cur = float(st.session_state.get(widget_key, f_to_c(stored)))
        st.session_state[widget_key] = max(lo, min(hi, cur))
        new_c = loc.slider(
            label,
            min_value=lo,
            max_value=hi,
            step=step,
            help=help,
            key=widget_key,
            disabled=disabled,
        )
        st.session_state[stored_key] = max(min_f, min(max_f, c_to_f(float(new_c))))
    else:
        label = f"{label_base} °F"
        if st.session_state.get(unit_marker) != "imperial":
            st.session_state[widget_key] = stored
            st.session_state[unit_marker] = "imperial"
        cur = float(st.session_state.get(widget_key, stored))
        st.session_state[widget_key] = max(min_f, min(max_f, cur))
        new_f = loc.slider(
            label,
            min_value=min_f,
            max_value=max_f,
            step=step_f,
            help=help,
            key=widget_key,
            disabled=disabled,
        )
        st.session_state[stored_key] = float(new_f)

    return float(st.session_state[stored_key])


def _hhmm_to_time(text: str):
    from datetime import time as dtime

    parts = str(text).strip().split(":")
    h = int(parts[0]) if parts else 6
    m = int(parts[1]) if len(parts) > 1 else 0
    return dtime(max(0, min(23, h)), max(0, min(59, m)))


def _time_to_hhmm(t) -> str:
    return f"{int(t.hour):02d}:{int(t.minute):02d}"


def _sync_zone_comfort_into_params() -> None:
    """Push Overview/sidebar zone band into VAV-1, SCHED-1, and CHW-NOLOAD-1 params."""
    params = st.session_state.setdefault("params", {})
    lo = float(st.session_state.get("zone_lo_f", 70.0))
    hi = float(st.session_state.get("zone_hi_f", 75.0))
    vav = dict(params.get("VAV-1") or {})
    vav["zone_lo"] = lo
    vav["zone_hi"] = hi
    params["VAV-1"] = vav
    sched = dict(params.get("SCHED-1") or {})
    sched["comfort_low_f"] = lo
    sched["comfort_high_f"] = hi
    params["SCHED-1"] = sched
    noload = dict(params.get("CHW-NOLOAD-1") or {})
    noload["comfort_low_f"] = lo
    noload["comfort_high_f"] = hi
    params["CHW-NOLOAD-1"] = noload
    st.session_state.params = params


def _render_occupancy_editor(*, key_prefix: str) -> OccupancySchedule:
    """Mon–Sun occupied windows with time pickers. Persists to session_state.occupancy_schedule."""
    sched = OccupancySchedule.from_dict(st.session_state.get("occupancy_schedule"))
    tz = st.text_input("Timezone", value=sched.timezone, key=f"{key_prefix}_occ_tz")
    days_out: dict = {}
    for d in DAYS:
        day = sched.days[d]
        st.markdown(f"**{DAY_LABELS[d]}**")
        c1, c2, c3 = st.columns(3)
        occ = c1.checkbox("Occupied", value=day.occupied, key=f"{key_prefix}_occ_{d}")
        start = c2.time_input(
            "Start",
            value=_hhmm_to_time(day.start),
            key=f"{key_prefix}_occ_s_{d}",
        )
        end = c3.time_input(
            "End",
            value=_hhmm_to_time(day.end),
            key=f"{key_prefix}_occ_e_{d}",
        )
        days_out[d] = {
            "occupied": bool(occ),
            "start": _time_to_hhmm(start),
            "end": _time_to_hhmm(end),
        }
    out = {"timezone": tz, "days": days_out}
    st.session_state.occupancy_schedule = out
    return OccupancySchedule.from_dict(out)


def _render_building_schedule_overview() -> float:
    """Main-dashboard occupancy + zone SP; returns bare-min occupied hours/week."""
    st.markdown("##### Building schedule & zone comfort (FDD starting point)")
    st.caption(
        "Occupancy calendar always drives **SCHED-1** (`occ_mode`) — edit times below; do not remove this UI. "
        "Zone low/high seed **VAV-1** comfort band (Units radio switches °F/°C). "
        "Bare-min occupied hours/week draws on air-side motor charts."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        _temp_threshold_slider(
            label_base="Zone low",
            stored_key="zone_lo_f",
            min_f=55.0,
            max_f=72.0,
            step_f=0.5,
            location=st,
        )
    with c2:
        _temp_threshold_slider(
            label_base="Zone high",
            stored_key="zone_hi_f",
            min_f=70.0,
            max_f=85.0,
            step_f=0.5,
            location=st,
        )
    with c3:
        sched0 = OccupancySchedule.from_dict(st.session_state.get("occupancy_schedule"))
        st.metric("Bare-min occ hours / week", f"{occupied_hours_per_week(sched0):.0f}")
    _sync_zone_comfort_into_params()
    with st.expander("Edit weekly occupancy (time pickers)", expanded=True):
        sched = _render_occupancy_editor(key_prefix="overview")
    return occupied_hours_per_week(
        OccupancySchedule.from_dict(st.session_state.get("occupancy_schedule"))
    )


def _site_mapping_tab(cfg: AppConfig, selected: str, raw_df: pd.DataFrame) -> None:
    st.subheader("Site / building / equipment mapping")
    sites = st.session_state.site_mapping
    site_ids = sorted(sites.keys()) or [DEFAULT_SITE_ID]
    sid = st.selectbox("Site", site_ids, key="map_site")
    site = sites.setdefault(sid, Site(site_id=sid, site_name=sid))
    bids = sorted(site.buildings.keys()) or [DEFAULT_BUILDING_ID]
    bid = st.selectbox("Building", bids, key="map_bldg")
    building = site.buildings.setdefault(bid, Building(building_id=bid, building_name=bid, site_id=sid))
    type_opts = list(EQUIPMENT_TYPES)
    cur_type = resolve_equipment_type(
        selected,
        df=raw_df,
        role_map=st.session_state.role_map,
        column_map=st.session_state.get("column_map"),
        sites=sites,
    )
    type_idx = type_opts.index(cur_type) if cur_type in type_opts else 0
    etype = st.selectbox(
        "Equipment type",
        type_opts,
        index=type_idx,
        key=f"map_etype_{selected}",
        help="RTU → choose AHU (DX roles). Heat pump → HP. Persists into session_config role_map meta.",
    )
    st.write(f"Editing equipment **{selected}**")
    inferred = {**suggest_roles(raw_df), **roles_from_columns_csv(Path(raw_df.attrs.get("columns_path")) if raw_df.attrs.get("columns_path") else None)}
    edit = dict(st.session_state.role_map.get(selected, {}))
    for role in sorted(set(list(inferred.keys()) + list(edit.keys()) + ["zone-air-temp", "discharge-air-temp", "discharge-air-temp-sp", "outside-air-temp", "fan-cmd", "chw-pump-status", "chw_pump_equipment"])):
        if role in {"equipment_type", "equipType", "plant_group", "notes"}:
            continue
        opts = [""] + list(raw_df.columns)
        cur = edit.get(role, inferred.get(role, ""))
        if role == "chw_pump_equipment":
            eq_opts = [""] + sorted(st.session_state.equipment_frames)
            cur_link = str(edit.get("chw_pump_equipment") or "")
            edit["chw_pump_equipment"] = st.selectbox(
                "chw_pump_equipment (linked)",
                eq_opts,
                index=eq_opts.index(cur_link) if cur_link in eq_opts else 0,
                key=f"sm_{selected}_chw_pump_equipment",
                help="Optional: equipment id that owns the CHW pump status column.",
            )
            continue
        edit[role] = st.selectbox(role, opts, index=opts.index(cur) if cur in opts else 0, key=f"sm_{selected}_{role}")
    edit = {k: v for k, v in edit.items() if v}
    edit["equipment_type"] = etype
    st.session_state.role_map[selected] = edit
    raw_df.attrs["equipment_type"] = etype
    upsert_equipment_roles(
        sites,
        site_id=sid,
        building_id=bid,
        equipment_id=selected,
        equipment_type=etype,
        roles=edit,
    )
    _sync_role_map_from_sites()
    c1, c2, c3 = st.columns(3)
    if c1.button("Save flat YAML"):
        if not cfg.allow_disk_writes:
            st.warning("Shared/Cloud host: use Export download — server disk writes are disabled.")
        else:
            save_role_map(cfg.role_map_path, st.session_state.role_map, nested=False)
            st.success("Saved flat role_map.yaml")
    if c2.button("Save nested site YAML"):
        if not cfg.allow_disk_writes:
            st.warning("Shared/Cloud host: use Export download — server disk writes are disabled.")
        else:
            save_site_mapping(cfg.role_map_path, sites)
            st.success("Saved nested sites YAML")
    if c3.button("Export nested YAML download"):
        st.download_button("Download nested mapping", yaml.safe_dump({"sites": {s: st.session_state.site_mapping[s].to_dict() for s in st.session_state.site_mapping}}, sort_keys=False), "site_mapping.yaml")


def main() -> None:
    _init_state()
    cfg = AppConfig.load()
    defaults_cfg = cached_rule_defaults(str(cfg.rule_defaults_path))
    _apply_agent_bootstrap_once()
    _apply_browser_autoload_once()
    _load_data(cfg)
    _sidebar_sliders(defaults_cfg)

    if st.session_state.get("bootstrap_status"):
        st.sidebar.caption(f"Agent bootstrap: {st.session_state.bootstrap_status}")

    frames = st.session_state.equipment_frames
    if frames and st.session_state.get("upload_workdir"):
        try:
            from app.browser_session import touch_path

            touch_path(st.session_state.upload_workdir)
        except Exception:
            pass
    if not frames:
        _empty_state_directions()
        return

    # Sidebar "Rerun cat." — apply after frames exist
    pending = st.session_state.pop("_pending_rerun_family", "__none__")
    if pending != "__none__":
        rules = RULES if pending is None else _rules_by_family().get(pending, [])
        st.session_state.batch_results = _run_rule_list(sorted(frames), rules, frames)
        label = "all rules" if pending is None else family_label(pending)
        st.toast(f"Reran {label}: {len(st.session_state.batch_results)} evaluations")

    eq_ids = sorted(frames, key=natural_key)
    selected = st.selectbox("Equipment", eq_ids, index=eq_ids.index(st.session_state.selected_equipment) if st.session_state.selected_equipment in eq_ids else 0)
    st.session_state.selected_equipment = selected
    mapped, poll = _mapped_equipment(selected, frames)
    kind = infer_equipment_kind(
        selected, df=frames.get(selected), role_map=st.session_state.role_map
    )
    units_map = _units_map()
    by_type = _equip_by_type(frames)

    _MAIN_SECTIONS = list(REQUIRED_MAIN_SECTIONS)
    section = st.radio(
        "Section",
        _MAIN_SECTIONS,
        horizontal=True,
        key="main_section",
        label_visibility="collapsed",
    )
    st.caption(
        f"Plot traces capped at **{max_plot_points():,}** points "
        "(env `VIBE19_MAX_PLOT_POINTS`) — full data still used for rules/exports."
    )

    span = dataset_time_span(frames)
    motor_tbl = motor_run_hours_table(frames, st.session_state.role_map)
    motor_tot = motor_run_hours_totals(motor_tbl)
    motor_weekly = pd.DataFrame()
    cool_bins = pd.DataFrame()
    cool_coverage = pd.DataFrame()
    if section == "Overview":
        try:
            motor_weekly = motor_run_hours_weekly(
                frames,
                st.session_state.role_map,
                chw_leave_max_f=float(st.session_state.get("chw_leave_max_f", 48.0)),
                weather=st.session_state.weather,
                prefer_web_oat=bool(st.session_state.get("prefer_web_oat", True)),
            )
        except Exception as exc:
            st.warning(f"Weekly motor hours unavailable: {exc}")
        try:
            cool_bins = mech_cooling_oat_bins(
                frames,
                st.session_state.role_map,
                weather=st.session_state.weather,
                prefer_web_oat=bool(st.session_state.get("prefer_web_oat", True)),
                chw_leave_max_f=float(st.session_state.get("chw_leave_max_f", 48.0)),
                include_ahu_chw_valve=False,
                include_total=True,
                use_status_proof=bool(
                    st.session_state.get("use_mech_cooling_status_proof", True)
                ),
            )
            cool_coverage = mech_cooling_coverage(
                frames,
                st.session_state.role_map,
                weather=st.session_state.weather,
                prefer_web_oat=bool(st.session_state.get("prefer_web_oat", True)),
                chw_leave_max_f=float(st.session_state.get("chw_leave_max_f", 48.0)),
                use_status_proof=bool(
                    st.session_state.get("use_mech_cooling_status_proof", True)
                ),
            )
        except Exception as exc:
            st.warning(f"Mech-cooling OAT bins unavailable: {exc}")
    start_s = span["start"].strftime("%Y-%m-%d %H:%M") if span["start"] is not None else "—"
    end_s = span["end"].strftime("%Y-%m-%d %H:%M") if span["end"] is not None else "—"

    if section == "Overview":
        st.subheader("Overview")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Equipment", len(frames))
        _n_custom = len(RULES) - CANONICAL_RULE_COUNT
        c2.metric(
            "Rules",
            (
                f"{CANONICAL_RULE_COUNT} (+{_n_custom} custom)"
                if _n_custom > 0
                else str(CANONICAL_RULE_COUNT)
            ),
        )
        c3.metric("Rows (selected)", len(mapped))
        c4.metric("Poll (s)", f"{poll:.0f}")
        c5.metric("Kind", kind)
        st.caption(f"`{st.session_state.data_source}`")
        _pkg_rep = st.session_state.get("package_report") or {}
        _size_bits = []
        if _pkg_rep.get("zip_mb") is not None:
            _size_bits.append(f"{_pkg_rep['zip_mb']} MB zip")
        if _pkg_rep.get("uncompressed_mb") is not None:
            _size_bits.append(f"{_pkg_rep['uncompressed_mb']} MB on disk")
        if _size_bits:
            _lim_z = _pkg_rep.get("max_zip_mb", "—")
            _lim_u = _pkg_rep.get("max_uncompressed_mb", "—")
            st.caption(
                f"Dataset size: {' · '.join(str(b) for b in _size_bits)} "
                f"(limits {_lim_z} / {_lim_u} MB)"
            )

        d1, d2, d3 = st.columns(3)
        d1.metric("Dataset start", start_s)
        d2.metric("Dataset end", end_s)
        d3.metric("Span (h)", f"{span['span_hours']:.1f}")

        from app.report_downloads import render_overview_rcx_download

        render_overview_rcx_download(key="overview_generic_rcx_docx")

        min_air_hours = _render_building_schedule_overview()
        _render_plant_motor_weekly(
            motor_weekly,
            key_prefix="overview",
            show_table=True,
            min_air_hours=min_air_hours,
        )

        st.markdown("##### Mechanical cooling hours by OAT bin")
        st.caption(
            "**Chillers / DX / VRF** use the sidebar compressor-proof mode (default: "
            "mapped status → command → amps → power; optional inferred CHW leave temp "
            "when status proof is unchecked). **CHW pump alone is never compressor "
            "proof.** Never CHW cooling valves. Bins sorted cold→hot; OAT from **web** "
            "weather by default. Stacked bars are per-device runtime; line traces are "
            "**total compressor device-hours** and **any compressor active**. The "
            "coverage table always lists every cooling-capable device with eligibility, "
            "activity, proof, runtime, and reason. Temperature-derived runtime is "
            "labeled inferred — cold water can flow through an idle chiller."
        )
        zero_warn = mech_cooling_zero_eligible_warning(cool_coverage)
        if zero_warn:
            st.warning(zero_warn)
        runtime_msg = mech_cooling_runtime_message(cool_coverage)
        if runtime_msg:
            st.info(runtime_msg)
        cool_fig = mech_cooling_oat_histogram(cool_bins)
        if cool_fig is None and not zero_warn:
            st.info(
                "No compressor runtime bins for the selected proof mode. Eligible "
                "devices with zero observed runtime still appear in the coverage table "
                "as **No runtime observed**. Map chiller/compressor status, command, "
                "amps, or power, or uncheck status proof and set CHW leave proof max °F. "
                "AHU CHW valves excluded."
            )
        elif cool_fig is not None:
            st.plotly_chart(
                cool_fig,
                width="stretch",
                config=plotly_config(filename="mech_cooling_oat_bins"),
                key="overview_cool_bins",
            )
            st.dataframe(cool_bins, hide_index=True, width="stretch", height=280)
            st.download_button(
                "Download mech cooling OAT bins CSV",
                to_csv_bytes(cool_bins),
                "mech_cooling_oat_bins.csv",
                key="dl_cool_bins_overview",
            )
        if not cool_coverage.empty:
            if "included" in cool_coverage.columns:
                n_inc = int(cool_coverage["included"].fillna(False).astype(bool).sum())
                n_exc = int((~cool_coverage["included"].fillna(False).astype(bool)).sum())
            else:
                n_inc = int((cool_coverage["status"] == "included").sum())
                n_exc = int((cool_coverage["status"] == "excluded").sum())
            mode = (
                "mapped compressor/chiller status, command, amps, or power"
                if st.session_state.get("use_mech_cooling_status_proof", True)
                else "inferred CHW leaving temperature"
            )
            st.markdown(
                f"###### Mechanical cooling devices — {n_inc} included, {n_exc} excluded"
            )
            st.caption(
                f"Selected proof mode: **{mode}**. Coverage shows eligibility, activity, "
                "proof, runtime, and reason for every cooling-capable device. Eligible "
                "devices with no observed runtime remain visible as **No runtime "
                "observed**. Temperature-derived runtime is inferred: cold water can "
                "flow through an idle chiller."
            )
            coverage_display = format_mech_cooling_coverage_display(cool_coverage)
            st.dataframe(
                coverage_display,
                hide_index=True,
                width="stretch",
                height=min(360, 38 + 35 * max(1, len(coverage_display))),
            )
            st.download_button(
                "Download cooling coverage CSV",
                to_csv_bytes(cool_coverage),
                "mech_cooling_coverage.csv",
                key="dl_cool_coverage_overview",
            )

        st.markdown("##### Economizer weather opportunity / compliance")
        st.caption(
            "Strict **web** dry-bulb + dewpoint (or Magnus from web RH). "
            "Opportunity = 60≤DB<72°F and DP<60°F. "
            "Integrated hours use cooling-valve + OA damper threshold (default 90%). "
            "Prohibited cooling uses compressor/chiller proof below 60°F. "
            "Hours use actual timestamp deltas."
        )
        try:
            econ_tbl = economizer_weather_summary(
                frames,
                st.session_state.role_map,
                weather=st.session_state.weather,
            )
        except Exception as exc:
            econ_tbl = pd.DataFrame()
            st.warning(f"Economizer weather summary unavailable: {exc}")
        if econ_tbl is None or econ_tbl.empty:
            st.info("No AHU/chiller/heat-pump rows with web weather or applicable signals.")
        else:
            st.dataframe(econ_tbl, hide_index=True, width="stretch", height=280)
            st.download_button(
                "Download economizer weather CSV",
                to_csv_bytes(econ_tbl),
                "economizer_weather.csv",
                key="dl_econ_weather_overview",
            )

        st.markdown("##### BAS vs web outdoor-air temperature")
        st.caption(
            "Overlay of **BAS OAT** and **web dry-bulb** on one axis with a ±`oat_err` tolerance band "
            "(from OAT-METEO slider; default 5°F). Bottom lane flags samples outside the band. "
            "Histogram of BAS − web deviation is below for distribution shape."
        )
        oat_err = 5.0
        try:
            oat_err = float((st.session_state.get("params") or {}).get("OAT-METEO", {}).get("oat_err", 5.0))
        except (TypeError, ValueError):
            oat_err = 5.0
        overlay = bas_vs_web_oat_overlay(
            frames,
            st.session_state.role_map,
            weather=st.session_state.weather,
            oat_err=oat_err,
        )
        if overlay is None:
            st.info("Need both BAS outdoor-air temp and web weather OAT for the overlay chart.")
        else:
            st.plotly_chart(
                overlay,
                width="stretch",
                config=plotly_config(filename="bas_vs_web_oat_overlay"),
                key="overview_bas_web_oat_overlay",
            )
        wx_fig = bas_vs_web_oat_histogram(
            frames,
            st.session_state.role_map,
            weather=st.session_state.weather,
        )
        if wx_fig is not None:
            with st.expander("BAS − web OAT deviation histogram", expanded=False):
                st.plotly_chart(
                    wx_fig,
                    width="stretch",
                    config=plotly_config(filename="bas_vs_web_oat_hist"),
                    key="overview_bas_web_oat",
                )

        st.markdown(
            "Tune thresholds in the **left sidebar** → **Run Rules** (all or by category) "
            "or sidebar **Rerun cat.** → browse **FDD Plots** by device type (AHU / VAV / plant…)."
        )
        st.markdown("**Devices by type**")
        type_counts = pd.DataFrame(
            [{"type": t, "count": len(ids)} for t, ids in by_type.items()]
        )
        st.dataframe(type_counts, hide_index=True, width="stretch")

        st.markdown("##### Data inspection — raw CSV")
        st.caption(
            "Pick any uploaded equipment (or weather) CSV and plot **all numeric / status columns** "
            "as stacked Plotly line charts. Data stays loaded across browser refresh until you click "
            "**Delete dataset** in the sidebar (a container restart still clears temp files)."
        )
        inspect_options: list[str] = list(eq_ids)
        weather_df = st.session_state.get("weather")
        if weather_df is not None and getattr(weather_df, "empty", True) is False:
            inspect_options = inspect_options + ["(weather)"]
        default_inspect = selected if selected in inspect_options else inspect_options[0]
        inspect_pick = st.selectbox(
            "CSV / equipment",
            inspect_options,
            index=inspect_options.index(default_inspect),
            key="overview_inspect_csv",
        )
        if inspect_pick == "(weather)":
            inspect_df = weather_df
            inspect_label = "weather"
        else:
            inspect_df = frames[inspect_pick]
            inspect_label = inspect_pick
        numeric_cols = []
        for c in inspect_df.columns:
            s = inspect_df[c]
            if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
                numeric_cols.append(str(c))
            else:
                coerced = pd.to_numeric(s, errors="coerce")
                if coerced.notna().sum() >= max(1, int(0.5 * len(s))):
                    numeric_cols.append(str(c))
        show_cols = st.multiselect(
            "Columns to plot (default: all)",
            numeric_cols,
            default=numeric_cols,
            key=f"overview_inspect_cols_{inspect_label}",
        )
        n_rows = int(len(inspect_df))
        span = ""
        if isinstance(inspect_df.index, pd.DatetimeIndex) and len(inspect_df.index):
            span = f" · {inspect_df.index.min()} → {inspect_df.index.max()}"
        st.caption(
            f"`{inspect_label}` · **{n_rows}** rows · **{len(show_cols)}** / {len(numeric_cols)} "
            f"plottable columns{span}"
        )
        if not show_cols:
            st.info("Select at least one column to plot.")
        else:
            fig_insp = equipment_inspection_chart(
                inspect_df,
                equipment_id=inspect_label,
                columns=show_cols,
            )
            if fig_insp is None:
                st.info("No plottable series in this CSV.")
            else:
                st.plotly_chart(
                    fig_insp,
                    width="stretch",
                    config=plotly_config(filename=f"inspect_{inspect_label}"),
                    key=f"overview_inspect_chart_{inspect_label}",
                )
        st.download_button(
            f"Download `{inspect_label}` CSV",
            to_csv_bytes(inspect_df),
            f"{inspect_label}_raw.csv",
            key=f"dl_inspect_{inspect_label}",
        )

    if section == "Data Model":
        from app.data_model_tree import build_data_model_tree

        st.subheader("Data model")
        st.caption(
            "Point inventory: equipment → Haystack-like tags → raw CSV columns. "
            "AHU↔VAV topology is listed separately (from package `vav_to_ahu_simple.csv` when present). "
            "Word report: use the Generic RCx download on **Overview**."
        )
        tree = build_data_model_tree(
            frames,
            st.session_state.role_map,
            building_id=st.session_state.get("building_id") or "",
            vav_to_ahu=st.session_state.get("vav_to_ahu")
            or (st.session_state.get("package_report") or {}).get("vav_to_ahu"),
        )

        st.markdown("##### Topology (AHU ↔ VAV)")
        topo_n = len(tree.vav_to_ahu or {})
        if topo_n:
            st.caption(
                f"**{topo_n}** VAV→AHU link(s): each VAV is **fedBy** its parent AHU; "
                "each AHU **feeds** its VAV children."
            )
            topo_df = pd.DataFrame(tree.topology_rows())
            st.dataframe(topo_df, hide_index=True, width="stretch", height=min(360, 48 + 28 * len(topo_df)))
            st.download_button(
                "Download topology.csv",
                to_csv_bytes(topo_df),
                "topology.csv",
                key="dl_topology_csv",
            )
        else:
            st.info("No `vav_to_ahu_simple.csv` topology in this package — feeds / fedBy empty.")

        st.markdown("##### Points by equipment")
        for eq in tree.equipment:
            title = f"{eq.equipment_id} · {eq.equipment_type}"
            with st.expander(title, expanded=False):
                if not eq.bindings:
                    st.info(
                        "No point bindings yet — include a sibling Haystack JSON next to "
                        "this equipment CSV in the zip."
                    )
                else:
                    rows = [
                        {
                            "Haystack point": b.haystack_tag,
                            "CSV column": b.csv_column or "—",
                            "In history": "yes" if b.present_in_history else "no",
                            "Rules": ", ".join(b.required_by_rules[:8])
                            + ("…" if len(b.required_by_rules) > 8 else ""),
                        }
                        for b in eq.bindings
                    ]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=280)
                st.caption(f"{len(eq.applicable_rule_ids)} applicable cookbook rules for this type")
        flat = pd.DataFrame(tree.to_rows())
        if not flat.empty:
            st.download_button(
                "Download data_model.csv",
                to_csv_bytes(flat),
                "data_model.csv",
                key="dl_data_model_csv",
            )

        st.divider()
        st.markdown("##### Mapping status")
        st.caption(
            "Maps load from the package: each equipment `history_wide.csv` needs a sibling "
            "`history_wide.json` / `history_wide.column_map.json` / `column_map.json`. "
            "Weather CSV maps are optional. Upload zips via the sidebar."
        )
        from app.role_map_gap import build_role_map_gap_report

        gap_df = build_role_map_gap_report(
            frames,
            st.session_state.role_map,
            weather=st.session_state.weather,
        )
        if not gap_df.empty:
            st.dataframe(gap_df, hide_index=True, width="stretch", height=280)
            st.download_button(
                "Download role_map_gap_report.csv",
                to_csv_bytes(gap_df),
                "role_map_gap_report.csv",
                key="dl_gap_data_model",
            )
        if st.session_state.get("column_map"):
            st.download_button(
                "Download merged column map JSON",
                data=__import__("json").dumps(
                    to_haystack_document(st.session_state.column_map), indent=2
                ).encode(),
                file_name="column_map.json",
                mime="application/json",
                key="dl_colmap_data_model",
            )
        with st.expander("Advanced: edit roles for selected device", expanded=False):
            raw_df = frames[selected]
            inferred = {
                **suggest_roles(raw_df),
                **roles_from_columns_csv(
                    Path(raw_df.attrs.get("columns_path"))
                    if raw_df.attrs.get("columns_path")
                    else None
                ),
            }
            edit = dict(st.session_state.role_map.get(selected, {}))
            # Drop meta keys from the editable role list
            edit.pop("equipment_type", None)
            edit.pop("plant_group", None)
            default_roles = [
                "zone-air-temp",
                "discharge-air-temp",
                "discharge-air-temp-sp",
                "mixed-air-temp",
                "return-air-temp",
                "outside-air-temp",
                "outside-air-damper",
                "cooling-valve",
                "heating-valve",
                "fan-cmd",
                "fan-status",
                "duct-static-pressure",
            ]
            for role in sorted(
                set(list(inferred.keys()) + list(edit.keys()) + default_roles)
            ):
                opts = [""] + list(raw_df.columns)
                cur = edit.get(role, inferred.get(role, ""))
                edit[role] = st.selectbox(
                    role,
                    opts,
                    index=opts.index(cur) if cur in opts else 0,
                    key=f"r_{selected}_{role}",
                )
            edit = {k: v for k, v in edit.items() if v}
            changed = _commit_role_map_edit(selected, edit)
            if changed:
                st.info(
                    "Mapping updated — FDD Plots will re-run this device's rules on next visit "
                    "so charts use the new columns."
                )
            st.caption(
                "Overrides apply in-session; prefer fixing the package sidecar JSON for lasting maps."
            )


    if section == "Run Rules":
        st.subheader("Run rules")
        st.caption(
            "Sidebar sliders only store thresholds — they do **not** re-evaluate rules. "
            "Click **Run** here (or sidebar **Rerun cat.**) after tuning."
        )
        with st.expander("SV-RATE — context-aware sensor rate thresholds", expanded=False):
            _render_sv_rate_config()
        scope = st.radio(
            "Equipment scope",
            ["selected equipment", "all equipment"],
            horizontal=True,
            key="run_scope",
        )
        mode = st.radio(
            "Rule set",
            [f"All {CANONICAL_RULE_COUNT} rules", "One mechanical category"],
            horizontal=True,
            key="run_mode",
        )
        fam_key = None
        if mode == "One mechanical category":
            labels = [family_label(f) for f in FAMILY_ORDER if _rules_by_family().get(f)]
            pick = st.selectbox("Category", labels, key="run_fam_label")
            fam_key = {family_label(f): f for f in FAMILY_ORDER}[pick]

        if st.button("Run", type="primary", key="run_btn"):
            target_rules = RULES if fam_key is None else _rules_by_family().get(fam_key, [])
            eq_list = [selected] if scope == "selected equipment" else sorted(frames, key=natural_key)
            st.session_state.batch_results = _run_rule_list(eq_list, target_rules, frames)
            st.session_state.rules_mapping_rev = st.session_state.get("mapping_rev") or _role_map_fingerprint()
            st.session_state.mapping_stale = False
            st.success(
                f"Ran {len(st.session_state.batch_results)} SQL evaluations (DataFusion) — "
                "open **FDD Plots** for charts, or **RCx Plots**."
            )

    if section == "Results by Category":
        st.subheader("Results by equipment type")
        st.caption(
            "Organized by **device type** (AHU / VAV / plant…), then one table per device. "
            "Not by cookbook rule family — so boilers never appear under AHU."
        )
        results = st.session_state.batch_results
        if not results:
            st.info("Run rules (main tab or sidebar **Rerun cat.**), then review here or on **FDD Plots**.")
        else:
            summary = results_summary_table(results)
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("PASS", int((summary["status"] == "PASS").sum()))
            m2.metric("FAULT", int((summary["status"] == "FAULT").sum()))
            m3.metric("SKIPPED", int((summary["status"] == "SKIPPED_MISSING_ROLES").sum()))
            m4.metric("EQUIP OFF", int((summary["status"] == "SKIPPED_EQUIPMENT_OFF").sum()))
            m5.metric("N/A", int((summary["status"] == "NOT_APPLICABLE_EQUIPMENT_TYPE").sum()))
            m6.metric("ERROR", int((summary["status"] == "ERROR").sum()))

            fps = {
                getattr(r, "params_fingerprint", "")
                for r in results
                if getattr(r, "params_fingerprint", "")
            }
            if len(fps) > 1:
                st.warning(
                    f"Mixed tuning vintages in these results ({len(fps)} distinct param fingerprints). "
                    "Partial re-runs (Rerun cat. / per-device) leave older rows with different thresholds — "
                    "click **Run** for all equipment to refresh everything."
                )

            hide_na = st.checkbox(
                "Hide N/A rows (NOT_APPLICABLE_EQUIPMENT_TYPE)",
                value=True,
                key="results_hide_na",
                help="N/A means the rule does not apply to this equipment type — hide to scan FAULT/PASS faster.",
            )
            view = summary
            if hide_na and not view.empty:
                view = view[view["status"] != "NOT_APPLICABLE_EQUIPMENT_TYPE"]

            # Prefer live typed buckets; fall back to types stamped on results
            type_order = list(by_type.keys()) if by_type else []
            if not type_order and "equipment_type" in summary.columns:
                type_order = sorted(
                    {str(t) for t in summary["equipment_type"].dropna().unique()},
                    key=natural_key,
                )

            for eq_type in type_order:
                device_ids = list(by_type.get(eq_type) or [])
                if not device_ids:
                    # Results-only devices of this type
                    device_ids = sorted(
                        summary.loc[summary["equipment_type"] == eq_type, "equipment_id"]
                        .astype(str)
                        .unique(),
                        key=natural_key,
                    )
                type_rows = view[view["equipment_id"].isin(device_ids)] if not view.empty else view
                if type_rows.empty and hide_na:
                    # Still show type if it has devices but only N/A left
                    raw_type = summary[summary["equipment_id"].isin(device_ids)]
                    if raw_type.empty:
                        continue
                counts = _status_counts(
                    summary[summary["equipment_id"].isin(device_ids)]
                    if not summary.empty
                    else summary
                )
                bits = " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: _STATUS_SORT.get(kv[0], 99)))
                st.markdown(f"### {eq_type} · {len(device_ids)} device(s)")
                if bits:
                    st.caption(bits)

                for eq_id in sorted(device_ids, key=natural_key):
                    tbl = _device_results_table(view if hide_na else summary, eq_id)
                    if tbl.empty:
                        # Device present but filtered out / not run
                        raw_tbl = _device_results_table(summary, eq_id)
                        if raw_tbl.empty:
                            st.markdown(f"**`{eq_id}`** — no results yet")
                            continue
                        n_na = int((raw_tbl["status"] == "NOT_APPLICABLE_EQUIPMENT_TYPE").sum())
                        st.markdown(f"**`{eq_id}`**")
                        st.caption(f"Only N/A rows ({n_na}) — uncheck **Hide N/A** to show.")
                        continue
                    n_fault = int((tbl["status"] == "FAULT").sum())
                    n_pass = int((tbl["status"] == "PASS").sum())
                    st.markdown(
                        f"**`{eq_id}`** — {len(tbl)} row(s)"
                        + (f" · FAULT {n_fault}" if n_fault else "")
                        + (f" · PASS {n_pass}" if n_pass else "")
                    )
                    st.dataframe(tbl, hide_index=True, width="stretch", height=min(420, 48 + 28 * len(tbl)))

            st.download_button(
                "Download full results CSV",
                to_csv_bytes(summary),
                "fdd_results_by_equipment.csv",
                key="dl_results_by_equip",
            )

    if section == "FDD Plots":
        from app.docx_report import applicable_rules_for_equipment
        from app.rule_card import (
            build_rule_card,
            equipment_mapping_coverage,
            filter_status_bucket,
        )

        st.subheader("FDD Plots — rule validation")
        st.caption(
            "Pick a device → rules auto-run → **chart on top**. "
            "Cards below = params + mapping. Camera icon on chart → PNG/JPEG. "
            "One Plotly at a time (low-RAM). "
            "Word report: Generic RCx template on **Overview**."
        )
        st.caption(
            "Economizer **ECON-1…4**, **OA-1**, **DMP-1**, **FC8–11** need OA damper / MAT / OAT "
            "(`oa_damper_pct` → e.g. `mad_c`). **ECON-5** needs heat/preheat. "
            "**FC6** needs AHU `vav_total_flow`. Empty plots are usually **data gaps**."
        )

        type_opts = list(by_type.keys()) or ["UNKNOWN"]
        cur_type = resolve_equipment_type(
            selected, df=frames[selected], role_map=st.session_state.role_map
        )
        type_idx = type_opts.index(cur_type) if cur_type in type_opts else 0
        c_type, c_dev, c_fmt = st.columns([1, 1.2, 0.8])
        with c_type:
            eq_type = st.selectbox("Device type", type_opts, index=type_idx, key="plot_eq_type")
        device_ids = by_type.get(eq_type, [])
        if not device_ids:
            st.warning("No devices of that type.")
        else:
            with c_dev:
                dev_idx = device_ids.index(selected) if selected in device_ids else 0
                device = st.selectbox("Device", device_ids, index=dev_idx, key="plot_device")
            with c_fmt:
                plot_fmt = st.selectbox(
                    "Chart download", ["png", "jpeg", "svg", "webp"], index=0, key="plot_fmt"
                )
            st.session_state.selected_equipment = device
            plot_df, _ = _mapped_equipment(device, frames)
            applicable = applicable_rules_for_equipment(
                device,
                equipment_type=eq_type,
                mapped_df=plot_df,
                role_map=st.session_state.role_map,
            )
            present_n, total_n, cov_pct = equipment_mapping_coverage(
                applicable, device, st.session_state.role_map, plot_df
            )

            # Auto-run when this device has no evaluations yet
            if _ensure_device_rules_run(device, applicable, frames):
                st.caption("Mapping or first visit — re-ran rules for this device so charts match the live role map.")
                st.rerun()

            lookup = _result_lookup(st.session_state.batch_results)

            # Device data strip
            n_rows = int(len(plot_df)) if plot_df is not None and not plot_df.empty else 0
            t0 = t1 = "—"
            if plot_df is not None and not plot_df.empty and isinstance(plot_df.index, pd.DatetimeIndex):
                t0 = str(plot_df.index.min())[:19]
                t1 = str(plot_df.index.max())[:19]
            device_map = dict((st.session_state.role_map or {}).get(device) or {})
            mapped_roles = [
                k for k, v in device_map.items()
                if k not in {"equipment_type", "plant_group"} and v
            ]
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("History rows", f"{n_rows:,}")
            s2.metric("Mapped roles", len(mapped_roles))
            s3.metric("Mapping coverage", f"{cov_pct:.0f}%", help=f"{present_n}/{total_n} unique required roles")
            s4.metric("Rule cards", len(applicable))
            if n_rows:
                st.caption(f"History span: `{t0}` → `{t1}`")

            # Downloads + rerun (Word template lives on Overview only)
            d1, d2, d3 = st.columns([1.1, 1.1, 1])
            with d1:
                try:
                    session_bytes = json.dumps(_session_config_payload(), indent=2).encode("utf-8")
                except Exception:
                    session_bytes = json.dumps(
                        {
                            "schema_version": "openfdd_session_v1",
                            "role_map": st.session_state.get("role_map") or {},
                            "params": st.session_state.get("params") or {},
                        },
                        indent=2,
                    ).encode("utf-8")
                st.download_button(
                    "Download session_config.json",
                    data=session_bytes,
                    file_name="session_config.json",
                    mime="application/json",
                    key=f"dl_session_plots_{device}",
                    help="Current units, prefer_web_oat, full role_map, params.",
                )
            with d2:
                role_bytes = json.dumps(
                    st.session_state.get("role_map") or {}, indent=2
                ).encode("utf-8")
                st.download_button(
                    "Download role_map.json",
                    data=role_bytes,
                    file_name="role_map.json",
                    mime="application/json",
                    key=f"dl_rolemap_plots_{device}",
                    help="Equipment → role → CSV column mapping only.",
                )
            with d3:
                if st.button("Re-run device rules", key="plot_run_device"):
                    new_res = _run_rule_list([device], applicable, frames)
                    keep = [r for r in st.session_state.batch_results if r.equipment_id != device]
                    st.session_state.batch_results = keep + new_res
                    lookup = _result_lookup(st.session_state.batch_results)
                    pref = _preferred_plot_rule_id(applicable, lookup, device)
                    if pref:
                        st.session_state[f"plot_chart_rule_{device}"] = next(
                            (f"{r.id} — {r.title}" for r in applicable if r.id == pref),
                            st.session_state.get(f"plot_chart_rule_{device}"),
                        )
                    st.rerun()

            device_results = [r for r in st.session_state.batch_results if r.equipment_id == device]
            n_fault = sum(1 for r in device_results if r.status == "FAULT")
            n_pass = sum(1 for r in device_results if r.status == "PASS")
            n_skip = sum(
                1
                for r in device_results
                if str(r.status).startswith("SKIPPED")
            )
            st.caption(
                f"`{device}` · {len(applicable)} applicable rules · "
                f"FAULT {n_fault} · PASS {n_pass} · SKIPPED {n_skip} · "
                f"{len(device_results)} evaluations"
            )

            # Chart panel (always on top — never default to "none")
            focus_labels = [f"{r.id} — {r.title}" for r in applicable]
            focus_key = f"plot_chart_rule_{device}"
            if focus_labels:
                pref_id = _preferred_plot_rule_id(applicable, lookup, device)
                pref_label = next(
                    (lab for lab in focus_labels if lab.startswith(f"{pref_id} —")),
                    focus_labels[0],
                )
                if focus_key not in st.session_state or st.session_state[focus_key] not in focus_labels:
                    st.session_state[focus_key] = pref_label
                focus_pick = st.selectbox(
                    "Chart rule (one Plotly at a time)",
                    focus_labels,
                    key=focus_key,
                )
                focus_rule_id = focus_pick.split(" — ", 1)[0].strip()
                focus_rule = next((r for r in applicable if r.id == focus_rule_id), None)
                focus_res = lookup.get((device, focus_rule_id))
                st.markdown(f"##### Chart · `{focus_rule_id}`")
                if focus_rule is None:
                    st.info("No applicable rules for this device type.")
                elif focus_res is None:
                    st.warning("No result for this rule — click **Re-run device rules**.")
                else:
                    status = str(getattr(focus_res, "status", "") or "")
                    st.caption(f"Status: `{status}`")
                    fig = rule_result_chart(
                        plot_df,
                        focus_res,
                        required_roles=focus_rule.required_roles,
                        units_map=units_map,
                    )
                    if fig:
                        st.plotly_chart(
                            fig,
                            width="stretch",
                            config=plotly_config(
                                filename=f"{device}_{focus_rule_id}", fmt=plot_fmt
                            ),
                            key=f"fig_top_{device}_{focus_rule_id}",
                        )
                    else:
                        miss = list(getattr(focus_res, "missing_roles", None) or [])
                        note = str(getattr(focus_res, "notes", "") or "")
                        bits = [f"status `{status}`"]
                        if miss:
                            bits.append("missing: " + ", ".join(miss))
                        if note:
                            bits.append(note[:200])
                        st.info("No Plotly series for this rule — " + " · ".join(bits))
            else:
                focus_rule_id = None
                st.info("No applicable cookbook rules for this equipment type.")

            sens = sensor_fault_summary(plot_df, device_results, equipment_id=device)
            health = sensor_health_matrix(plot_df, device_results, equipment_id=device)
            with st.expander("Sensor health — per sensor", expanded=not health.empty):
                st.caption(
                    "Itemized by HVAC sensor type. Fault hours are **per sensor** "
                    "(RANGE / SPIKE / FLATLINE / STALE / RATE) — not the shared equipment OR window."
                )
                if health.empty:
                    st.info("No mapped sweep sensors on this device yet.")
                else:
                    for stype, block in health.groupby("sensor_type", sort=True):
                        st.markdown(f"**{stype}**")
                        st.dataframe(block.drop(columns=["sensor_type"], errors="ignore"), hide_index=True, width="stretch")
                    st.download_button(
                        "Download sensor health matrix CSV",
                        to_csv_bytes(health),
                        f"{device}_sensor_health.csv",
                        key=f"dl_sens_health_{device}",
                    )
                    pick = st.selectbox(
                        "Sensor detail chart",
                        ["(none)"] + list(health["sensor"].astype(str)),
                        key=f"sens_chart_pick_{device}",
                    )
                    if pick != "(none)" and pick in plot_df.columns:
                        rule_masks: dict = {}
                        for res in device_results:
                            rid = getattr(res, "rule_id", "")
                            metrics = getattr(res, "metrics", {}) or {}
                            if rid in {"SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE"}:
                                masks = metrics.get("sv_sweep_confirmed_roles") or {}
                                if pick in masks:
                                    rule_masks[rid] = masks[pick]
                            elif rid in {"SV-RATE", "SV-SLEW"}:
                                # Rate evidence is aggregate; use equipment confirmed_fault as lane when that role was checked
                                ev = metrics.get("sv_rate_evidence") or []
                                if any(str(e.get("role")) == pick and (e.get("violation_count") or 0) > 0 for e in ev):
                                    if getattr(res, "confirmed_fault", None) is not None:
                                        rule_masks["SV-RATE"] = res.confirmed_fault
                        fig_s = sensor_fault_chart(
                            plot_df[pick],
                            sensor_name=pick,
                            rule_masks=rule_masks,
                        )
                        if fig_s is not None:
                            st.plotly_chart(
                                fig_s,
                                width="stretch",
                                config=plotly_config(filename=f"{device}_{pick}_sensor"),
                                key=f"sens_chart_{device}_{pick}",
                            )
                if not sens.empty:
                    st.markdown("**Faulting sensors — stats**")
                    st.dataframe(sens, width="stretch", height=220)
                    st.download_button(
                        "Download sensor fault stats CSV",
                        to_csv_bytes(sens),
                        f"{device}_sensor_fault_stats.csv",
                        key=f"dl_sens_{device}",
                    )

            st.markdown("##### Rule cards (catalog parity)")
            status_filter = st.radio(
                "Filter cards",
                ["All", "FAULT", "PASS", "SKIPPED", "Not run"],
                horizontal=True,
                index=0,
                key=f"plot_status_filter_{device}",
            )

            from app.rcx_plots import rcx_preset_coverage

            try:
                rcx_cov = rcx_preset_coverage(
                    frames,
                    st.session_state.role_map,
                    weather=st.session_state.weather,
                    schedule=OccupancySchedule.from_dict(
                        st.session_state.get("occupancy_schedule")
                    ),
                    comfort_low_f=float(st.session_state.get("zone_lo_f", 70.0)),
                    comfort_high_f=float(st.session_state.get("zone_hi_f", 75.0)),
                )
            except Exception:
                rcx_cov = pd.DataFrame()
            has_sens_fault = not sens.empty

            cards_shown = 0
            for rule in applicable:
                res = lookup.get((device, rule.id))
                card = build_rule_card(
                    equipment_id=device,
                    rule=rule,
                    result=res,
                    role_map=st.session_state.role_map,
                    mapped_df=plot_df,
                    params=st.session_state.get("params") or {},
                    results=st.session_state.batch_results,
                    rcx_coverage=rcx_cov if not rcx_cov.empty else None,
                    weather=st.session_state.weather,
                    has_sensor_fault_summary=has_sens_fault,
                )
                bucket = filter_status_bucket(card.status)
                if status_filter != "All" and bucket != status_filter:
                    continue
                cards_shown += 1
                title = f"{card.rule_id} — {card.title} · {card.status}"
                with st.expander(title, expanded=(rule.id == focus_rule_id)):
                    if card.description:
                        st.markdown(f"**Summary:** {card.description}")
                    if card.equation:
                        st.markdown(f"**Equation:** {card.equation}")
                    fh = card.fault_hours
                    meta_bits = [f"`{card.status}`"]
                    if fh is not None:
                        meta_bits.append(f"fault hours: {fh:.2f}")
                    # Prefer hours over % when reading tuning changes — startup delay shrinks the denominator.
                    if res is not None and getattr(res, "rule_id", "") == "OAT-METEO":
                        m = getattr(res, "metrics", None) or {}
                        mean_d = m.get("oat_meteo_mean_abs_diff_f")
                        max_d = m.get("oat_meteo_max_abs_diff_f")
                        if mean_d is not None:
                            meta_bits.append(f"mean |BAS−web|: {mean_d:.2f}°F")
                        if max_d is not None:
                            meta_bits.append(f"max |BAS−web|: {max_d:.2f}°F")
                    elif res is not None and getattr(res, "fault_pct", None) is not None:
                        meta_bits.append(f"fault % of active: {res.fault_pct:.1f}")
                    if card.coverage_pct is not None:
                        meta_bits.append(
                            f"required roles: {card.required_roles_present}/{card.required_roles_total}"
                        )
                    if card.missing_roles:
                        meta_bits.append(f"missing: {', '.join(card.missing_roles)}")
                    st.caption(" · ".join(meta_bits))
                    if card.notes:
                        st.caption(card.notes)

                    st.markdown("**Rule facts**")
                    facts = list(card.catalog_facts) + [
                        ("Status", card.status),
                        (
                            "Fault hours",
                            "—" if card.fault_hours is None else f"{card.fault_hours:.2f}",
                        ),
                    ]
                    st.dataframe(
                        pd.DataFrame(facts, columns=["Field", "Value"]),
                        hide_index=True,
                        width="stretch",
                    )

                    st.markdown("**Points → Haystack tags**")
                    if card.points_note:
                        st.caption(card.points_note)
                    if card.mapping_rows:
                        map_df = pd.DataFrame(
                            [
                                {
                                    "role": m.role,
                                    "haystack": m.haystack_tag,
                                    "csv_column": m.csv_column,
                                    "requirement": m.requirement,
                                    "in_history": "yes" if m.in_history else "MISSING",
                                }
                                for m in card.mapping_rows
                            ]
                        )
                        st.dataframe(map_df, hide_index=True, width="stretch")
                    else:
                        st.caption("Sensor/control sweep — applies to present sensors / outputs.")

                    st.markdown("**Plot series**")
                    for bullet in card.plot_series:
                        st.markdown(f"- {bullet}")

                    st.markdown("**Sliders (tune params)**")
                    if card.param_rows:
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "key": p.key,
                                        "label": p.label,
                                        "unit": p.unit,
                                        "value": p.value,
                                        "default": p.default,
                                        "min": p.min,
                                        "max": p.max,
                                        "step": p.step,
                                        "source": p.source,
                                    }
                                    for p in card.param_rows
                                ]
                            ),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.caption("No tune params for this rule.")

                    st.markdown("**Analytics / related views**")
                    st.caption(card.analytics_hint or "—")
                    for line in card.analytics_fit:
                        st.markdown(f"- {line}")

                    if rule.id == focus_rule_id:
                        st.caption("Chart for this rule is in the **panel above**.")

            if cards_shown == 0:
                st.info(f"No cards match filter **{status_filter}**.")
            else:
                st.caption(
                    f"{cards_shown} card(s) · {len(applicable)} applicable rules · "
                    f"traces ≤ {max_plot_points():,} pts"
                )

    if section == "RCx Plots":
        try:
            render_rcx_plots_tab(
                frames,
                st.session_state.role_map,
                weather=st.session_state.weather,
                unit_system=st.session_state.get("unit_system", "imperial"),
                occupancy_schedule=st.session_state.get("occupancy_schedule"),
                zone_lo_f=float(st.session_state.get("zone_lo_f", 70.0)),
                zone_hi_f=float(st.session_state.get("zone_hi_f", 75.0)),
            )
        except Exception as exc:
            st.error(f"RCx Plots failed: {exc}")

    if section == "Metering":
        st.subheader("Metering")
        st.caption(
            "Building / plant electrical and gas meters vs degree-days (web OAT). "
            "Same rollups as RCx metering presets at the end of **RCx Plots** — this section starts "
            "the dedicated Metering category (expand later)."
        )
        from app.metering import build_meter_monthly_table, meter_scatter_frame

        for kind, title, dd_label in (
            ("electric", "Electric (kWh) vs CDD", "CDD"),
            ("gas", "Natural gas vs HDD", "HDD"),
        ):
            st.markdown(f"##### {title}")
            monthly, stats, reason = build_meter_monthly_table(
                frames,
                st.session_state.role_map,
                kind=kind,  # type: ignore[arg-type]
                weather=st.session_state.weather,
            )
            if reason or monthly.empty:
                st.info(reason or "No meter series for this package.")
                continue
            energy_col = "kwh" if kind == "electric" else "gas_qty"
            bar = monthly_energy_bar(
                monthly,
                energy_col=energy_col,
                title=f"Monthly {energy_col} by meter",
            )
            if bar is not None:
                st.plotly_chart(
                    bar,
                    width="stretch",
                    config=plotly_config(filename=f"meter_{kind}_bar"),
                    key=f"meter_{kind}_bar",
                )
            scatter_df = meter_scatter_frame(monthly, kind=kind)  # type: ignore[arg-type]
            scat = energy_degree_day_scatter(
                scatter_df,
                x_title=dd_label,
                y_title=energy_col,
                title=f"{title} scatter",
            )
            if scat is not None:
                st.plotly_chart(
                    scat,
                    width="stretch",
                    config=plotly_config(filename=f"meter_{kind}_scatter"),
                    key=f"meter_{kind}_scatter",
                )
            if stats is not None and not stats.empty:
                st.dataframe(stats, hide_index=True, width="stretch")
            st.download_button(
                f"Download {kind} monthly CSV",
                to_csv_bytes(monthly),
                f"meter_{kind}_monthly.csv",
                key=f"dl_meter_{kind}",
            )

    if section == "Export":
        st.subheader("Export")
        st.caption(
            "One big dump for WattLab (vibe20): every FDD rule, analytic CSVs, "
            "sensor stats / 24h diurnal profiles (fan on/off × weekday/weekend/holiday), "
            "setpoints, schedules, weather, data-derived model seed, and MANIFEST.json. "
            "Session restore stays below; individual CSVs live under the expander."
        )
        results = st.session_state.batch_results

        st.markdown("##### WattLab dump (vibe20 handoff)")
        if not frames:
            st.info("Load a package first — the dump needs equipment data.")
        else:
            profile_options = {
                "Summary (default)": "summary",
                "Diagnostic": "diagnostic",
                "Forensic": "forensic",
            }
            # Durable non-widget key survives Export unmount; widget key is re-seeded.
            if "wattlab_export_profile" not in st.session_state:
                st.session_state["wattlab_export_profile"] = "summary"
            if "wattlab_export_profile_label" not in st.session_state:
                rev = {v: k for k, v in profile_options.items()}
                st.session_state["wattlab_export_profile_label"] = rev.get(
                    st.session_state["wattlab_export_profile"],
                    "Summary (default)",
                )
            profile_label = st.selectbox(
                "Export profile",
                options=list(profile_options),
                key="wattlab_export_profile_label",
                help=(
                    "Summary: shared telemetry + analytic tables, no per-rule timeseries. "
                    "Diagnostic: FAULT/ERROR evidence. Forensic: applicable evidence."
                ),
            )
            st.session_state["wattlab_export_profile"] = profile_options.get(
                str(profile_label), "summary"
            )
            if st.button("Build WattLab dump (zip)", type="primary", key="wattlab_dump_build"):
                with st.spinner("Running analytics + writing bundle…"):
                    try:
                        data, fname = _build_wattlab_dump_zip(
                            profile=st.session_state.get("wattlab_export_profile", "summary")
                        )
                        st.session_state["wattlab_dump_zip"] = (data, fname)
                        st.success(f"Dump ready · {len(data) / 1e6:.1f} MB — see README_WATTLAB.md inside")
                    except Exception as exc:
                        st.error(f"WattLab dump failed: {exc}")
            dump = st.session_state.get("wattlab_dump_zip")
            if dump:
                st.download_button(
                    "Download WattLab dump (zip)",
                    data=dump[0],
                    file_name=dump[1],
                    mime="application/zip",
                    key="wattlab_dump_dl",
                )

        st.markdown("##### Session restore")
        _render_session_config_io(key_prefix="export")

        with st.expander("Individual exports (summary CSV, column map, gap report, tuning report)"):
            if results:
                summary = results_summary_table(results)
                st.download_button("Summary CSV", to_csv_bytes(summary), "fdd_summary.csv")
            if st.session_state.column_map:
                st.download_button(
                    "Haystack column map JSON",
                    data=__import__("json").dumps(
                        to_haystack_document(st.session_state.column_map), indent=2
                    ).encode(),
                    file_name="column_map.json",
                    mime="application/json",
                    key="dl_colmap_export",
                )
            if frames:
                from app.role_map_gap import build_role_map_gap_report

                gap_df = build_role_map_gap_report(
                    frames,
                    st.session_state.role_map,
                    weather=st.session_state.weather,
                )
                if not gap_df.empty:
                    st.markdown("##### Role map gap report")
                    st.dataframe(gap_df, hide_index=True, width="stretch", height=280)
                    st.download_button(
                        "Download role_map_gap_report.csv",
                        to_csv_bytes(gap_df),
                        "role_map_gap_report.csv",
                        key="dl_gap_export",
                    )
                try:
                    from app.tuning_report import build_tuning_assistant_report

                    trep = build_tuning_assistant_report(
                        tuned=results or [],
                        params=st.session_state.get("params") or {},
                        has_web_weather=st.session_state.weather is not None,
                        gap_report=gap_df,
                    )
                    st.download_button(
                        "Download tuning_assistant_report.json",
                        data=__import__("json").dumps(trep, indent=2, default=str).encode("utf-8"),
                        file_name="tuning_assistant_report.json",
                        mime="application/json",
                        key="dl_tuning_report",
                    )
                except Exception:
                    pass

        st.caption(
            "Word report: download the Generic RCx template from the **Overview** section."
        )


if __name__ == "__main__":
    main()
