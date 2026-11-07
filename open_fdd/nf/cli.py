"""``open-fdd-nf``: read a Normal Framework box (LAN or Normal Online portal) from the shell.

    open-fdd-nf info
    open-fdd-nf model [--site S] [--json]
    open-fdd-nf pull --equip AHU-1 --days 7 --out ahu1.csv
    open-fdd-nf rules --days 7 [--rules ECON-1,FC1] [--json]
    open-fdd-nf report --days 7 --out report_dir [--findings]
    open-fdd-nf analyze weekly-runtime --site S --days 28 [--json]       (read-only tools run on the box)

Connection: ``--url`` or the environment (``NF_URL`` / ``NF_LAN_URL`` / ``NFURL``,
``NF_CLIENT_ID`` + ``NF_CLIENT_SECRET`` or ``NF_CONSOLE_USER`` + ``NF_CONSOLE_PASSWORD``,
``NF_CA_FILE``), optionally topped up from ``--env FILE``. ``--via lan|portal`` picks the URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from open_fdd.nf.analytics import SHORT, TOOLS
from open_fdd.nf.client import NFClient, NFError

_ANALYZE_HELP = """Run one read-only analytics tool through NF's StartHook (POST /api/v1/apps/open-fdd/hooks/analytics)
and print the answer. Every row is keyed by equipUuid (with siteRef and equipRef), so two sites that both have an
AHU-1 never share a row. The tools cannot write points, schedules or BACnet values.

  weekly-runtime  per ISO week: run_hours, schedule_hours, in_schedule_hours, after_hours, partial_week, mean_oat_on_c
  cooling         hours per SI outdoor-air bin (<10, 10-16, 16-21, 21-27, 27-32, >=32 degC), fine 5-minute grid
  economizer      n, n_identifiable, median_residual_k, mae_k
  fault-timeline  confirmed / ok / unknown per assessed timestamp (needs --equip and --rule)
  roles           the roles bound to one equip (--equip = NF uuid, or an id with --site; ambiguous = error)
  explain-view    why an RCx view is not available (needs --view)
"""

def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("connection")
    g.add_argument("--url", help="NF base URL (overrides the environment)")
    g.add_argument("--env", metavar="FILE", default=os.environ.get("NF_ENV_FILE", ""),
                   help="KEY=VALUE env file with NF_* settings (default: $NF_ENV_FILE; real environment wins)")
    g.add_argument("--via", choices=("lan", "portal"),
                   help="lan: prefer NF_LAN_URL; portal: prefer NFURL (Normal Online)")
    g.add_argument("--ca-file", help="trust this self-signed LAN certificate (default: $NF_CA_FILE)")
    g.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds (default 60)")
    s = p.add_argument_group("scope")
    s.add_argument("--site", help="site id or name (default: every site)")
    s.add_argument("--equip", help="equipment id or name (default: every equipment)")
    return p


def _range(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("time range (UTC)")
    g.add_argument("--days", type=float, default=7.0, help="trailing days ending now (default 7)")
    g.add_argument("--start", help="ISO start, e.g. 2026-11-01T00:00:00Z (with --end instead of --days)")
    g.add_argument("--end", help="ISO end (default now)")
    g.add_argument("--window", type=int, default=300, help="NF resample window seconds (default 300)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="open-fdd-nf", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{info,model,pull,rules,report,analyze}")
    c = _common()
    sub.add_parser("info", parents=[c], help="platform info and the sites in the model")
    m = sub.add_parser("model", parents=[c], help="equipment with the points bound to each FDD role")
    m.add_argument("--json", action="store_true", help="full JSON instead of a table")
    pl = sub.add_parser("pull", parents=[c], help="history of the bound roles as SI CSV (or parquet)")
    _range(pl)
    pl.add_argument("--out", required=True, help=".csv (or .parquet when pyarrow is installed)")
    r = sub.add_parser("rules", parents=[c], help="run the pandas reference rules and print a summary")
    _range(r)
    r.add_argument("--rules", help="comma list of rule ids (default: every applicable rule)")
    r.add_argument("--all", action="store_true", help="include ok / not-assessed rows (default: faults only)")
    r.add_argument("--json", action="store_true", help="JSON records instead of a table")
    rp = sub.add_parser("report", parents=[c], help="rules.csv + summary.md (and findings with --findings)")
    _range(rp)
    rp.add_argument("--out", required=True, help="output directory")
    rp.add_argument("--findings", action="store_true",
                    help="also build the Engineering Findings report (reporting extra)")
    rp.add_argument("--docx", action="store_true", help="with --findings, also write DOCX")
    an = sub.add_parser(
        "analyze", parents=[c], formatter_class=argparse.RawDescriptionHelpFormatter,
        help="read-only agent analytics tools, run by the NF app's analytics hook (math stays in JS)",
        description=_ANALYZE_HELP)
    an.add_argument("tool", choices=sorted(SHORT) + list(TOOLS), metavar="TOOL",
                    help="; ".join(f"{k} = {v}" for k, v in SHORT.items()) + " (or the full tool name)")
    an.add_argument("--rule", help="rule id (fault-timeline), e.g. ECON-1")
    an.add_argument("--days", type=float, help="trailing days (hook defaults: 28 weekly-runtime / cooling, 7 economizer, 1 fault-timeline)")
    an.add_argument("--view", help="RCx view id (explain-view), e.g. weekly-fan")
    an.add_argument("--dense", action="store_true", help="fault-timeline: every 5-minute sample, not just state changes")
    an.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the hook run (default 120)")
    an.add_argument("--json", action="store_true", help="the hook's full JSON answer instead of a table")
    return ap


def client_from_args(a: argparse.Namespace) -> NFClient:
    env = dict(os.environ)
    if a.url:
        for k in ("NF_URL", "NF_LAN_URL", "NFURL"):
            env[k] = a.url
    if a.ca_file:
        env["NF_CA_FILE"] = a.ca_file
    return NFClient.from_env(via=a.via, env_file=a.env or None, env=env, timeout=a.timeout)


def time_range(a: argparse.Namespace) -> tuple[datetime, datetime]:
    from open_fdd.nf.client import parse_nf_ts
    from open_fdd.nf.model import default_range

    if a.start:
        end = parse_nf_ts(a.end) if a.end else datetime.now(timezone.utc).replace(microsecond=0)
        return parse_nf_ts(a.start), end
    return default_range(a.days)


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "(none)"
    blank = lambda v: v is None or (isinstance(v, float) and v != v)  # noqa: E731
    data = [["" if blank(r.get(c)) else str(r.get(c)) for c in cols] for r in rows]
    w = [max(len(c), *(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    line = lambda cells: "  ".join(x.ljust(w[i]) for i, x in enumerate(cells)).rstrip()  # noqa: E731
    return "\n".join([line(cols), line(["-" * n for n in w]), *(line(d) for d in data)])


def _frames(a: argparse.Namespace, client: NFClient):
    from open_fdd.nf.model import equipment_frames, load_model

    start, end = time_range(a)
    model = load_model(client)
    frames = equipment_frames(client, model, start, end, window_sec=a.window, site=a.site, equip=a.equip)
    return model, frames


def cmd_info(a: argparse.Namespace) -> int:
    client = client_from_args(a)
    info = client.platform_info()
    sites = client.sites()
    print(json.dumps({"url": client.base_url, "platform": info, "sites": sites}, indent=2, default=str))
    return 0


def cmd_model(a: argparse.Namespace) -> int:
    from open_fdd.nf.model import bind_equipment, load_model, model_summary

    client = client_from_args(a)
    model = load_model(client)
    binds = [b for b in bind_equipment(model, site=a.site, equip=a.equip)]
    rows = model_summary(model, binds)
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    flat = [{"site": r["site"], "equip": r["equip"], "type": r["type"] or "-",
             "roles": len(r["roles"]), "columns": ",".join(v["column"] for v in r["roles"].values())}
            for r in rows]
    print(_table(flat, ["site", "equip", "type", "roles", "columns"]))
    return 0


def cmd_pull(a: argparse.Namespace) -> int:
    import pandas as pd

    client = client_from_args(a)
    _, frames = _frames(a, client)
    if not frames:
        raise NFError("no history for the selected equipment in that range (check `open-fdd-nf model`)")
    parts = []
    for (_, equip), df in frames.items():
        units = df.attrs.get("role_units", {})
        parts.append(df.rename(columns=lambda c, e=equip: f"{e} {c} [{units.get(c, '')}]"))
    wide = pd.concat(parts, axis=1).sort_index()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".parquet":
        try:
            wide.to_parquet(out)
        except ImportError as exc:
            raise NFError("parquet output needs pyarrow (pip install pyarrow); use a .csv name instead") from exc
    else:
        wide.to_csv(out, encoding="utf-8-sig")
    print(f"wrote {out} ({len(wide)} rows x {wide.shape[1]} columns, SI units)")
    return 0


def cmd_rules(a: argparse.Namespace) -> int:
    from open_fdd.nf.rules import run_rules

    client = client_from_args(a)
    _, frames = _frames(a, client)
    table = run_rules(frames, rules=a.rules.split(",") if a.rules else None)
    shown = table if a.all else table[table["status"].isin(["fault", "error"])]
    if a.json:
        print(shown.to_json(orient="records", indent=2))
    else:
        counts = table["status"].value_counts().to_dict()
        print(f"{len(frames)} equipment, {len(table)} rule results: "
              + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"))
        print(_table(shown.drop(columns=["notes", "missing_roles"]).to_dict("records"),
                     ["site", "equip", "rule", "status", "fault_hours", "fault_pct", "coverage"]))
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    from open_fdd.nf.report import write_report

    client = client_from_args(a)
    model, frames = _frames(a, client)
    from open_fdd.nf.model import site_name

    building = site_name(model, a.site) if a.site else ", ".join(
        (s.get("attrs") or {}).get("dis") or s.get("name", "") for s in model.sites)
    written = write_report(frames, a.out, building=building, findings=a.findings, docx=a.docx)
    print(json.dumps(written, indent=2))
    return 0


def _analyze_tables(tool: str, out: dict[str, Any]) -> list[str]:
    """Plain-text view of one tool's answer (the JSON is the contract; this is for people)."""
    ident = ["siteRef", "equipRef", "equipUuid"]
    if tool == "analyze_ahu_weekly_runtime":
        return [_table(out["rows"], ident + ["week", "run_hours", "schedule_hours", "in_schedule_hours", "after_hours",
                                              "partial_week", "mean_oat_on_c", "schedule_source"])]
    if tool == "analyze_mechanical_cooling":
        flat = [{**{k: r.get(k) for k in ident + ["signal_role", "total_hours"]}, **{b["label"]: b["hours"] for b in r.get("bins", [])}}
                for r in out["rows"]]
        labels = [b["label"] for b in (out["rows"][0].get("bins", []) if out["rows"] else [])]
        return [_table(flat, ident + ["signal_role", *labels, "total_hours"])]
    if tool == "analyze_economizer":
        return [_table(out["rows"], ident + ["n", "n_identifiable", "median_residual_k", "mae_k"])]
    if tool == "get_fdd_fault_timeline":
        s = out["summary"]
        head = (f"{out['siteRef']}/{out['equipRef']} ({out['equipUuid']}) {out['rule']} source={out['source']}"
                f"{' (approximate)' if out.get('approximate') else ''}: {s['confirmed']} confirmed, {s['ok']} ok, "
                f"{s['unknown']} unknown samples; last state {s['last_state']}")
        return [head, _table(out["timeline"], ["ts", "state"])]
    if tool == "resolve_equipment_roles":
        rows = [{"role": role, "points": len(pts), "uuid": pts[0]["uuid"], "dis": pts[0].get("dis"), "units": pts[0].get("units")}
                for role, pts in sorted(out["roles"].items())]
        return [f"{out['siteRef']}/{out['equipRef']} ({out['equipUuid']}) kinds: {', '.join(out['kinds']) or '-'}",
                _table(rows, ["role", "points", "uuid", "dis", "units"]),
                "runnable rules: " + (", ".join(out["runnable_rules"]) or "(none)")]
    if tool == "explain_missing_rcx_view":
        v = out["view"]
        lines = [f"{v['id']} ({v['title']}): {'available' if out['available'] else 'NOT available'}"]
        lines += [f"  - {r}" for r in out["reasons"]]
        lines.append(_table([{**e, "missing_roles": ",".join(e["missing_roles"]), "no_data_roles": ",".join(e["no_data_roles"])}
                             for e in out["equips"]], ident + ["status", "missing_roles", "no_data_roles"]))
        return lines
    return [json.dumps(out, indent=2)]


def cmd_analyze(a: argparse.Namespace) -> int:
    from open_fdd.nf.analytics import analyze

    client = client_from_args(a)
    out = analyze(client, a.tool, timeout=a.wait, site=a.site, equip=a.equip, rule=a.rule, days=a.days, view=a.view,
                  dense=a.dense)
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    if out.get("truncated"):
        print("(answer truncated by the hook; narrow with --site / --equip / --days)", file=sys.stderr)
    print("\n".join(_analyze_tables(out["tool"], out)))
    return 0


COMMANDS = {"info": cmd_info, "model": cmd_model, "pull": cmd_pull, "rules": cmd_rules, "report": cmd_report,
            "analyze": cmd_analyze}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # units like inH2O with a subscript crash cp1252 consoles
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except NFError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        print(f"error: missing dependency ({exc}); pip install 'open-fdd[nf]'", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
