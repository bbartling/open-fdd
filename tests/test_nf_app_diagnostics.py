"""nf_app_sync.py doctor diagnostics (#1549 failure categories, #1550 frozen-FDD freshness check).

Failures are mocked at urllib's urlopen; one test connects to a real refused loopback port.
"""

from __future__ import annotations

import datetime
import errno
import socket
import ssl
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from test_nf_app_install import doctor_nf, make_manifest, sync

SECRET_URL = "https://admin:s3cr3t-pw@console.example:8443/prefix?token=abc123"
PASSWORD = "dummy-test-password"


def console(base: str = "http://127.0.0.1:9") -> "sync.Console":
    return sync.Console(base, "admin", PASSWORD)


def raising(exc: BaseException):
    def fake(req, *a, **k):
        raise exc
    return fake


def fail_with(monkeypatch, exc, base: str = "https://nf.example:8443", path: str = "/api/v1/apps"):
    monkeypatch.setattr(sync.urllib.request, "urlopen", raising(exc))
    with pytest.raises(SystemExit) as e:
        console(base).call("GET", path)
    return e.value


# ---------------------------------------------------------------- connectivity

@pytest.mark.parametrize("exc,phrase", [
    (urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")), "connection refused"),
    (urllib.error.URLError(socket.gaierror(-2, "Name or service not known")), "DNS lookup failed"),
    (urllib.error.URLError(OSError(errno.ENETUNREACH, "Network is unreachable")), "network or host unreachable"),
    (urllib.error.URLError(OSError(errno.EHOSTUNREACH, "No route to host")), "network or host unreachable"),
    (urllib.error.URLError(socket.timeout("timed out")), "connect timed out"),
    (socket.timeout("The read operation timed out"), "read timed out"),          # raised while reading the reply
    (ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"), "connection dropped"),
])
def test_transport_failures_are_connectivity_never_auth(monkeypatch, exc, phrase):
    e = fail_with(monkeypatch, exc)
    text = str(e)
    assert e.kind == "connectivity" and e.status == 0
    assert phrase in text
    assert "https://nf.example:8443" in text and "GET /api/v1/apps" in text
    assert "before any login was attempted" in text and "credentials were not validated" in text
    assert "front door" in text and "not NF's own port" in text and "loopback only" in text
    assert "auth" not in text.lower().replace("authentic", "")   # no authentication claim at all
    assert PASSWORD not in text


def test_doctor_labels_each_transport_failure_connectivity(monkeypatch, capsys, tmp_path):
    for exc in (urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused")),
                urllib.error.URLError(socket.gaierror(-2, "x")), urllib.error.URLError(socket.timeout("t")),
                socket.timeout("read")):
        monkeypatch.setattr(sync.urllib.request, "urlopen", raising(exc))
        assert sync.cmd_doctor(console("https://nf.example"), make_manifest(tmp_path)) == 1
        out = capsys.readouterr().out
        assert out.startswith("[FAIL] connectivity: GET /api/v1/apps: "), out
        assert "[FAIL] auth" not in out and "[PASS]" not in out


def test_real_refused_loopback_port_is_connectivity(tmp_path, capsys):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                       # nothing listens here now
    assert sync.cmd_doctor(console(f"http://127.0.0.1:{port}"), make_manifest(tmp_path)) == 1
    out = capsys.readouterr().out
    assert out.startswith("[FAIL] connectivity: GET /api/v1/apps: connection refused"), out
    assert f"http://127.0.0.1:{port}" in out and "credentials were not validated" in out
    assert "[FAIL] auth" not in out and PASSWORD not in out
    assert "doctor:" not in out or "check(s) failed" in out


# ---------------------------------------------------------------- TLS

def _ssl_error(code: int, message: str) -> ssl.SSLCertVerificationError:
    e = ssl.SSLCertVerificationError(1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {message}")
    e.verify_code, e.verify_message = code, message
    return e


@pytest.mark.parametrize("exc,phrase", [
    (_ssl_error(18, "self-signed certificate"), "TLS certificate not trusted"),
    (_ssl_error(20, "unable to get local issuer certificate"), "TLS certificate not trusted"),
    (_ssl_error(62, "Hostname mismatch, certificate is not valid for 'nf.example'."), "does not match the host name"),
    (_ssl_error(64, "IP address mismatch, certificate is not valid for '10.0.0.1'."), "does not match the host name"),
    (ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number"), "TLS handshake failed"),
])
def test_tls_failures_suggest_trust_options_never_a_bypass(monkeypatch, exc, phrase):
    e = fail_with(monkeypatch, urllib.error.URLError(exc))
    text = str(e)
    assert e.kind == "tls" and phrase in text
    assert "--ca-file" in text and "--pin-server-cert" in text
    assert "verification is never disabled" in text
    for bad in ("--insecure", "verify=False", "CERT_NONE", "-k "):
        assert bad not in text
    assert "credentials were not validated" not in text      # a TLS failure is not a connectivity claim


def test_doctor_labels_tls(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sync.urllib.request, "urlopen", raising(urllib.error.URLError(_ssl_error(18, "self-signed certificate"))))
    assert sync.cmd_doctor(console("https://nf.example"), make_manifest(tmp_path)) == 1
    assert capsys.readouterr().out.startswith("[FAIL] tls: ")


# ---------------------------------------------------------------- auth (real HTTP responses only)

def _serve(status: int, realm: str | None):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            if realm:
                self.send_header("WWW-Authenticate", f'Basic realm="{realm}"')
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("status,realm,phrases", [
    (401, "restricted", ("HTTP 401", "Caddy front door")),
    (401, "nf-", ("HTTP 401", "NF itself")),
    (403, "restricted", ("HTTP 403", "forbidden", "Caddy front door")),
    (403, None, ("HTTP 403", "forbidden", "not permitted")),
])
def test_only_real_401_403_responses_are_auth(status, realm, phrases, tmp_path, capsys):
    srv = _serve(status, realm)
    try:
        c = console(f"http://127.0.0.1:{srv.server_port}")
        with pytest.raises(SystemExit) as e:
            c.apps()
        assert e.value.kind == "auth" and e.value.status == status
        for p in phrases:
            assert p in str(e.value)
        assert sync.cmd_doctor(c, make_manifest(tmp_path)) == 1
        assert capsys.readouterr().out.startswith("[FAIL] auth: ")
    finally:
        srv.shutdown()


def test_other_http_errors_are_not_auth():
    srv = _serve(502, None)
    try:
        with pytest.raises(SystemExit) as e:
            console(f"http://127.0.0.1:{srv.server_port}").apps()
        assert e.value.kind == "http" and e.value.status == 502
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- redaction and read-only

def test_messages_show_scheme_host_port_path_only(monkeypatch):
    nested = ConnectionRefusedError(errno.ECONNREFUSED, f"refused {SECRET_URL} Authorization: Basic YWRtaW46cw==")
    e = fail_with(monkeypatch, urllib.error.URLError(nested), base=SECRET_URL, path="/api/v1/sites?pageSize=500&apikey=k-999")
    text = str(e)
    assert "https://console.example:8443" in text and "GET /api/v1/sites:" in text
    for leak in ("admin", "s3cr3t-pw", "token", "abc123", "apikey", "k-999", "Authorization", "YWRtaW46", "/prefix"):
        assert leak not in text, (leak, text)


def test_safe_origin_forms():
    assert sync.safe_origin("http://u:p@10.0.0.5/x?q=1") == "http://10.0.0.5:80"
    assert sync.safe_origin("https://[::1]:8443") == "https://[::1]:8443"
    assert sync.safe_origin("https://host") == "https://host:443"


def test_doctor_failure_makes_only_get_requests(monkeypatch, tmp_path):
    methods = []

    def fake(req, *a, **k):
        methods.append(req.get_method())
        raise urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake)
    assert sync.cmd_doctor(console("http://127.0.0.1:9"), make_manifest(tmp_path)) == 1
    assert methods == ["GET"], "doctor stops at the failed preflight and mutates nothing"


# ---------------------------------------------------------------- FDD freshness (#1550)

NOW = datetime.datetime(2026, 11, 9, 15, 0, tzinfo=datetime.timezone.utc)


def iso(minutes_ago: float) -> str:
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_point(minutes_ago: float, uuid: str = "raw-1") -> dict:
    return {"uuid": uuid, "attrs": {"markers": "point,his", "equipRef": "e"}, "latestValue": {"ts": iso(minutes_ago), "double": 1}}


def result_point(minutes_ago: float, status: str = "ok", reason: str = "", uuid: str = "res-1") -> dict:
    return {"uuid": uuid, "attrs": {"markers": "point,his,fault,fdd", "ruleRef": "FC1", "fddStatus": status, "fddReason": reason,
                                    "fddLastRun": iso(1 if status == "stale" else minutes_ago)},   # rewritten even when only flagged stale
            "latestValue": {"ts": iso(minutes_ago), "double": 0}}


class Pts:
    def __init__(self, points):
        self.points, self.calls = points, []

    def call(self, method, path, body=None, ok_404=False):
        self.calls.append((method, path))
        assert path == "/api/v1/point/query" and body["layer"] == "default"
        return {"points": self.points}


def test_computed_results_fresh_pass():
    lvl, text = sync.fdd_freshness(Pts([raw_point(2), result_point(20)]), 3600, NOW)
    assert lvl == "pass" and "computed results 20 min old" in text and "raw history 2 min old" in text


def test_frozen_computed_results_with_fresh_raw_fail_and_name_the_stale_reasons():
    pts = [raw_point(2), result_point(19 * 60, "stale", "required roles missing (fan_cmd)"),
           result_point(19 * 60, "stale", "required roles missing (sat)", uuid="res-2"),
           {"uuid": "tl", "attrs": {"markers": "point,his,fault_timeline", "ruleRef": "FC1", "fddKind": "fault-timeline",
                                    "fddTimelineThrough": iso(19 * 60)}, "latestValue": {"ts": iso(19 * 60)}}]
    lvl, text = sync.fdd_freshness(Pts(pts), 3600, NOW)
    assert lvl == "fail"
    assert "computed results 19.0 h old" in text and "2x the schedule" in text and "fdd runs every 60 min" in text
    assert "raw history is fresh" in text and "newest sample 2 min ago" in text
    assert "2 results flagged stale (required roles missing x2)" in text


def test_threshold_is_twice_the_schedule_interval():
    ok = sync.fdd_freshness(Pts([raw_point(1), result_point(119)]), 3600, NOW)[0]
    bad = sync.fdd_freshness(Pts([raw_point(1), result_point(121)]), 3600, NOW)[0]
    assert (ok, bad) == ("pass", "fail")
    assert sync.fdd_freshness(Pts([raw_point(1), result_point(25)]), 900, NOW)[0] == "pass"      # 15 min schedule -> 30 min
    assert sync.fdd_freshness(Pts([raw_point(1), result_point(35)]), 900, NOW)[0] == "fail"


def test_stale_raw_data_is_a_warning_not_a_fdd_failure():
    lvl, text = sync.fdd_freshness(Pts([raw_point(600), result_point(900)]), 3600, NOW)
    assert lvl == "warn" and "raw history is also stale" in text


def test_no_results_or_no_raw_data_warn():
    assert sync.fdd_freshness(Pts([raw_point(1)]), 3600, NOW)[0] == "warn"
    assert sync.fdd_freshness(Pts([result_point(1)]), 3600, NOW)[0] == "warn"


def test_rrule_interval_and_timestamp_helpers():
    assert sync.rrule_interval_seconds("DTSTART:20261101T000700Z\nRRULE:FREQ=HOURLY;INTERVAL=1") == 3600
    assert sync.rrule_interval_seconds("RRULE:FREQ=MINUTELY;INTERVAL=20") == 1200
    assert sync.rrule_interval_seconds("RRULE:FREQ=DAILY") == 86400
    assert sync.rrule_interval_seconds("RRULE:FREQ=MONTHLY") is None and sync.rrule_interval_seconds(None) is None
    assert sync.parse_ts("2026-11-08T19:00:00.123456789Z") == datetime.datetime(2026, 11, 8, 19, 0, 0, 123456, tzinfo=datetime.timezone.utc)
    assert sync.parse_ts("garbage") is None and sync.parse_ts(None) is None


def test_doctor_fails_on_frozen_fdd_and_stays_read_only(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sync, "timescale_schema_check", lambda *_args, **_kwargs: ("PASS", "Timescale schema version 3"))
    m, nf = doctor_nf(tmp_path, sites=[{"id": "s", "latitude": 43.0, "longitude": -89.0}],
                      redirect=(302, {"Location": "https://h/api/v1/apps/static/new-app/"}), timescale=True)
    real = nf.call
    points = [raw_point(3), result_point(20 * 60, "stale", "no input data in window (newest sample at 2026-11-08T19:00:00Z)")]

    def call(method, path, body=None, ok_404=False):
        if path == "/api/v1/point/query" and body.get("layer") == "default":
            nf.log.append((method, path))
            return {"points": points}
        return real(method, path, body, ok_404)

    nf.call = call
    assert sync.cmd_doctor(nf, m, now=NOW) == 1
    out = capsys.readouterr().out
    assert "[FAIL] fdd freshness: computed results 20.0 h old" in out and "no input data in window x1" in out, out
    assert "1 check(s) failed" in out
    assert all(c[0] == "GET" or c[1] == "/api/v1/point/query" for c in nf.log), nf.log
    points[:] = [raw_point(3), result_point(10)]
    assert sync.cmd_doctor(nf, m, now=NOW) == 0
    assert "[PASS] fdd freshness: computed results 10 min old" in capsys.readouterr().out
