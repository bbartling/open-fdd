#!/usr/bin/env python3
"""Finite requestor-only ZAP passive scan for an owned qualification stack.

This runner makes no OpenAPI import, spider, active scan, add-on update, or
provider request. Requestor header syntax follows ZAP's AF requestor job docs:
https://www.zaproxy.org/docs/desktop/addons/automation-framework/job-requestor/
The internal network is the isolation control; the 12-request limit is
validated after execution from HAR and is not a preventive firewall budget.
HAR and report data are secret-bearing and remain private; only hashes and
sanitized alert summaries escape. This is not a full qualification scan.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlsplit

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required") from exc

HERE = Path(__file__).resolve().parent
AF_RUNNER = HERE / "run_af_disposable.py"
ZAP_DIGEST = "sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
PROBE = "X-OpenFDD-Static-Passive-Probe"
PATHS = (
    "/api/auth/me", "/app/", "/app/assets/js/app.js",
    "/app/assets/js/ttl-model.js", "/openapi.json", "/api/sites/buildings",
    "/api/fdd/rules", "/api/providers/sites", "/api/version",
)
PHASES = ("before", "during", "after")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[a-f0-9]{16,64}$")
DOCKER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class GateError(ValueError):
    pass


class CapturedScanError(GateError):
    def __init__(self, message: str, output: bytes):
        super().__init__(message)
        self.output = output


def _af_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("openfdd_static_af_helpers", AF_RUNNER)
    if spec is None or spec.loader is None:
        raise GateError("cannot load HAR validation helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(argv: list[str], *, timeout: int = 15) -> str:
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    if p.returncode:
        raise GateError(f"command failed ({p.returncode}): {Path(argv[0]).name}")
    return p.stdout


def _inspect(kind: str, name: str) -> dict:
    raw = _run(["docker", kind, "inspect", name])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"invalid Docker {kind} inspection JSON") from exc
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GateError(f"invalid Docker {kind} inspection")
    return data[0]


def validate_images(central: str, timescale: str, zap: str) -> None:
    for name, value in (("central", central), ("timescale", timescale), ("zap", zap)):
        if not IMAGE_RE.fullmatch(value):
            raise GateError(f"{name} image must be a local sha256 image ID")
        _run(["docker", "image", "inspect", value])
    if zap != ZAP_DIGEST:
        raise GateError("ZAP image digest differs from the pinned qualification image")


def validate_owned_stack(*, network: str, central_container: str,
                         timescale_container: str, nonce: str,
                         central_image: str, timescale_image: str) -> str:
    if not NONCE_RE.fullmatch(nonce):
        raise GateError("invalid run nonce")
    if any(not DOCKER_NAME_RE.fullmatch(v) for v in (network, central_container, timescale_container)):
        raise GateError("network/container name is invalid")
    net = _inspect("network", network)
    labels = net.get("Labels") or {}
    if net.get("Name") != network or net.get("Internal") is not True:
        raise GateError("network is not the exact internal qualification network")
    if labels.get("openfdd.qualification.owner") != "static-passive" or labels.get("openfdd.qualification.run_nonce") != nonce:
        raise GateError("network ownership labels do not match this run")
    inspected = []
    for name, image, required_alias in ((central_container, central_image, "central"),
                                        (timescale_container, timescale_image, "timescale")):
        c = _inspect("container", name)
        inspected.append(c)
        clabels = (c.get("Config") or {}).get("Labels") or {}
        if clabels.get("openfdd.qualification.owner") != "static-passive" or clabels.get("openfdd.qualification.run_nonce") != nonce:
            raise GateError("container ownership labels do not match this run")
        if c.get("Image") != image or (c.get("State") or {}).get("Running") is not True:
            raise GateError("stack container is stopped or image ID mismatches")
        networks = (c.get("NetworkSettings") or {}).get("Networks") or {}
        if set(networks) != {network}:
            raise GateError("stack container is attached to an unexpected network")
        aliases = networks[network].get("Aliases") or []
        if required_alias not in aliases:
            raise GateError("stack service DNS alias is missing from the owned network")
        bindings = (c.get("HostConfig") or {}).get("PortBindings") or {}
        if any(values for values in bindings.values()):
            raise GateError("owned stack container has an unexpected published host port")
    expected_ids = {c.get("Id") for c in inspected}
    members = net.get("Containers") or {}
    if set(members) != expected_ids or len(members) != 2:
        raise GateError("owned internal network has unexpected or ambiguous members")
    alias_owners: dict[str, int] = {}
    for c in inspected:
        endpoint = ((c.get("NetworkSettings") or {}).get("Networks") or {})[network]
        for alias in set(endpoint.get("Aliases") or []):
            alias_owners[alias] = alias_owners.get(alias, 0) + 1
    if any(n != 1 for n in alias_owners.values()) or alias_owners.get("central") != 1 or alias_owners.get("timescale") != 1:
        raise GateError("owned network DNS aliases are ambiguous")
    env = (( _inspect("container", central_container).get("Config") or {}).get("Env") or [])
    for entry in env:
        if entry.startswith("OPENFDD_PROVIDER_SITES=") and entry.split("=", 1)[1].strip() not in ("", "[]"):
            raise GateError("provider configuration must be empty for this scan")
    return central_container


def load_auth_file(path: Path) -> str:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
        raise GateError("auth header file must be a regular 0600-or-stricter file")
    value = path.read_text(encoding="utf-8").strip()
    if not value.startswith("Bearer ") or len(value) < 20 or "\n" in value:
        raise GateError("auth header file must contain one Bearer header value")
    return value


def build_plan(origin: str, nonce: str, bearer: str, work: Path) -> dict:
    base = origin.rstrip("/")
    jobs = []

    def request(name: str, path: str, auth: str, probe: str | None = None) -> dict:
        headers = ["Authorization:" + auth, "Accept:application/json"]
        if probe:
            headers.append(f"{PROBE}:{probe}-{nonce}")
        return {"type": "requestor", "name": name, "requests": [{
            "url": base + path, "name": name, "method": "GET", "headers": headers,
        }]}

    jobs.append(request("auth-before", "/api/auth/me", bearer, "before"))
    for i, path in enumerate(PATHS[1:5], 1):
        jobs.append(request(f"finite-get-{i}", path, bearer))
    jobs.append(request("auth-during", "/api/auth/me", bearer, "during"))
    for i, path in enumerate(PATHS[5:], 5):
        jobs.append(request(f"finite-get-{i}", path, bearer))
    jobs.append(request("auth-invalid-bearer", "/api/auth/me", "Bearer invalid-static-passive", "invalid"))
    jobs.append(request("auth-after", "/api/auth/me", bearer, "after"))
    jobs.extend([
        {"type": "passiveScan-wait", "parameters": {"maxDuration": 0}},
        {"type": "export", "alwaysRun": True, "parameters": {
            "type": "har", "source": "all", "fileName": "/zap/wrk/out/messages.har",
        }},
        {"type": "report", "alwaysRun": True, "parameters": {
            "template": "traditional-json", "reportDir": "/zap/wrk/out",
            "reportFile": "report.json", "reportTitle": "Open-FDD finite passive scan",
        }},
    ])
    plan = {"env": {
        "contexts": [{"name": "openfdd-static-passive", "urls": [base],
                      "includePaths": [r"^" + re.escape(base) + r"(?:/.*)?$"]}],
        "parameters": {"failOnError": True, "failOnWarning": False,
                       "continueOnFailure": False, "progressToStdout": True}}, "jobs": jobs}
    return plan


def summarize_traffic(raw: bytes) -> dict:
    """Header/body-free evidence for rejected runs; never filters traffic."""
    observed = _af_module().parse_scanner_messages(raw)
    # Keep exporter metadata and payload dimensions, but never retain header or
    # body values. ZAP's HAR exporter writes _zapMessageType as an integer.
    # Structural Site Tree references can therefore be distinguished from
    # requestor history without treating every status-0 entry as harmless.
    try:
        har_entries = json.loads(raw.decode("utf-8"))["log"]["entries"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise GateError("scanner message history is malformed or truncated") from None
    if len(har_entries) != len(observed):
        raise GateError("scanner message history diagnostics are inconsistent")
    counts = Counter()
    for entry, raw_entry in zip(observed, har_entries):
        uri = urlsplit(entry.url)
        raw_type = raw_entry.get("_zapMessageType")
        if isinstance(raw_type, int) and not isinstance(raw_type, bool):
            zap_type = raw_type
        elif isinstance(raw_type, str) and raw_type.isdecimal():
            zap_type = int(raw_type)
        else:
            zap_type = None
        request = raw_entry.get("request") or {}
        post_data = request.get("postData") or {}
        request_text = post_data.get("text")
        request_body_bytes = len(request_text.encode("utf-8")) if isinstance(request_text, str) else 0
        counts[(entry.method, uri.scheme, uri.hostname, uri.port, uri.path,
                entry.status, zap_type, request_body_bytes, len(entry.body),
                len(entry.request_headers), len(entry.response_headers))] += 1
    return {
        "observed_message_count": len(observed),
        "traffic_summary": [
            {"method": k[0], "scheme": k[1], "host": k[2], "port": k[3],
             "path": k[4][:160], "status": k[5], "zap_message_type": k[6],
             "request_body_bytes": k[7], "response_body_bytes": k[8],
             "request_header_count": k[9], "response_header_count": k[10],
             "count": count}
            for k, count in sorted(counts.items(), key=lambda item: repr(item[0]))[:64]
        ],
        "har_sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_har(raw: bytes, *, origin: str, nonce: str, bearer: str,
                 expected_username: str, expected_version: str) -> dict:
    af = _af_module()
    try:
        entries = af.parse_scanner_messages(raw)
    except af.EvidenceError as exc:
        raise GateError("scanner message history is malformed or truncated") from exc
    # Pinned ZAP exports temporary SiteMap ancestors as well as requestor
    # history. TYPE_TEMPORARY=0 is not a blanket exemption for status 0:
    # only the exact nine empty ancestor records from this finite plan qualify.
    # TYPE_ZAP_USER=15 identifies the requestor records. Official contracts:
    # zaproxy/zaproxy HistoryReference.java and zaproxy/zap-extensions
    # exim/har/HarExporter.java; both retain their types in _zapMessageType.
    raw_entries = json.loads(raw.decode("utf-8"))["log"]["entries"]
    ancestor_urls = {origin.rstrip("/") + p for p in (
        "", "/api", "/api/auth", "/api/fdd", "/api/providers", "/api/sites",
        "/app", "/app/assets", "/app/assets/js",
    )}
    ancestors = set()
    wire = []
    for e, item in zip(entries, raw_entries, strict=True):
        record_type = item.get("_zapMessageType")
        if isinstance(record_type, str) and record_type.isdecimal():
            record_type = int(record_type)
        if (not isinstance(record_type, int) or isinstance(record_type, bool)
                or record_type not in (0, 15)):
            raise GateError("HAR has missing or unexpected ZAP history type")
        request = item.get("request") or {}
        post = request.get("postData")
        # HAR exporters may include an empty postData object for a GET. Treat
        # only the known, truly empty representation as metadata, never as a
        # reason to discard a real body/parameter or unknown encoded payload.
        if post is not None and (
            not isinstance(post, dict)
            or set(post) - {"mimeType", "text", "params", "comment"}
            or post.get("text", "") != ""
            or post.get("params", []) != []
        ):
            raise GateError("finite GET history unexpectedly contains a request body")
        if record_type == 15:
            wire.append(e)
            continue
        if (e.url not in ancestor_urls or e.url in ancestors or e.method != "GET"
                or e.status != 0 or e.body or e.response_headers):
            raise GateError("HAR temporary record is not an exact empty SiteMap ancestor")
        ancestors.add(e.url)
    if ancestors != ancestor_urls:
        raise GateError("HAR temporary SiteMap ancestor set is incomplete")
    exported_count = len(entries)
    entries = wire
    expected = [("GET", origin.rstrip("/") + p) for p in PATHS]
    expected += [("GET", origin.rstrip("/") + "/api/auth/me")] * 3
    # A multiset validates counts while allowing AF's recorded order to be checked below.
    actual = [(e.method, e.url) for e in entries]
    if len(entries) != 12 or sorted(actual) != sorted(expected):
        raise GateError("HAR request count or exact method/origin/path set mismatches finite plan")
    if any(urlsplit(e.url).query or urlsplit(e.url).fragment or urlsplit(e.url).username for e in entries):
        raise GateError("HAR contains query, fragment, or URL credentials")
    nonce_entries = {}
    for e in entries:
        values = e.req_header(PROBE)
        if values:
            if len(values) != 1 or not values[0].endswith("-" + nonce):
                raise GateError("HAR nonce probe header mismatches")
            phase = values[0].split("-", 1)[0]
            if phase in nonce_entries:
                raise GateError("duplicate auth phase probe")
            nonce_entries[phase] = e
    if set(nonce_entries) != {"before", "during", "after", "invalid"}:
        raise GateError("HAR missing or duplicate phase/bad-bearer probe")
    for phase in PHASES:
        e = nonce_entries[phase]
        if e.url != origin.rstrip("/") + "/api/auth/me":
            raise GateError(f"{phase} auth phase probe used an unexpected path")
        if e.req_header("authorization") != [bearer] or e.status != 200:
            raise GateError(f"{phase} auth probe is not authenticated HTTP 200")
        result = af.verify_auth_me_response(status=e.status, body=e.body,
            content_type=(e.resp_header("content-type") or [e.mime_type])[0],
            expected_username=expected_username)
        if not result.get("ok"):
            raise GateError(f"{phase} auth identity verification failed")
    if not (nonce_entries["before"].index < nonce_entries["during"].index < nonce_entries["after"].index):
        raise GateError("auth phase probes are out of order")
    bad = nonce_entries["invalid"]
    if bad.req_header("authorization") != ["Bearer invalid-static-passive"] or bad.status != 401:
        raise GateError("bad-bearer control did not return HTTP 401")
    try:
        denial = json.loads(bad.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("bad-bearer response is not JSON") from exc
    if not isinstance(denial, dict) or denial.get("ok") is not False:
        raise GateError("bad-bearer response did not confirm denial")
    for e in entries:
        if not e.req_header(PROBE) and e.req_header("authorization") != [bearer]:
            raise GateError("finite GET lacks exact scanner bearer header")
        if e.status != 200 and e is not bad:
            raise GateError("finite positive GET did not return HTTP 200")
    version_entry = next(e for e in entries if e.url == origin.rstrip("/") + "/api/version")
    try:
        version = json.loads(version_entry.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("candidate /api/version response is invalid JSON") from exc
    if not isinstance(version, dict) or version.get("ok") is not True or version.get("service") != "openfdd-central":
        raise GateError("candidate /api/version identity is invalid")
    version_value = version.get("version")
    if not isinstance(version_value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\+[0-9a-f]{7,40}", version_value):
        raise GateError("candidate version/source identity is missing or malformed")
    if version_value != expected_version:
        raise GateError("candidate /api/version does not match expected source version")
    return {"request_count": 12, "exported_har_entry_count": exported_count,
            "artifact_node_count": len(ancestors), "wire_request_count": len(entries),
            "auth_positive_phases": list(PHASES),
            "bad_bearer_status": 401, "candidate_version": version_value,
            "candidate_service": version["service"]}


def _alert_summary(raw: bytes, *, origin: str) -> dict:
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("ZAP traditional JSON report is invalid") from exc
    af = _af_module()
    parsed_origin = urlsplit(origin)
    target = af.TargetOrigin(parsed_origin.scheme, parsed_origin.hostname or "", parsed_origin.port,
                             origin, "docker_network")
    try:
        parsed = af.parse_traditional_report(report, target)
    except af.EvidenceError as exc:
        raise GateError("ZAP traditional report failed strict schema/scope validation") from exc
    return {"alert_counts_by_risk": parsed.by_risk(),
            "rule_ids": sorted({item.plugin_id for item in parsed.instances}),
            "alert_instances": [
                {"rule_id": item.plugin_id, "risk": item.risk,
                 "method": item.method, "path": urlsplit(item.url).path[:160]}
                for item in parsed.instances[:128]
            ],
            "alert_instances_truncated": len(parsed.instances) > 128,
            "stopping_insight": parsed.stopping_insight}


def _write_summary(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _bounded_communicate(proc: subprocess.Popen, *, timeout: int = 180,
                         max_bytes: int = 2 * 1024 * 1024) -> bytes:
    """Capture bounded scanner progress; kill immediately if it floods output."""
    if proc.stdout is None:
        raise GateError("scanner stdout pipe is unavailable")
    captured = bytearray()
    overflow = Event()

    def reader() -> None:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                return
            if len(captured) + len(chunk) > max_bytes:
                overflow.set()
                try:
                    proc.kill()
                except OSError:
                    pass
            elif not overflow.is_set():
                captured.extend(chunk)

    thread = Thread(target=reader, daemon=True)
    thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        thread.join(timeout=5)
        if thread.is_alive():
            raise GateError("scanner progress stream did not close") from exc
        proc.stdout.close()
        raise CapturedScanError("scanner exceeded 180 second hard timeout", bytes(captured)) from exc
    thread.join(timeout=5)
    if thread.is_alive():
        raise GateError("scanner progress stream did not close")
    proc.stdout.close()
    if overflow.is_set():
        raise CapturedScanError("scanner output exceeded the 2 MiB bounded progress limit", bytes(captured))
    return bytes(captured)


def classify_scan(counts: dict[str, int], stopping_insight: bool = False) -> str:
    if counts.get("High", 0) or counts.get("Medium", 0):
        return "FAIL"
    if counts.get("Low", 0) or counts.get("Informational", 0) or stopping_insight:
        return "REVIEW"
    return "PASS"


def sanitize_progress(output: str, bearer: str) -> list[str]:
    secrets = _af_module().SecretSet([bearer])
    return [secrets.scrub(line)[:240] for line in output.splitlines()[-30:]]


def require_passive_drain(output: str) -> None:
    errors = _af_module().passive_drain_errors(output, expected=1)
    if errors:
        raise GateError("passiveScan-wait completion was not confirmed")


def run(args: argparse.Namespace) -> dict:
    base = {"scan_class": "finite_requestor_only_passive",
            "qualification_status": "NOT_FULLY_QUALIFIED",
            "planned_request_count": 12,
            "network_enforcement": "owned_internal_network_only; count validated post-run from HAR",
            "run_nonce": args.run_nonce,
            "images": {"central": args.central_image, "timescale": args.timescale_image,
                       "zap": args.zap_image},
            "owned_stack": {"network": args.network, "central_container": args.central_container,
                            "timescale_container": args.timescale_container},
            "expected_version": args.expected_version}
    temp: Path | None = None
    scanner_name = "openfdd-static-passive-" + args.run_nonce[:16]
    origin = "http://central:8080"
    started = time.monotonic()
    scanner_progress: list[str] = []
    bearer = ""
    try:
        validate_images(args.central_image, args.timescale_image, args.zap_image)
        validate_owned_stack(network=args.network, central_container=args.central_container,
                             timescale_container=args.timescale_container, nonce=args.run_nonce,
                             central_image=args.central_image, timescale_image=args.timescale_image)
        if not re.fullmatch(r"[A-Za-z0-9._@-]{1,64}", args.expected_username):
            raise GateError("invalid expected username")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\+[0-9a-f]{7,40}", args.expected_version):
            raise GateError("invalid expected candidate version/source identity")
        # No credential is read until all image, network, container, membership,
        # port-binding, provider, alias, and ownership gates pass.
        bearer = load_auth_file(Path(args.auth_header_file))
        temp = Path(tempfile.mkdtemp(prefix="openfdd-static-passive-"))
        os.chmod(temp, 0o700)
        out = temp / "out"
        out.mkdir(mode=0o700)
        plan_path = temp / "plan.yaml"
        plan_path.write_text(yaml.safe_dump(build_plan(origin, args.run_nonce, bearer, temp), sort_keys=False), encoding="utf-8")
        os.chmod(plan_path, 0o600)
        cmd = ["docker", "run", "--pull=never", "--name", scanner_name,
               "--label", "openfdd.qualification.owner=static-passive-scanner",
               "--label", f"openfdd.qualification.run_nonce={args.run_nonce}",
               "--network", args.network, "--cpus=2", "--memory=2g", "--pids-limit=256",
               "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
               "-u", f"{os.getuid()}:{os.getgid()}",
               "--mount", f"type=bind,src={plan_path},dst=/zap/wrk/plan.yaml,readonly",
               "--mount", f"type=bind,src={out},dst=/zap/wrk/out",
               args.zap_image, "zap.sh", "-cmd", "-autorun", "/zap/wrk/plan.yaml"]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        stdout = _bounded_communicate(proc).decode("utf-8", errors="replace")
        scanner_progress = sanitize_progress(stdout, bearer)
        if proc.returncode:
            raise GateError(f"scanner exited {proc.returncode}")
        require_passive_drain(stdout)
        har = out / "messages.har"
        report = out / "report.json"
        if (not har.is_file() or har.stat().st_size < 100 or har.stat().st_size > 16 * 1024 * 1024
                or not report.is_file() or report.stat().st_size < 10
                or report.stat().st_size > 16 * 1024 * 1024):
            raise GateError("scanner HAR or traditional JSON report missing/truncated")
        har_bytes = har.read_bytes()
        # Keep header/body-free diagnostics even when validation fails.
        base.update(summarize_traffic(har_bytes))
        evidence = validate_har(har_bytes, origin=origin, nonce=args.run_nonce,
                                bearer=bearer, expected_username=args.expected_username,
                                expected_version=args.expected_version)
        evidence.update(_alert_summary(report.read_bytes(), origin=origin))
        counts = evidence["alert_counts_by_risk"]
        evidence.update({"execution_status": "PASS", "auth_proof": "PASS",
                         "scan_verdict": classify_scan(counts, evidence["stopping_insight"]),
                         "har_sha256": hashlib.sha256(har_bytes).hexdigest(),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "scope": origin, "confirmed_har_request_count": 12,
                         "passive_queue_drained": True, "scanner_progress_tail": scanner_progress})
        base.update(evidence)
        _write_summary(args.output, base)
        return base
    except (GateError, OSError, subprocess.SubprocessError, yaml.YAMLError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, CapturedScanError):
            scanner_progress = sanitize_progress(exc.output.decode("utf-8", errors="replace"), bearer)
        base.update({"execution_status": "ERROR", "auth_proof": "NOT_PROVEN",
                     "scan_verdict": "NOT_ASSESSED", "error": str(exc)[:240],
                     "elapsed_seconds": round(time.monotonic() - started, 3),
                     "scanner_progress_tail": scanner_progress})
        try:
            _write_summary(args.output, base)
        except OSError:
            pass
        return base
    finally:
        # Remove only the scanner created by this run, after verifying its labels.
        if NONCE_RE.fullmatch(args.run_nonce):
            try:
                c = _inspect("container", scanner_name)
                labels = (c.get("Config") or {}).get("Labels") or {}
                if labels.get("openfdd.qualification.owner") == "static-passive-scanner" and labels.get("openfdd.qualification.run_nonce") == args.run_nonce:
                    subprocess.run(["docker", "rm", "-f", scanner_name], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            except Exception:
                pass
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network", required=True)
    p.add_argument("--central-container", required=True)
    p.add_argument("--timescale-container", required=True)
    p.add_argument("--run-nonce", required=True)
    p.add_argument("--central-image", required=True)
    p.add_argument("--timescale-image", required=True)
    p.add_argument("--zap-image", default=ZAP_DIGEST)
    p.add_argument("--auth-header-file", required=True)
    p.add_argument("--expected-username", required=True)
    p.add_argument("--expected-version", required=True,
                   help="exact candidate /api/version string, including source SHA suffix")
    p.add_argument("--output", type=Path, required=True)
    return p.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result, sort_keys=True))
    if result.get("execution_status") != "PASS" or result.get("scan_verdict") == "FAIL":
        raise SystemExit(1)
