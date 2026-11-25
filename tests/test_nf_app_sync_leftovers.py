"""#1772: push removes the app files an earlier push wrote and the current manifest dropped; doctor lists extra files
and reads a 401 on / as "behind login".

Fake NF (in memory) and the mock NF only; nothing here talks to a real box.
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from test_nf_app_install import Clock, doctor_nf, fake, install_args, make_manifest, sync

APP = "new-app"
OLD = "/static/old-theme.js"


def box_with_leftover(tmp_path):
    """A box after a push that shipped OLD, and the next manifest that no longer ships it: (manifest, fake NF, clock)."""
    m, nf, clk = make_manifest(tmp_path), fake(), Clock()
    (tmp_path / "old-theme.js").write_text("// old theme\n")
    m["files"][OLD] = "old-theme.js"
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    del m["files"][OLD]
    return m, nf, clk


def push_manifest(nf) -> dict:
    return json.loads(nf.files[(APP, "/static/version.json")])["files"]


def deletes(nf, n: int = 0) -> list[str]:
    return [p for meth, p in nf.log[n:] if meth == "DELETE"]


def test_push_removes_a_file_the_last_push_wrote_and_the_manifest_dropped(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    out = capsys.readouterr().out
    assert ("push: removing 1 file(s) an earlier push wrote that this manifest no longer ships:\n"
            f"  {OLD}\n") in out and f"removed {OLD}" in out
    assert deletes(nf) == [f"/api/v1/apps/{APP}/files{OLD}"]
    assert (APP, OLD) not in nf.files
    assert set(push_manifest(nf)) == {"/package.json", "/hooks/x.js"}
    n = len(nf.log)
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert deletes(nf, n) == [], "nothing left to remove"


def test_push_never_touches_files_it_did_not_write_or_that_nf_owns(tmp_path):
    m, nf, clk = box_with_leftover(tmp_path)
    for p in ("/app.json", "/hooks-update/fdd.js", "/static/made-by-hand.js", "/node_modules/pg/package.json"):
        nf.files[(APP, p)] = b"keep me"
    info = json.loads(nf.files[(APP, "/static/version.json")])
    # a push manifest that (somehow) names NF-owned or odd paths: still never deleted
    for p in ("/app.json", "/hooks-update/fdd.js", "/../../etc/passwd", "/static/a?b", "relative.js"):
        info["files"][p] = sync.sha256_hex(b"keep me")
    nf.files[(APP, "/static/version.json")] = json.dumps(info).encode()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert deletes(nf) == [f"/api/v1/apps/{APP}/files{OLD}"]
    for p in ("/app.json", "/hooks-update/fdd.js", "/static/made-by-hand.js", "/node_modules/pg/package.json"):
        assert nf.files[(APP, p)] == b"keep me"


@pytest.mark.parametrize(("path", "ok"), [
    ("/static/old.js", True), ("/hooks/lib/x.js", True), ("/app.json", False), ("/static/version.json", False),
    ("/hooks-update/x.js", False), ("/node_modules/pg/index.js", False), ("/", False), ("", False),
    ("static/x.js", False), ("/static/../app.json", False), ("/static//x.js", False), ("/static/./x.js", False),
    ("/static/x.js?y", False), ("/static/x%2e.js", False), ("/static\\x.js", False), (None, False)])
def test_removable_path(path, ok):
    assert sync.removable_path(path) is ok


def test_no_push_manifest_means_nothing_is_removed(tmp_path):
    m, nf, clk = box_with_leftover(tmp_path)
    info = json.loads(nf.files[(APP, "/static/version.json")])
    del info["files"]                               # an install by an older release
    nf.files[(APP, "/static/version.json")] = json.dumps(info).encode()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True) == 0
    assert deletes(nf) == [] and (APP, OLD) in nf.files


def test_an_edited_leftover_is_kept_unless_force_and_save_remote_keeps_a_copy(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    nf.files[(APP, OLD)] = b"// edited on the box\n"
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    out = capsys.readouterr().out
    assert "push: keeping 1 file(s) this manifest no longer ships because they were edited on the box" in out
    assert deletes(nf) == [] and nf.files[(APP, OLD)] == b"// edited on the box\n"
    assert OLD in push_manifest(nf), "kept leftovers stay in the push manifest"
    keep = tmp_path / "copies"
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True, save_remote=keep) == 0
    assert (keep / "static" / "old-theme.js").read_bytes() == b"// edited on the box\n"
    assert (APP, OLD) not in nf.files and OLD not in push_manifest(nf)


def test_keep_files_lists_and_leaves_them_then_a_plain_push_removes_them(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, keep_files=True) == 0
    assert "push: --keep-files: leaving 1 file(s)" in capsys.readouterr().out
    assert deletes(nf) == [] and OLD in push_manifest(nf)
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert (APP, OLD) not in nf.files
    assert sync.build_parser().parse_args(["push", "x.json", "--keep-files"]).keep_files


def test_a_leftover_a_hook_still_points_at_is_kept(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    nf.store[APP]["hooks"].append({"id": "retired", "entryPoint": OLD})       # a hook this manifest no longer ships
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert f"push: keeping {OLD}: hook retired still points at it" in capsys.readouterr().out
    assert deletes(nf) == [] and OLD in push_manifest(nf)


@pytest.mark.parametrize(("skip_hooks", "removed"), [(False, True), (True, False)])
def test_a_hook_this_push_repoints_no_longer_protects_the_old_file(tmp_path, skip_hooks, removed):
    m, nf, clk = box_with_leftover(tmp_path)
    nf.store[APP]["hooks"] = [{"id": "fdd", "entryPoint": OLD}]   # the box's fdd still runs OLD; the manifest's runs x.js
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, skip_hooks=skip_hooks) == 0
    assert ((APP, OLD) not in nf.files) is removed


def test_without_a_file_listing_nothing_is_removed_and_the_record_is_kept(tmp_path, capsys, monkeypatch):
    m, nf, clk = box_with_leftover(tmp_path)
    monkeypatch.setattr(sync, "remote_file_paths", lambda *_: None)
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert "push: NF did not list the app's files" in capsys.readouterr().out
    assert deletes(nf) == [] and OLD in push_manifest(nf)


def test_a_failed_delete_is_reported_and_kept_for_the_next_push(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    real = nf.call

    def call(method, path, body=None, ok_404=False):
        if method == "DELETE":
            nf.log.append((method, path))
            raise sync.ApiError(f"DELETE {path} -> HTTP 500", 500, "http")
        return real(method, path, body, ok_404)

    nf.call = call
    capsys.readouterr()
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep) == 0
    assert f"push: could not remove {OLD}" in capsys.readouterr().out
    assert (APP, OLD) in nf.files and OLD in push_manifest(nf)


def test_install_dry_run_lists_leftovers_and_writes_nothing(tmp_path, capsys):
    m, nf, clk = box_with_leftover(tmp_path)
    capsys.readouterr()
    n = len(nf.log)
    assert sync.cmd_install(nf, m, install_args("--dry-run"), clk, clk.sleep) == 0
    out = capsys.readouterr().out
    assert ("install: dry run: would remove 1 file(s) an earlier push wrote that this manifest no longer ships:\n"
            f"  {OLD}\n") in out
    assert [x for x in nf.log[n:] if x[0] != "GET"] == [] and (APP, OLD) in nf.files


def test_install_rollback_puts_a_removed_leftover_back(tmp_path, monkeypatch):
    m, nf, clk = box_with_leftover(tmp_path)
    before = nf.files[(APP, OLD)]
    nf.store[APP]["configuration"] = {"version": {"string": "9.9.9"}}     # the fake stores what a real box returns
    monkeypatch.setattr(sync, "verify_install", lambda *_a, **_k: sync.EXIT_FAILED)
    assert sync.cmd_install(nf, m, install_args("--skip-deps"), clk, clk.sleep) == sync.EXIT_FAILED
    assert f"/api/v1/apps/{APP}/files{OLD}" in deletes(nf), "the push removed it"
    assert nf.files[(APP, OLD)] == before, "the rollback restored it"
    assert OLD in push_manifest(nf), "and the restored version.json still records it"


# ---------------------------------------------------------------- doctor

def test_doctor_lists_extra_files_by_origin_read_only(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path, redirect=(302, {"Location": "https://h/api/v1/apps/static/new-app/"}))
    clk = Clock()
    (tmp_path / "old-theme.js").write_text("// old theme\n")
    m["files"][OLD] = "old-theme.js"
    assert sync.cmd_push(nf, m, clock=clk, sleep=clk.sleep, force=True) == 0
    capsys.readouterr()
    sync.cmd_doctor(nf, m)
    assert "[PASS] extra files: none" in capsys.readouterr().out
    del m["files"][OLD]
    for p in ("/static/by-hand.js", "/app.json", "/hooks-update/fdd.js"):
        nf.files[(APP, p)] = b"x"
    n = len(nf.log)
    sync.cmd_doctor(nf, m)
    out = capsys.readouterr().out
    assert (f"[WARN] extra files: 2 file(s) on the box not in the manifest: /static/by-hand.js, {OLD}. "
            "1 written by an earlier push: the next push removes them; "
            "1 not written by this tool: push leaves them") in out
    assert "/app.json" not in out.split("extra files")[1].split("\n")[0]
    assert [x for x in nf.log[n:] if x[0] in ("POST", "PATCH", "DELETE") and x[1] != "/api/v1/point/query"
            and "/hooks/" not in x[1]] == []


def test_doctor_extra_files_without_a_listing_is_skipped(tmp_path, capsys, monkeypatch):
    m, nf = doctor_nf(tmp_path)
    monkeypatch.setattr(sync, "remote_file_paths", lambda *_: None)
    sync.cmd_doctor(nf, m)
    assert "[SKIP] extra files: NF did not list the app's files" in capsys.readouterr().out


@pytest.mark.parametrize("code", [401, 403])
def test_doctor_reads_a_login_on_slash_as_behind_login(tmp_path, capsys, code):
    m, nf = doctor_nf(tmp_path, redirect=(code, {}))
    sync.cmd_doctor(nf, m)
    out = capsys.readouterr().out
    assert f"[PASS] / redirect: behind login (HTTP {code}); redirect not checked" in out
    assert "no redirect" not in out


# ---------------------------------------------------------------- mock NF

@pytest.mark.skipif(not shutil.which("node"), reason="mock NF requires Node")
def test_mock_nf_push_removes_the_dropped_file(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([shutil.which("node"), str(root / "nf-app" / "dev" / "mock-nf.mjs"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with sync.urllib.request.urlopen(base + "/api/v1/apps", timeout=0.2):
                    break
            except Exception:
                if proc.poll() is not None:
                    raise AssertionError("mock NF exited before becoming ready")
                time.sleep(0.05)
        state = {"files": ["/app.json", "/static/by-hand.js"],
                 "contents": {"/app.json": base64.b64encode(b"{}").decode(),
                              "/static/by-hand.js": base64.b64encode(b"x").decode()}}
        req = sync.urllib.request.Request(base + "/api/v1/_mock/install/state", data=json.dumps(state).encode(),
                                          headers={"Content-Type": "application/json"}, method="POST")
        sync.urllib.request.urlopen(req, timeout=2).read()
        c = sync.Console(base, "mock", "mock")
        (tmp_path / "VERSION").write_text("9.9.9\n")
        (tmp_path / "a.js").write_text("// a\n")
        (tmp_path / "old.js").write_text("// old\n")
        m = {"application": {"id": "open-fdd"}, "_dir": tmp_path, "hooks": [],
             "files": {"/static/a.js": "a.js", "/static/old.js": "old.js"}}
        monkeypatch.setattr(sync, "version_info", lambda *_: {"version": "9.9.9", "commit": "", "dirty": False})
        clk = Clock()
        assert sync.cmd_push(c, m, skip_deps=True, clock=clk, sleep=clk.sleep) == 0
        del m["files"]["/static/old.js"]
        assert sync.cmd_push(c, m, skip_deps=True, clock=clk, sleep=clk.sleep) == 0
        listed = sync.remote_file_paths(c, "open-fdd")
        assert "/static/old.js" not in listed
        assert {"/app.json", "/static/by-hand.js", "/static/a.js", "/static/version.json"} <= listed
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
