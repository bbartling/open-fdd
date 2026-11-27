"""open_fdd.scorecard: portable rule scorecard (stdlib only), its SQL on SQLite and, when available, PostgreSQL."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from open_fdd.scorecard import SQL_PATH, Config, score, wilson_interval
from open_fdd.scorecard.cli import main


def _res(eq, rule, start, status, hours=1):
    h = int(start[11:13])
    return {"equipment_id": eq, "rule_id": rule, "window_start": start,
            "window_end": f"{start[:11]}{h + hours:02d}:00:00Z", "status": status}


RESULTS = [
    # AHU-F is labeled faulted 01:00-04:00, AHU-N labeled normal all day.
    _res("AHU-F", "FC1", "2026-01-01T00:00:00Z", "PASS"),   # before the fault: unlabeled
    _res("AHU-F", "FC1", "2026-01-01T01:00:00Z", "PASS"),   # FN
    _res("AHU-F", "FC1", "2026-01-01T02:00:00Z", "FAULT"),  # TP, lead 1 h
    _res("AHU-F", "FC1", "2026-01-01T03:00:00Z", "FAULT"),  # TP
    _res("AHU-N", "FC1", "2026-01-01T01:00:00Z", "FAULT"),  # FP
    _res("AHU-N", "FC1", "2026-01-01T02:00:00Z", "PASS"),   # TN
    _res("AHU-N", "FC1", "2026-01-01T03:00:00Z", "INCONCLUSIVE"),  # not assessed
    _res("AHU-N", "FC8", "2026-01-01T01:00:00Z", "FAULT"),  # technician: false positive (rule-specific)
    _res("AHU-X", "FC8", "2026-01-01T01:00:00Z", "FAULT"),  # unlabeled -> review queue
]
LABELS = [
    {"equipment_id": "AHU-F", "start_ts": "2026-01-01T01:00:00Z", "end_ts": "2026-01-01T04:00:00Z",
     "label": "fault", "rule_id": "", "fault_type": "SAT bias", "source": "dataset"},
    {"equipment_id": "AHU-N", "start_ts": "2026-01-01T00:00:00Z", "end_ts": "2026-01-02T00:00:00Z",
     "label": "normal", "rule_id": "", "fault_type": "", "source": "dataset"},
    {"equipment_id": "AHU-N", "start_ts": "2026-01-01T01:00:00Z", "end_ts": "2026-01-01T02:00:00Z",
     "label": "false_positive", "rule_id": "FC8", "fault_type": "", "source": "technician"},
]


def _by_rule(card):
    return {r["rule_id"]: r for r in card["rules"]}


def test_confusion_counts_and_rates():
    card = score(RESULTS, LABELS)
    fc1 = _by_rule(card)["FC1"]
    assert (fc1["tp"], fc1["fp"], fc1["fn"], fc1["tn"]) == (2, 1, 1, 1)
    assert fc1["not_assessed"] == 1 and fc1["unlabeled"] == 1
    assert fc1["precision"] == pytest.approx(2 / 3)
    assert fc1["recall"] == pytest.approx(2 / 3)
    assert fc1["fpr"] == pytest.approx(0.5)
    assert fc1["false_positive_share"] == pytest.approx(1 / 3)
    assert fc1["lead_time_h_median"] == pytest.approx(1.0)
    fc8 = _by_rule(card)["FC8"]
    assert (fc8["tp"], fc8["fp"]) == (0, 1)          # technician verdict counted
    assert fc8["unlabeled_faults"] == 1
    assert [q["equipment_id"] for q in card["review_queue"]] == ["AHU-X"]


def test_rule_specific_label_beats_generic():
    labels = LABELS + [{"equipment_id": "AHU-F", "start_ts": "2026-01-01T03:00:00Z",
                        "end_ts": "2026-01-01T04:00:00Z", "label": "normal", "rule_id": "FC1"}]
    fc1 = _by_rule(score(RESULTS, labels))["FC1"]
    assert (fc1["tp"], fc1["fp"]) == (1, 2)


def test_prior_blends_toward_public_estimate():
    prior = {"rules": [{"rule_id": "FC1", "precision": 0.9}]}
    fc1 = _by_rule(score(RESULTS, LABELS, prior=prior, prior_weight=10))["FC1"]
    assert fc1["p_true_fault"] == pytest.approx((2 + 10 * 0.9) / (3 + 10))
    no_prior = _by_rule(score(RESULTS, LABELS))["FC1"]
    assert no_prior["p_true_fault"] == pytest.approx(2 / 3)


def test_config_maps_partner_columns_and_values():
    cfg = Config(results={"equipment_id": "equip", "rule_id": "rule", "window_start": "t0", "window_end": "t1",
                          "status": "result"},
                 status_map={"1": "FAULT", "0": "PASS"})
    rows = [{"equip": r["equipment_id"], "rule": r["rule_id"], "t0": r["window_start"], "t1": r["window_end"],
             "result": {"FAULT": "1", "PASS": "0"}.get(r["status"], "n/a")} for r in RESULTS]
    assert _by_rule(score(rows, LABELS, cfg))["FC1"]["tp"] == 2


def test_timezone_offsets_normalized():
    rows = [dict(r, window_start=r["window_start"].replace("T02:00:00Z", "T03:00:00+01:00"),
                 window_end=r["window_end"].replace("T03:00:00Z", "T04:00:00+01:00")) for r in RESULTS]
    assert _by_rule(score(rows, LABELS))["FC1"]["tp"] == 2


def test_bad_label_value_rejected():
    with pytest.raises(ValueError):
        score(RESULTS, [dict(LABELS[0], label="maybe")])


def test_wilson():
    assert wilson_interval(0, 0) == (None, None)
    lo, hi = wilson_interval(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.97


def test_cli_roundtrip(tmp_path, capsys):
    import csv
    for name, rows in (("r.csv", RESULTS), ("l.csv", LABELS)):
        with open(tmp_path / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    rc = main(["run", "--results", str(tmp_path / "r.csv"), "--labels", str(tmp_path / "l.csv"),
               "--json", str(tmp_path / "c.json"), "--queue", str(tmp_path / "q.csv")])
    assert rc == 0
    assert "| FC1 | 2 | 1 | 1 | 1 |" in capsys.readouterr().out
    assert json.loads((tmp_path / "c.json").read_text())["rules"][0]["rule_id"] == "FC1"
    assert "AHU-X" in (tmp_path / "q.csv").read_text()
    assert main(["sql"]) == 0


@pytest.mark.skipif(not os.environ.get("OPENFDD_SCORECARD_PG_DSN") or not shutil.which("psql"),
                    reason="set OPENFDD_SCORECARD_PG_DSN to run the SQL in PostgreSQL")
def test_same_sql_in_postgres():
    dsn = os.environ["OPENFDD_SCORECARD_PG_DSN"]
    def lit(v):
        return "NULL" if v in ("", None) else "'" + str(v).replace("'", "''") + "'"
    status = {"FAULT": "FAULT", "PASS": "PASS"}
    vals_r = ",".join(f"({lit(r['equipment_id'])},{lit(r['rule_id'])},{lit(r['window_start'])}::timestamptz,"
                      f"{lit(r['window_end'])}::timestamptz,{lit(status.get(r['status'], 'NA'))})" for r in RESULTS)
    lab = {"fault": "fault", "normal": "normal", "false_positive": "normal"}
    vals_l = ",".join(f"({lit(l['equipment_id'])},{lit(l['start_ts'])}::timestamptz,{lit(l['end_ts'])}::timestamptz,"
                      f"{lit(lab[l['label']])},{lit(l['rule_id'])})" for l in LABELS)
    script = (f"CREATE TEMP VIEW scorecard_results(equipment_id,rule_id,window_start,window_end,status) AS VALUES {vals_r};\n"
              f"CREATE TEMP VIEW scorecard_labels(equipment_id,start_ts,end_ts,label,rule_id) AS VALUES {vals_l};\n"
              + SQL_PATH.read_text())
    out = subprocess.run(["psql", dsn, "-X", "-q", "-A", "-t", "-F", ",", "-v", "ON_ERROR_STOP=1"],
                         input=script, capture_output=True, text=True, check=True).stdout
    pg = {line.split(",")[0]: [int(x) for x in line.split(",")[1:]] for line in out.split() if line}
    lite = {r["rule_id"]: [r[k] for k in ("tp", "fp", "fn", "tn", "not_assessed", "unlabeled", "unlabeled_faults")]
            for r in score(RESULTS, LABELS)["rules"]}
    assert pg == lite


def test_lbnl_export_feeds_scorecard(tmp_path):
    pytest.importorskip("pandas")
    import csv
    from pathlib import Path

    from open_fdd.ml import lbnl
    from open_fdd.scorecard.core import read_csv

    fixtures = sorted((Path(__file__).parent / "fixtures" / "lbnl_sdahu").glob("*.csv"))
    paths = lbnl.export_long(fixtures, tmp_path)
    labels = read_csv(paths["labels"])
    assert {(l["equipment_id"].split("/")[1][:10], l["label"]) for l in labels} == {
        ("AHU_annual", "normal"), ("coi_stuck_", "fault")}
    with open(paths["history"]) as fh:
        head = next(csv.reader(fh))
    assert head == ["ts", "equipment_id", "role", "value"]
    results = [{"equipment_id": l["equipment_id"], "rule_id": "FC1", "window_start": "2018-07-03T12:00:00Z",
                "window_end": "2018-07-03T13:00:00Z", "status": "FAULT"} for l in labels]
    fc1 = score(results, labels)["rules"][0]
    assert (fc1["tp"], fc1["fp"]) == (1, 1)


def _write_bundle(root, *, labels=LABELS, history=True, point_name=False):
    import csv
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({"format": "open-fdd-scorecard-bundle", "version": 1}))
    for name, rows in (("rule_results.csv", RESULTS), ("labels.csv", labels)):
        with open(root / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
            w.writeheader()
            w.writerows(rows)
    if history:
        role = "AHU1.SA-T" if point_name else "discharge_air_temperature"
        with open(root / "history_long.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ts", "equipment_id", "role", "value"])
            for eq in ("AHU-F", "AHU-N"):
                for h in range(5):
                    w.writerow([f"2026-01-01T{h:02d}:30:00Z", eq, role, 13.0])
    (root / "role_map.json").write_text(json.dumps({"AHU-F": {"kind": "ahu", "roles": ["discharge_air_temperature"]}}))


def test_bundle_check_run_and_template(tmp_path, capsys):
    b = tmp_path / "bundle"
    _write_bundle(b)
    from open_fdd.scorecard import bundle
    rep = bundle.check(b)
    assert rep["ok"], rep
    assert rep["stats"]["faults"] == 5 and rep["stats"]["faults_without_history"] == 1  # AHU-X has no history
    assert main(["run", "--bundle", str(b)]) == 0
    assert "| FC1 | 2 | 1 | 1 | 1 |" in capsys.readouterr().out
    assert main(["template", str(b), "--out", str(tmp_path / "v.csv")]) == 0
    tpl = (tmp_path / "v.csv").read_text().splitlines()
    assert len(tpl) == 2 and tpl[1].startswith("AHU-X,") and ",FC8," in tpl[1]
    # a filled template row is a verdict; a blank one is ignored
    filled = LABELS + [{"equipment_id": "AHU-X", "start_ts": "2026-01-01T01:00:00Z", "end_ts": "2026-01-01T02:00:00Z",
                        "label": "confirmed", "rule_id": "FC8"},
                       {"equipment_id": "AHU-X", "start_ts": "2026-01-01T01:00:00Z", "end_ts": "2026-01-01T02:00:00Z",
                        "label": "", "rule_id": "FC1"}]
    fc8 = {r["rule_id"]: r for r in score(RESULTS, filled)["rules"]}["FC8"]
    assert (fc8["tp"], fc8["fp"]) == (1, 1)


def test_bundle_check_rejects_point_names(tmp_path):
    from open_fdd.scorecard import bundle
    _write_bundle(tmp_path / "b", point_name=True)
    rep = bundle.check(tmp_path / "b")
    assert not rep["ok"] and "point names" in rep["errors"][0]


def test_export_bundle_privacy_checksums_and_unalias(tmp_path, capsys):
    import csv

    from open_fdd.scorecard import bundle

    def write(name, rows):
        with open(tmp_path / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return tmp_path / name
    results = write("results.csv", [dict(r, site_id="SECRET-SITE") for r in RESULTS])
    hist = write("hist.csv", [{"ts": f"2026-01-0{d}T{h:02d}:00:00Z", "equipment_id": "AHU-F", "point": p, "value": 1}
                              for d in (1, 3) for h in range(24) for p in ("Bldg7.AHU-F.SAT", "Bldg7.AHU-F.Secret")])
    pmap = write("points.csv", [{"point": "Bldg7.AHU-F.SAT", "role": "discharge_air_temperature"}])
    bdir, priv = tmp_path / "bundle", tmp_path / "private"
    rc = main(["export", "--results", str(results), "--history", str(hist), "--point-map", str(pmap),
               "--out", str(bdir), "--private-dir", str(priv), "--shift-days", "364", "--window-hours", "2"])
    assert rc == 0
    blob = "".join(p.read_text() for p in bdir.iterdir())
    for secret in ("SECRET-SITE", "Bldg7", "AHU-F", "AHU-N", "2026-01-01"):
        assert secret not in blob
    hist_rows = list(csv.DictReader((bdir / "history_long.csv").read_text().splitlines()))
    # FAULT windows on AHU-F are 02:00-04:00 -> +/-2 h = 00:00-06:00 on Jan 1 only, one mapped point
    assert len(hist_rows) == 7 and {r["role"] for r in hist_rows} == {"discharge_air_temperature"}
    assert hist_rows[0]["ts"].startswith("2026-12-31T00:00")  # shifted 364 days
    rep = bundle.check(bdir)
    assert rep["ok"], rep
    # reviewer fills the verdict sheet; checksums still pass (verdicts.csv is not checksummed)
    rows = list(csv.DictReader((bdir / "verdicts.csv").read_text().splitlines()))
    assert len(rows) == 4  # AHU-F FC1 02:00-04:00 is one episode
    assert any(r["start_ts"].startswith("2026-12-31T02:00") and r["end_ts"].startswith("2026-12-31T04:00")
               for r in rows)
    for r in rows:
        r["label"] = "confirmed" if r["equipment_id"] == "EQ-0001" else "false_positive"
    with open(bdir / "verdicts.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    capsys.readouterr()
    assert main(["run", "--bundle", str(bdir)]) == 0
    assert "| FC1 | 2 | 1 | 0 | 0 |" in capsys.readouterr().out
    assert main(["unalias", "--verdicts", str(bdir / "verdicts.csv"), "--private-dir", str(priv),
                 "--out", str(tmp_path / "real.csv")]) == 0
    real = list(csv.DictReader((tmp_path / "real.csv").read_text().splitlines()))
    assert real[0]["equipment_id"] == "AHU-F" and real[0]["start_ts"].startswith("2026-01-01T02:00")
    # tampering is detected
    (bdir / "rule_results.csv").write_text((bdir / "rule_results.csv").read_text() + "x,y,z\n")
    assert not bundle.check(bdir)["ok"]
    assert main(["run", "--bundle", str(bdir)]) == 1


def test_prevalence_reweights_precision_and_feeds_prior():
    card = score(RESULTS, LABELS, prevalence=0.1)
    fc1 = _by_rule(card)["FC1"]
    r, f = 2.5 / 4, 1.5 / 3  # Jeffreys-smoothed recall (2 of 3) and FPR (1 of 2)
    assert fc1["precision_at_prevalence"] == pytest.approx((r * 0.1) / (r * 0.1 + f * 0.9))
    assert fc1["p_true_fault"] == pytest.approx(fc1["precision_at_prevalence"])
    site = _by_rule(score(RESULTS, LABELS, prior=card, prior_weight=10))["FC1"]
    assert site["prior_precision"] == pytest.approx(fc1["precision_at_prevalence"])
    with pytest.raises(ValueError):
        score(RESULTS, LABELS, prevalence=1.5)


def _write_csv(path, rows):
    import csv
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def test_export_drops_owner_free_text_and_invalid_history_values(tmp_path):
    import csv
    from open_fdd.scorecard import export
    secret = "PRIVATE-OWNER-NOTE"
    results = _write_csv(tmp_path / "r.csv", [
        _res("AHU-F", "FC1", "2026-01-01T02:00:00Z", "FAULT"),
        _res("AHU-F", "FC1", "2026-01-01T03:00:00Z", secret)])
    labels = _write_csv(tmp_path / "l.csv", [{
        "equipment_id": "AHU-F", "start_ts": "2026-01-01T02:00:00Z", "end_ts": "2026-01-01T04:00:00Z",
        "label": "confirmed", "rule_id": "FC1", "source": secret, "fault_type": secret,
        "reviewer": secret, "notes": secret}])
    history = _write_csv(tmp_path / "h.csv", [
        {"ts": "2026-01-01T02:30:00Z", "equipment_id": "AHU-F", "point": "p", "value": v}
        for v in (21.0, secret, "nan", "inf")])
    pmap = _write_csv(tmp_path / "p.csv", [{"point": "p", "role": "supply-air-temp"}])
    out = tmp_path / "bundle"
    stats = export.build(results=results, labels=labels, history=history, point_map=pmap,
                         out=out, private_dir=tmp_path / "private", shift_days=28)
    assert stats["dropped_invalid_value_rows"] == 3 and stats["history_rows"] == 1
    assert secret not in "".join(p.read_text() for p in out.iterdir())
    assert {r["status"] for r in csv.DictReader((out / "rule_results.csv").open())} == {"FAULT", "NA"}
    exported_label = next(csv.DictReader((out / "labels.csv").open()))
    assert exported_label["label"] == "fault"
    assert all(exported_label[k] == "" for k in ("source", "fault_type", "reviewer", "notes"))


@pytest.mark.parametrize("field", ["label", "rule_id"])
def test_export_rejects_unmapped_labels_and_free_text_rule_ids(tmp_path, field):
    from open_fdd.scorecard import export
    results = _write_csv(tmp_path / "r.csv", [_res("E", "FC1", "2026-01-01T02:00:00Z", "FAULT")])
    row = {"equipment_id": "E", "start_ts": "2026-01-01T02:00:00Z", "end_ts": "2026-01-01T04:00:00Z",
           "label": "fault", "rule_id": "FC1"}
    row[field] = "private owner note"
    labels = _write_csv(tmp_path / "l.csv", [row])
    with pytest.raises(ValueError, match="not mapped|rule_id"):
        export.build(results=results, labels=labels, out=tmp_path / "bundle", private_dir=tmp_path / "private")


def test_export_keys_equipment_by_site_and_normalizes_snake_roles(tmp_path):
    """Same equipment id at two sites -> two aliases; snake_case roles accepted; site ids never leave."""
    import csv
    results = _write_csv(tmp_path / "r.csv", [
        dict(_res("AHU_1", "FC1", "2026-01-01T02:00:00Z", "FAULT"), site_id="SITE-A"),
        dict(_res("AHU_1", "FC1", "2026-01-01T02:00:00Z", "PASS"), site_id="SITE-B"),
    ])
    hist = _write_csv(tmp_path / "h.csv", [
        {"ts": f"2026-01-01T0{h}:00:00Z", "site_id": s, "equipment_id": "AHU_1", "point": "ZN-T", "value": v}
        for h in range(1, 5) for s, v in (("SITE-A", 21.0), ("SITE-B", 30.0))])
    pmap = _write_csv(tmp_path / "p.csv", [
        {"site_id": s, "point": "ZN-T", "role": "zone_air_temp", "equipment_id": "AHU_1"} for s in ("SITE-A", "SITE-B")])
    bdir, priv = tmp_path / "b", tmp_path / "k"
    from open_fdd.scorecard import bundle, export
    stats = export.build(results=results, history=hist, point_map=pmap, out=bdir, private_dir=priv)
    assert stats["equipment"] == 2 and stats["renamed_roles"] == ["zone_air_temp"]
    hist_rows = list(csv.DictReader((bdir / "history_long.csv").read_text().splitlines()))
    # only SITE-A faulted: its history (21.0) is exported, SITE-B's (30.0) is not
    assert {r["value"] for r in hist_rows} == {"21.0"} and {r["role"] for r in hist_rows} == {"zone-air-temp"}
    blob = "".join(p.read_text() for p in bdir.iterdir())
    assert "SITE-A" not in blob and "SITE-B" not in blob and "AHU_1" not in blob and "\x1f" not in blob
    assert bundle.check(bdir)["ok"]
    rows = list(csv.DictReader((bdir / "verdicts.csv").read_text().splitlines()))
    rows[0]["label"] = "fault"
    _write_csv(bdir / "verdicts.csv", rows)
    assert main(["unalias", "--verdicts", str(bdir / "verdicts.csv"), "--private-dir", str(priv),
                 "--out", str(tmp_path / "real.csv")]) == 0
    real = list(csv.DictReader((tmp_path / "real.csv").read_text().splitlines()))
    assert real[0]["site_id"] == "SITE-A" and real[0]["equipment_id"] == "AHU_1"


def test_export_validates_inputs_before_writing(tmp_path):
    results = _write_csv(tmp_path / "r.csv", [_res("AHU-1", "FC1", "2026-01-01T02:00:00Z", "FAULT")])
    hist = _write_csv(tmp_path / "h.csv", [{"ts": "2026-01-01T02:00:00Z", "equipment_id": "AHU-1",
                                            "point": "P", "value": 1}])
    pmap = _write_csv(tmp_path / "p.csv", [{"point": "P", "role": "Bldg7.SAT"}])
    from open_fdd.scorecard import export
    with pytest.raises(ValueError, match="point_map line 2"):
        export.build(results=results, history=hist, point_map=pmap, out=tmp_path / "b", private_dir=tmp_path / "k")
    assert not (tmp_path / "b" / "rule_results.csv").exists()
    (tmp_path / "bad.csv").write_text(results.read_text() + "a stray log line\n")
    with pytest.raises(ValueError, match="results .* line 3"):
        export.build(results=tmp_path / "bad.csv", out=tmp_path / "b2", private_dir=tmp_path / "k2")


def test_export_shifts_manifest_time(tmp_path):
    import json as _json
    from datetime import datetime, timezone
    results = _write_csv(tmp_path / "r.csv", [_res("AHU-1", "FC1", "2026-01-01T02:00:00Z", "FAULT")])
    from open_fdd.scorecard import export
    export.build(results=results, out=tmp_path / "b", private_dir=tmp_path / "k", shift_days=364)
    created = _json.loads((tmp_path / "b" / "manifest.json").read_text())["created_utc"]
    assert (datetime.fromisoformat(created.replace("Z", "+00:00")) - datetime.now(timezone.utc)).days >= 363
