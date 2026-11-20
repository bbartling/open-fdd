"""nf_app_sync.py prune-points (#1614): dry run by default, strictly this manifest's app ids, exact uuid deletes."""

from __future__ import annotations

import datetime
import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nf_app_sync_prune", Path(__file__).resolve().parents[1] / "scripts" / "nf" / "hooks" / "nf_app_sync.py"
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

NOW = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.timezone.utc)
OLD = "2026-09-01T00:00:00Z"      # 79 days before NOW
RECENT = "2026-11-18T00:00:00Z"   # 1.5 days before NOW
MANIFEST = {"application": {"id": "open-fdd"}, "replaces": ["open-fdd-edge", "old-weather"], "hooks": []}


def auto(uuid, app, typ="fdd-result", name=None):
    return {"uuid": uuid, "name": name or f"pt-{uuid}", "layer": "automation",
            "attrs": {"application_id": app, "type": typ}}


def model(uuid, status="stale", latest=None, through=None, reason="rule was not run for this equip (catalog)"):
    rec = {"uuid": uuid, "name": f"pt-{uuid}", "layer": "model",
           "attrs": {"fddStatus": status, "fddReason": reason, "ruleRef": "R-1", "fddLastRun": RECENT}}
    if latest:
        rec["latestValue"] = {"ts": latest, "real": 0}
    if through:
        rec["attrs"]["fddTimelineThrough"] = through
    return rec


class MockNF:
    """In-memory NF console: apps, automation + model layers, DeletePoints by ?uuids=. `log` = (method, path)."""

    def __init__(self, apps, automation, models, delete_status=None, short_count=False):
        self.apps_ = [{"id": a, "status": "STATUS_INSTALLED", "hooks": []} for a in apps]
        self.automation = automation
        self.models = models
        self.log: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.delete_status = delete_status
        self.short_count = short_count

    def apps(self):
        self.log.append(("GET", "/api/v1/apps"))
        return [dict(a) for a in self.apps_]

    def call(self, method, path, body=None, ok_404=False):
        self.log.append((method, path))
        base, _, query = path.partition("?")
        if base == "/api/v1/point/query" and method == "POST":
            rows = self.automation if body.get("layer") == "automation" else (
                self.models if body.get("layer") == "model" else [])
            off = int(body.get("pageOffset") or 0)
            size = int(body.get("pageSize") or 500)
            return {"points": rows[off:off + size], "totalCount": str(len(rows))}
        if base == "/api/v1/point/points" and method == "DELETE":
            if self.delete_status:
                raise sync.ApiError(f"DELETE /api/v1/point/points -> HTTP {self.delete_status}", self.delete_status, "http")
            assert body is None
            uuids = urllib.parse.parse_qs(query)["uuids"]
            self.deleted += uuids
            n = len(uuids) - (1 if self.short_count else 0)
            return {"deleteCount": str(n)}
        raise AssertionError(f"unexpected call {method} {path}")

    def writes(self):
        return [x for x in self.log if x[0] in ("POST", "PATCH", "DELETE", "PUT") and x[1] != "/api/v1/point/query"]


def site():
    """A long-lived box: one installed Open-FDD app, a removed predecessor, an unrelated app and field points."""
    automation = [
        auto("orph-1", "open-fdd-edge", "weather"),           # removed predecessor: orphan
        auto("orph-2", "old-weather", "weather"),             # removed predecessor: orphan
        auto("other-1", "someone-elses-app", "weather"),      # not ours, app gone: never touched
        auto("other-2", "bench-viz", "weather"),              # not in this manifest's replaces: never touched
        auto("stale-old", "open-fdd"),                        # ours, stale, old value: candidate
        auto("stale-never", "open-fdd", "fdd-fault-timeline"),  # ours, stale, never a value: candidate
        auto("stale-recent", "open-fdd"),                     # ours, stale but recent: kept
        auto("ok-1", "open-fdd"),                             # ours, current: kept
        auto("weather-own", "open-fdd", "weather"),           # ours but not a result type: kept
        {"uuid": "field-1", "name": "AHU-1 SAT", "layer": "automation", "attrs": {}},  # no application_id
        auto("inst-1", "installed-other", "fdd-result"),      # other installed app: never touched
    ]
    models = [
        model("stale-old", latest=OLD),
        model("stale-never"),
        model("stale-recent", latest=RECENT),
        model("ok-1", status="ok", latest=OLD),
        model("weather-own", latest=OLD),
        model("inst-1", latest=OLD),
    ]
    return MockNF(["open-fdd", "installed-other"], automation, models)


def test_dry_run_lists_both_groups_and_writes_nothing(capsys):
    nf = site()
    assert sync.cmd_prune_points(nf, MANIFEST, yes=False, now=NOW) == 0
    out = capsys.readouterr().out
    assert nf.writes() == []
    assert "orphan points (app not installed): 2" in out and "orph-1" in out and "orph-2" in out
    assert "stale FDD result / timeline points (older than 30 days): 2" in out
    assert "stale-old" in out and "stale-never" in out and "never had a value" in out
    for kept in ("other-1", "other-2", "stale-recent", "ok-1", "weather-own", "field-1", "inst-1"):
        assert kept not in out
    assert "dry run: nothing was changed; add --yes" in out
    assert "delete_points" in out


def test_yes_deletes_exactly_the_listed_uuids(capsys):
    nf = site()
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == 0
    assert sorted(nf.deleted) == ["orph-1", "orph-2", "stale-never", "stale-old"]
    assert [m for m, _ in nf.writes()] == ["DELETE"]
    assert "deleted 4 of 4 points" in capsys.readouterr().out


def test_candidates_are_strictly_this_manifests_ids():
    nf = site()
    orphans, stale = sync.prune_candidates(MANIFEST, nf.automation, nf.models, {"open-fdd", "installed-other"}, NOW, 30)
    assert {p["application_id"] for p in orphans + stale} <= sync.own_app_ids(MANIFEST)
    assert sync.own_app_ids(MANIFEST) == {"open-fdd", "open-fdd-edge", "old-weather"}


def test_an_installed_predecessor_is_not_an_orphan():
    nf = site()
    orphans, _ = sync.prune_candidates(MANIFEST, nf.automation, nf.models,
                                       {"open-fdd", "open-fdd-edge"}, NOW, 30)
    assert [p["uuid"] for p in orphans] == ["orph-2"]


def test_stale_days_moves_the_cutoff():
    nf = site()
    _, stale = sync.prune_candidates(MANIFEST, nf.automation, nf.models, {"open-fdd"}, NOW, 1)
    assert sorted(p["uuid"] for p in stale) == ["stale-never", "stale-old", "stale-recent"]
    _, stale = sync.prune_candidates(MANIFEST, nf.automation, nf.models, {"open-fdd"}, NOW, 365)
    assert [p["uuid"] for p in stale] == ["stale-never"]


def test_timeline_through_counts_as_the_newest_value():
    automation = [auto("tl", "open-fdd", "fdd-fault-timeline")]
    _, stale = sync.prune_candidates(MANIFEST, automation, [model("tl", through=RECENT)], {"open-fdd"}, NOW, 30)
    assert stale == []


def test_own_app_not_installed_makes_its_points_orphans():
    automation = [auto("a", "open-fdd"), auto("b", "open-fdd", "weather")]
    orphans, stale = sync.prune_candidates(MANIFEST, automation, [], set(), NOW, 30)
    assert sorted(p["uuid"] for p in orphans) == ["a", "b"] and stale == []


@pytest.mark.parametrize("yes", [False, True])
@pytest.mark.parametrize("apps", [[], ["unrelated-app"]])
def test_empty_or_incomplete_apps_list_cannot_authorize_pruning(apps, yes):
    nf = MockNF(apps, [auto("live", "open-fdd")], [])
    assert sync.cmd_prune_points(nf, MANIFEST, yes=yes, now=NOW) == sync.EXIT_FAILED
    assert nf.writes() == [] and nf.deleted == []


def test_empty_list_cannot_be_overridden():
    nf = MockNF([], [auto("live", "open-fdd")], [])
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW, self_uninstalled=True) == sync.EXIT_FAILED
    assert nf.writes() == []


@pytest.mark.parametrize("yes", [False, True])
def test_explicit_self_uninstalled_keeps_dry_run_default_and_exact_scope(yes):
    nf = MockNF(["unrelated-app"], [auto("removed", "open-fdd"), auto("other", "another-app")], [])
    assert sync.cmd_prune_points(nf, MANIFEST, yes=yes, now=NOW, self_uninstalled=True) == 0
    assert nf.deleted == (["removed"] if yes else [])


def test_nothing_to_delete_is_a_clean_exit(capsys):
    nf = MockNF(["open-fdd"], [auto("ok-1", "open-fdd")], [model("ok-1", status="ok", latest=RECENT)])
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == 0
    assert nf.writes() == [] and "nothing to delete" in capsys.readouterr().out


def test_over_max_delete_changes_nothing_even_with_yes(capsys):
    nf = site()
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, max_delete=3, now=NOW) == sync.EXIT_FAILED
    assert nf.writes() == [] and "more than --max-delete 3" in capsys.readouterr().out


def test_deletes_go_in_batches():
    automation = [auto(f"o{i:03d}", "old-weather", "weather") for i in range(120)]
    nf = MockNF(["open-fdd"], automation, [])
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == 0
    deletes = [p for m, p in nf.writes() if m == "DELETE"]
    assert len(deletes) == 3 and len(nf.deleted) == 120 and len(set(nf.deleted)) == 120


def test_a_refused_delete_is_reported_with_the_mcp_route(capsys):
    nf = site()
    nf.delete_status = 405
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == sync.EXIT_FAILED
    out = capsys.readouterr().out
    assert "delete FAILED" in out and "HTTP 405" in out and "delete_points" in out


def test_a_short_delete_count_is_a_failure(capsys):
    nf = site()
    nf.short_count = True
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == sync.EXIT_FAILED
    assert "NF reported a different count" in capsys.readouterr().out


def test_a_read_failure_changes_nothing(capsys):
    nf = site()
    real = nf.call

    def broken(method, path, body=None, ok_404=False):
        if path == "/api/v1/point/query" and body.get("layer") == "model":
            raise sync.ApiError("POST /api/v1/point/query -> HTTP 503", 503, "http")
        return real(method, path, body, ok_404)

    nf.call = broken
    assert sync.cmd_prune_points(nf, MANIFEST, yes=True, now=NOW) == sync.EXIT_FAILED
    assert nf.writes() == [] and "nothing was changed" in capsys.readouterr().out


def test_stale_days_below_one_is_refused():
    with pytest.raises(SystemExit):
        sync.cmd_prune_points(site(), MANIFEST, yes=False, stale_days=0, now=NOW)


def test_cli_wires_prune_points_with_dry_run_default():
    a = sync.build_parser().parse_args(["prune-points", "nf-app/app.json"])
    assert a.action == "prune-points" and a.yes is False and a.stale_days == 30 and a.max_delete == 500
    a = sync.build_parser().parse_args(["prune-points", "m.json", "--yes", "--stale-days", "7", "--max-delete", "10"])
    assert a.yes and a.stale_days == 7 and a.max_delete == 10


def test_real_manifests_scope_only_open_fdd_ids():
    root = Path(__file__).resolve().parents[1]
    for rel in ("nf-app/app.json", "lite/app.json"):
        m = json.loads((root / rel).read_text())
        ids = sync.own_app_ids(m)
        assert m["application"]["id"] in ids
        assert ids == {m["application"]["id"], *m.get("replaces", [])}
