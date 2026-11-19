"""doctor host health (#1615): memory, disk and restarts from GET /api/v1/platform/info only. Report-only."""

from __future__ import annotations

import base64
import json

from test_nf_app_install import doctor_nf, sync

GIB = 1024 ** 3


def b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


class Info:
    """Console stub answering only GET /api/v1/platform/info."""

    def __init__(self, info):
        self.info, self.log = info, []

    def call(self, method, path, body=None, ok_404=False):
        self.log.append((method, path))
        assert (method, path) == ("GET", "/api/v1/platform/info")
        if isinstance(self.info, BaseException):
            raise self.info
        return self.info


def lines(info):
    return {what: (lvl, text) for lvl, what, text in sync.host_health(Info(info))}


NF_3109 = {"siteName": "s", "version": "3.10.9-1", "domain": "", "services": [],
           "machineInfo": b64({"baseboard": {"serial_number": "SN-SECRET"}, "cpus": [],
                               "block": [{"bytes": 31914983424, "serial": "DISK-SECRET"}, {"bytes": 4194304}],
                               "net": [{"mac": "aa:bb:cc:dd:ee:ff", "name": "eth0"}]})}


def test_nf_3109_exposes_static_inventory_only_so_everything_skips():
    got = lines(NF_3109)
    assert got["host memory"] == ("SKIP", "NF 3.10.9-1 does not expose free memory through its API")
    assert got["host disk"][0] == "SKIP" and "largest disk 29.7 GiB (size only)" in got["host disk"][1]
    assert got["host services"][0] == "SKIP" and "no service list" in got["host services"][1]


def test_identifiers_in_machine_info_are_never_printed():
    text = " ".join(t for _, t in lines(NF_3109).values())
    for secret in ("SN-SECRET", "DISK-SECRET", "aa:bb:cc:dd:ee:ff", "eth0"):
        assert secret not in text


def test_free_memory_and_disk_pass_when_plenty():
    info = {"version": "9.9", "memAvailableBytes": 3 * GIB, "memTotalBytes": 8 * GIB,
            "diskFreeBytes": "200000000000", "diskTotalBytes": 250000000000}
    got = lines(info)
    assert got["host memory"] == ("PASS", "3.0 GiB available (38 % of 8.0 GiB)")
    assert got["host disk"][0] == "PASS" and "80 %" in got["host disk"][1]


def test_low_memory_and_low_disk_warn():
    info = {"memory": {"available_bytes": 100 * 1024 ** 2, "total_bytes": 4 * GIB},
            "disk": {"fs_available_bytes": 0.5 * GIB, "fs_size_bytes": 64 * GIB}}
    info["memory"]["memAvailable"] = info["memory"].pop("available_bytes")
    info["memory"]["memTotal"] = info["memory"].pop("total_bytes")
    got = lines(info)
    assert got["host memory"][0] == "WARN" and "low memory" in got["host memory"][1]
    assert got["host disk"][0] == "WARN" and "low disk" in got["host disk"][1]


def test_fraction_threshold_warns_even_above_the_absolute_floor():
    got = lines({"memAvailableBytes": 1 * GIB, "memTotalBytes": 16 * GIB})
    assert got["host memory"][0] == "WARN"


def test_total_ram_from_machine_info_is_shown_on_a_skip():
    got = lines({"version": "3.10.9-1", "machineInfo": b64({"memory": {"total_physical_bytes": 4 * GIB}})})
    assert got["host memory"] == ("SKIP", "NF 3.10.9-1 does not expose free memory through its API; total RAM 4.0 GiB")


def test_service_restarts_and_stopped_services_warn():
    info = {"uptimeSeconds": 7200, "services": [
        {"name": "hpl", "status": "RUNNING", "restartCount": 0},
        {"name": "hooks", "status": "RUNNING", "restartCount": "3"},
        {"name": "bacnet", "state": "STOPPED"}]}
    lvl, text = lines(info)["host services"]
    assert lvl == "WARN" and "restarted: hooks x3" in text and "not running: bacnet (stopped)" in text
    assert "uptime 2.0 h" in text


def test_healthy_services_pass():
    lvl, text = lines({"services": [{"name": "hpl", "status": "SERVING"}, {"name": "hooks", "health": "ok"}]})["host services"]
    assert lvl == "PASS" and "2 services" in text


def test_unreadable_platform_info_skips_cleanly():
    got = sync.host_health(Info(sync.ApiError("GET /api/v1/platform/info -> HTTP 404", 404, "http")))
    assert got == [("SKIP", "host", "NF platform info not readable through the console API "
                                    "(GET /api/v1/platform/info -> HTTP 404); memory, disk and restarts not checked")]


def test_machine_info_decoding_is_lenient():
    assert sync.decode_machine_info("not base64 !!") == {}
    assert sync.decode_machine_info(None) == {}
    assert sync.decode_machine_info({"a": 1}) == {"a": 1}
    assert sync.decode_machine_info('{"a": 1}') == {"a": 1}
    assert sync.decode_machine_info(b64({"a": 2})) == {"a": 2}


def test_doctor_prints_host_lines_and_a_warn_or_skip_never_fails_it(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path)
    nf.platform_info = NF_3109
    rc_skip = sync.cmd_doctor(nf, m)
    assert "[SKIP] host memory:" in capsys.readouterr().out
    nf.platform_info = {"version": "x", "memAvailableBytes": 1, "memTotalBytes": 4 * GIB,
                        "services": [{"name": "hooks", "status": "RUNNING", "restartCount": 5}]}
    assert sync.cmd_doctor(nf, m) == rc_skip           # host lines never change the exit status
    out = capsys.readouterr().out
    assert "[WARN] host memory:" in out and "[SKIP] host disk:" in out and "[WARN] host services:" in out
    nf.platform_info = sync.ApiError("GET /api/v1/platform/info -> HTTP 500", 500, "http")
    assert sync.cmd_doctor(nf, m) == rc_skip
    assert "[SKIP] host: NF platform info not readable" in capsys.readouterr().out


def test_doctor_host_check_is_one_read_only_get(tmp_path):
    m, nf = doctor_nf(tmp_path)
    sync.cmd_doctor(nf, m)
    assert [c for c in nf.log if c[1].startswith("/api/v1/platform")] == [("GET", "/api/v1/platform/info")]
    assert all(c[0] == "GET" or c[1] == "/api/v1/point/query" for c in nf.log), nf.log


def test_host_lines_come_before_the_app_check_so_they_show_when_the_app_is_missing(tmp_path, capsys):
    m, nf = doctor_nf(tmp_path)
    nf.store.clear()
    assert sync.cmd_doctor(nf, m) == 1
    out = capsys.readouterr().out
    assert out.index("host memory") < out.index("is not installed")
