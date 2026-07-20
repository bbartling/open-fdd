"""Generate vibe19_agent_spec/docs/RULE_PLOT_CATALOG.md from the live catalog."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.column_map_json import COOKBOOK_TO_HAYSTACK_POINT, FAMILY_LABELS, FAMILY_ORDER
from app.rule_plot_meta import (
    EXTENDED_HS,
    analytics_hint,
    catalog_fields,
    haystack_rows,
    haystack_tag,
    plot_series_bullets,
    points_haystack_note,
)
from app.rules import CANONICAL_RULE_COUNT
from app.rules.cookbook_catalog import RULES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "vibe19_agent_spec" / "docs" / "RULE_PLOT_CATALOG.md"


def main() -> None:
    lines: list[str] = []
    L = lines.append

    L(f"# Rule plot catalog (all {CANONICAL_RULE_COUNT})")
    L("")
    L("**Audience:** agents / engineers reviewing **Plots** validation cards and FDD DOCX.")
    L("")
    L("One section per cookbook rule, grouped by **mechanical family** (same order as sidebar / Results).")
    L(
        "Each chart plots **required (+ optional) roles** present on the mapped frame, "
        "plus a **confirmed-fault swim lane**."
    )
    L("")
    L("| Source | Path |")
    L("| --- | --- |")
    L("| Catalog | `app/rules/cookbook_catalog.py` |")
    L("| Shared meta | `app/rule_plot_meta.py` |")
    L("| Haystack export map | `app/column_map_json.py` → `COOKBOOK_TO_HAYSTACK_POINT` |")
    L("| Gates | `app/rules/operational_gate.py` → `RULE_GATES` |")
    L("| Chart API | `app/charts.py` → `rule_result_chart` |")
    L("| UX contract | [`PLOTS_DOCX_VALIDATION.md`](PLOTS_DOCX_VALIDATION.md) |")
    L("| Machine inventory | `configs/rule_inventory.yaml` (regenerate: `scripts/generate_rule_configs.py`) |")
    L("")
    L("**Haystack note:** Preferred tags come from `COOKBOOK_TO_HAYSTACK_POINT`. Roles not in that dict")
    L("use the extended names in Appendix B (hyphenated Project Haystack–style).")
    L("")
    L("**Sliders:** sidebar **Rule tuning** by category; values live in `session_state.params[rule_id]`.")
    L("Confirm delay is usually `confirm_min` (minutes) even when catalog `confirm_seconds` differs.")
    L("")
    L("---")
    L("")
    L("## Index by family")
    L("")
    L("| Family | Count | Rule ids |")
    L("| --- | ---: | --- |")

    by_fam: dict[str, list] = defaultdict(list)
    for r in RULES:
        by_fam[r.family].append(r)

    for fam in FAMILY_ORDER:
        rules = by_fam.get(fam) or []
        if not rules:
            continue
        ids = ", ".join(f"`{r.id}`" for r in rules)
        L(f"| {FAMILY_LABELS.get(fam, fam)} | {len(rules)} | {ids} |")

    n = sum(len(by_fam[f]) for f in FAMILY_ORDER if by_fam.get(f))
    assert n == CANONICAL_RULE_COUNT, n

    for fam in FAMILY_ORDER:
        rules = by_fam.get(fam) or []
        if not rules:
            continue
        L("")
        L("---")
        L("")
        L(f"## {FAMILY_LABELS.get(fam, fam)}")
        L("")

        for r in rules:
            fields = catalog_fields(r)
            L(f"### `{r.id}` — {r.title}")
            L("")
            L(f"**Summary:** {r.summary or r.title}")
            L("")
            L(f"**Equation:** {r.equation}")
            L("")
            L("| Field | Value |")
            L("| --- | --- |")
            L(f"| Family | `{fields.family}` |")
            L(f"| Equipment kinds | {', '.join(f'`{k}`' for k in fields.equipment_kinds)} |")
            L(f"| Operational gate | `{fields.gate_mode}` |")
            L(f"| Default confirm | {fields.confirm_seconds:g}s |")
            L(f"| Sweep | {fields.sweep_label if fields.sweep_label == '—' else ', '.join(f'`{f}`' for f in fields.sweep_label.split(', '))} |")
            L("")

            L("#### Points → Haystack tags (this chart)")
            L("")
            note = points_haystack_note(r)
            if note and (r.sensor_sweep or r.control_output_sweep):
                L(
                    "Sweep rule: plots **sensors / control outputs present** on the equipment "
                    "(see sweep role lists in `cookbook_catalog.py`). No fixed required-role list."
                )
                L("")
            hs = haystack_rows(r)
            if hs:
                L("| Cookbook role | Haystack-like tag | Requirement |")
                L("| --- | --- | --- |")
                for row in hs:
                    L(f"| `{row.role}` | `{row.haystack_tag}` | {row.requirement} |")
                L("")
            elif not (r.sensor_sweep or r.control_output_sweep):
                L("_No fixed roles._")
                L("")

            L("#### Plot series")
            L("")
            for bullet in plot_series_bullets(r):
                if " → " in bullet and not bullet.startswith("Present") and not bullet.startswith("Chart"):
                    role, tag = bullet.split(" → ", 1)
                    L(f"- `{role}` → `{tag}`")
                elif bullet.startswith("confirmed_fault"):
                    L("- `confirmed_fault` swim lane (bool shade) when the rule was run")
                else:
                    L(f"- {bullet}")
            L("")

            L("#### Sliders (tune params)")
            L("")
            if r.params:
                L("| Key | Label | Unit | Default | Min | Max | Step |")
                L("| --- | --- | --- | ---: | ---: | ---: | ---: |")
                for p in r.params:
                    L(
                        f"| `{p.key}` | {p.label} | {p.unit} | {p.default:g} | "
                        f"{p.min:g} | {p.max:g} | {p.step:g} |"
                    )
            else:
                L("_No tune params_ (confirm may still appear via shared confirm slider).")
            L("")

            L("#### Analytics / related views")
            L("")
            L(analytics_hint(r.id))
            L("")

    L("---")
    L("")
    L("## Appendix A — `COOKBOOK_TO_HAYSTACK_POINT` (canonical export)")
    L("")
    L("| Cookbook role | Haystack-like tag |")
    L("| --- | --- |")
    for role, tag in sorted(COOKBOOK_TO_HAYSTACK_POINT.items()):
        L(f"| `{role}` | `{tag}` |")

    L("")
    L("## Appendix B — Extended Haystack-style names used in this catalog")
    L("")
    L("These roles appear on rules but are **not** yet keys in `COOKBOOK_TO_HAYSTACK_POINT`.")
    L("Prefer adding them to the dict when you next touch mapping exports.")
    L("")
    L("| Cookbook role | Suggested Haystack-like tag |")
    L("| --- | --- |")
    for role, tag in sorted(EXTENDED_HS.items()):
        if role not in COOKBOOK_TO_HAYSTACK_POINT:
            L(f"| `{role}` | `{tag}` |")

    L("")
    L("## Appendix C — Related RCx presets (not the 50)")
    L("")
    L(
        "See [`RCX_PLOTS.md`](RCX_PLOTS.md). Reset scatters / duct-static box "
        "share roles with plant/AHU rules above."
    )
    L("")
    L("## Appendix D — Building-level analytics (not per-rule charts)")
    L("")
    L("| View | Where | Roles / inputs |")
    L("| --- | --- | --- |")
    L("| Motor weekly runtime | Overview | fan/pump/compressor **status** preferred |")
    L(
        "| Mech-cooling OAT bins | Overview | plant pump/status or DX compressor; "
        "**web OAT**; never CHW valve % |"
    )
    L("| Sensor fault summary | Plots (device) | sensors involved in FAULT SV-* |")
    L("| Occupancy calendar | Overview | writes `occ_mode` for SCHED-1 |")
    L("| RCx catalog DOCX | RCx Plots / Export | catalog + filled analytics when data-model fit |")
    L("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(lines)} lines, {len(RULES)} rules)")


if __name__ == "__main__":
    main()
