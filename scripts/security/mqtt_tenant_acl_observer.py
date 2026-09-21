#!/usr/bin/env python3
"""Positive observer for Wave L tenant MQTT ACL + key-mode 640 evidence.

Always validates generated ACL content and entrypoint key-mode 640.
When Docker is available, starts a disposable mosquitto with password+ACL
and proves own-topic publish OK / foreign-tenant publish deny.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "mqtt_tenant_acl"))

from generate_acl import (  # noqa: E402
    DEFAULT_ACL,
    FIXTURE_DIR,
    edge_topic_prefix,
    load_tenants,
    product_edge_user,
    render_acl,
    render_product_acl,
    semantic_errors,
    write_acl,
)

ENTRYPOINT = ROOT / "services" / "mqtt" / "docker-entrypoint-openfdd.sh"


def resolve_mqtt_acl_image() -> tuple[str, str]:
    """Return (image_ref, acl_source) for the live observer.

    Product path (default when EXECUTE / tip pin present): openfdd-mqtt + provisioner ACL.
    Fixture broker (eclipse-mosquitto) only when explicitly allowed.
    """
    allow_fixture = os.environ.get("OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER", "").strip() in (
        "1",
        "true",
        "yes",
    )
    explicit = (os.environ.get("OPENFDD_MQTT_ACL_IMAGE") or "").strip()
    tag = (
        os.environ.get("OPENFDD_IMAGE_TAG")
        or os.environ.get("OPENFDD_MQTT_ACL_TAG")
        or "nightly"
    ).strip()
    product = f"ghcr.io/bbartling/openfdd-mqtt:{tag}"

    if allow_fixture and (not explicit or "eclipse-mosquitto" in explicit):
        return (explicit or "eclipse-mosquitto:2", "fixture")
    if explicit:
        if "eclipse-mosquitto" in explicit and not allow_fixture:
            raise ValueError(
                "OPENFDD_MQTT_ACL_IMAGE is eclipse-mosquitto but "
                "OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER!=1 — refuse fixture broker for product gate"
            )
        source = "provisioner" if "openfdd-mqtt" in explicit else "custom"
        return (explicit, source)
    return (product, "provisioner")


# Module-level default for tests / legacy imports; live path re-resolves.
try:
    MOSQUITTO_IMAGE, _ACL_SOURCE_DEFAULT = resolve_mqtt_acl_image()
except ValueError:
    MOSQUITTO_IMAGE = os.environ.get("OPENFDD_MQTT_ACL_IMAGE", "eclipse-mosquitto:2")
    _ACL_SOURCE_DEFAULT = "fixture"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_key_mode_640() -> dict:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    ok = (
        "server.key.pem" in text
        and "chmod 640" in text
        and "world-readable" in text.lower()
    )
    return {
        "check": "mqtt.key_mode_640",
        "status": "PASS" if ok else "FAIL",
        "detail": str(ENTRYPOINT.relative_to(ROOT)) if ok else "chmod 640 missing",
    }


def check_acl_content(acl_path: Path) -> dict:
    text = acl_path.read_text(encoding="utf-8")
    errs = semantic_errors(text)
    return {
        "check": "mqtt.acl.content_semantics",
        "status": "PASS" if not errs else "FAIL",
        "errors": errs,
        "acl_path": str(acl_path),
    }


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=20,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kwargs)


def run_live_broker(acl_text: str, art: Path, *, image: str, acl_source: str) -> dict:
    """Disposable mosquitto: mTLS identity + ACL; own OK / foreign deny.

    Password auth cannot use ':' in usernames; production edge identities use
    colon-separated CNs, so the live observer issues ephemeral client certs
    whose CN matches the ACL ``user`` lines.
    """
    cfg = load_tenants()
    tenants = cfg["tenants"]
    a, b = tenants[0], tenants[1]
    # Product CN grammar omits building; fixture ACL uses full edge_user.
    if acl_source == "provisioner":
        cn_a = product_edge_user(a["tenant_id"], a["edge_id"])
        cn_b = product_edge_user(b["tenant_id"], b["edge_id"])
    else:
        cn_a = a["edge_user"]
        cn_b = b["edge_user"]
    name = f"openfdd-mqtt-acl-obs-{os.getpid()}-{int(time.time())}"
    tmp = Path(tempfile.mkdtemp(prefix="mqtt_acl_obs_"))
    result: dict = {
        "check": "mqtt.acl.live_broker_observer",
        "status": "ERROR",
        "image": image,
        "acl_source": acl_source,
        "container": name,
        "auth": "mtls_cn",
    }
    try:
        if shutil.which("openssl") is None:
            result["status"] = "BLOCKED"
            result["detail"] = "openssl required for disposable mTLS observer"
            return result

        (tmp / "acl").write_text(acl_text, encoding="utf-8")
        # Ephemeral CA + certs (never committed).
        ca_key, ca_pem = tmp / "ca.key.pem", tmp / "ca.pem"
        _run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=openfdd-mqtt-acl-obs-ca",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_pem),
            ],
            timeout=60,
        )

        def issue(name_: str, cn: str, *, server: bool = False) -> None:
            key = tmp / f"{name_}.key.pem"
            csr = tmp / f"{name_}.csr.pem"
            cert = tmp / f"{name_}.cert.pem"
            ext = tmp / f"{name_}.ext"
            if server:
                ext.write_text(
                    "extendedKeyUsage=serverAuth\n"
                    "subjectAltName=DNS:localhost,IP:127.0.0.1\n",
                    encoding="utf-8",
                )
            else:
                ext.write_text("extendedKeyUsage=clientAuth\n", encoding="utf-8")
            _run(
                [
                    "openssl",
                    "req",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    f"/CN={cn}",
                    "-keyout",
                    str(key),
                    "-out",
                    str(csr),
                ],
                timeout=60,
            )
            _run(
                [
                    "openssl",
                    "x509",
                    "-req",
                    "-days",
                    "1",
                    "-sha256",
                    "-in",
                    str(csr),
                    "-CA",
                    str(ca_pem),
                    "-CAkey",
                    str(ca_key),
                    "-CAcreateserial",
                    "-extfile",
                    str(ext),
                    "-out",
                    str(cert),
                ],
                timeout=60,
            )

        issue("server", "mqtt", server=True)
        issue("edge_a", cn_a)
        issue("edge_b", cn_b)
        # Mosquitto runs non-root; disposable certs must be group/world-readable.
        for p in tmp.glob("*.pem"):
            p.chmod(0o644)

        (tmp / "mosquitto.conf").write_text(
            "\n".join(
                [
                    "listener 8883",
                    "allow_anonymous false",
                    "require_certificate true",
                    "use_identity_as_username true",
                    "cafile /mosquitto/config/ca.pem",
                    "certfile /mosquitto/config/server.cert.pem",
                    "keyfile /mosquitto/config/server.key.pem",
                    "acl_file /mosquitto/config/acl",
                    "persistence false",
                    "log_dest stdout",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        _run(["docker", "pull", image], timeout=180)

        run = _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                "127.0.0.1::8883",
                "-v",
                f"{tmp}/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro",
                "-v",
                f"{tmp}/acl:/mosquitto/config/acl:ro",
                "-v",
                f"{tmp}/ca.pem:/mosquitto/config/ca.pem:ro",
                "-v",
                f"{tmp}/server.cert.pem:/mosquitto/config/server.cert.pem:ro",
                "-v",
                f"{tmp}/server.key.pem:/mosquitto/config/server.key.pem:ro",
                image,
            ],
            timeout=60,
        )
        if run.returncode != 0:
            result["status"] = "ERROR"
            result["detail"] = f"docker run failed: {run.stderr or run.stdout}"
            return result

        port_out = _run(["docker", "port", name, "8883"], timeout=30)
        host_port = None
        if port_out.returncode == 0 and port_out.stdout.strip():
            host_port = port_out.stdout.strip().rsplit(":", 1)[-1]
        if not host_port:
            result["status"] = "ERROR"
            result["detail"] = "could not resolve mapped broker port"
            return result
        result["host_port"] = host_port

        ready = False
        logs = _run(["docker", "logs", name], timeout=15)
        for _ in range(40):
            logs = _run(["docker", "logs", name], timeout=15)
            blob = ((logs.stdout or "") + (logs.stderr or "")).lower()
            if "mosquitto version" in blob or "opening ipv" in blob:
                ready = True
                break
            # Crash early?
            inspect = _run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                timeout=15,
            )
            if inspect.stdout.strip() != "true":
                break
            time.sleep(0.5)
        if not ready:
            result["status"] = "ERROR"
            result["detail"] = "broker did not become ready"
            (art / "broker.logs").write_text(
                (logs.stdout or "") + (logs.stderr or ""), encoding="utf-8"
            )
            return result

        topic_a = (
            edge_topic_prefix(a["tenant_id"], a["building_id"], a["edge_id"])
            + "/telemetry/observer"
        )
        topic_b = (
            edge_topic_prefix(b["tenant_id"], b["building_id"], b["edge_id"])
            + "/telemetry/observer"
        )

        # Issue a central cert so we can observe delivery (ACL grants central read).
        issue("central", cfg.get("central_user") or "central:ci")
        (tmp / "central.cert.pem").chmod(0o644)
        (tmp / "central.key.pem").chmod(0o644)

        sub_allow = f"{name}-sub-allow"
        sub_deny = f"{name}-sub-deny"
        allow_payload = tmp / "allow.payload"
        deny_payload = tmp / "deny.payload"
        allow_payload.write_text("", encoding="utf-8")
        deny_payload.write_text("", encoding="utf-8")

        # Client tools: always use upstream mosquitto image (product entrypoint
        # is broker-oriented). Broker container uses ``image`` (product when gated).
        client_image = os.environ.get(
            "OPENFDD_MQTT_ACL_CLIENT_IMAGE", "eclipse-mosquitto:2"
        )

        def start_sub(cname: str, topic: str, out_file: Path) -> None:
            # Background subscriber; -C 1 exits after one message or we kill it.
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    cname,
                    "--network",
                    "host",
                    "-v",
                    f"{tmp}:/certs:ro",
                    client_image,
                    "mosquitto_sub",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    host_port,
                    "--cafile",
                    "/certs/ca.pem",
                    "--cert",
                    "/certs/central.cert.pem",
                    "--key",
                    "/certs/central.key.pem",
                    "-t",
                    topic,
                    "-C",
                    "1",
                    "-W",
                    "8",
                ],
                timeout=60,
            )

        def pub(cert_stem: str, topic: str, payload: str) -> int:
            p = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "-v",
                    f"{tmp}:/certs:ro",
                    client_image,
                    "mosquitto_pub",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    host_port,
                    "--cafile",
                    "/certs/ca.pem",
                    "--cert",
                    f"/certs/{cert_stem}.cert.pem",
                    "--key",
                    f"/certs/{cert_stem}.key.pem",
                    "-t",
                    topic,
                    "-m",
                    payload,
                    "-q",
                    "1",
                ],
                timeout=60,
            )
            safe = payload.replace("/", "_")
            (art / f"pub_{cert_stem}_{safe}.err").write_text(
                (p.stderr or "") + (p.stdout or ""), encoding="utf-8"
            )
            return p.returncode

        # Case 1: own topic must be delivered to central.
        start_sub(sub_allow, topic_a, allow_payload)
        time.sleep(1.0)
        own_rc = pub("edge_a", topic_a, "own-ok")
        time.sleep(2.0)
        allow_logs = _run(["docker", "logs", sub_allow], timeout=15)
        allow_body = (allow_logs.stdout or "") + (allow_logs.stderr or "")
        allow_payload.write_text(allow_body, encoding="utf-8")
        (art / "allow_same_tenant.payload").write_text(allow_body, encoding="utf-8")
        _run(["docker", "rm", "-f", sub_allow], timeout=30)
        own_delivered = own_rc == 0 and "own-ok" in allow_body

        # Case 2: foreign topic must NOT be delivered (QoS0/1 pub may still exit 0).
        start_sub(sub_deny, topic_b, deny_payload)
        time.sleep(1.0)
        foreign_rc = pub("edge_a", topic_b, "foreign-deny")
        time.sleep(3.0)
        deny_logs = _run(["docker", "logs", sub_deny], timeout=15)
        deny_body = (deny_logs.stdout or "") + (deny_logs.stderr or "")
        deny_payload.write_text(deny_body, encoding="utf-8")
        (art / "deny_cross_tenant.payload").write_text(deny_body, encoding="utf-8")
        _run(["docker", "rm", "-f", sub_deny], timeout=30)
        foreign_leaked = "foreign-deny" in deny_body
        foreign_denied = not foreign_leaked

        result["own_topic"] = {
            "topic": topic_a,
            "rc": own_rc,
            "ok": own_delivered,
            "delivered": own_delivered,
        }
        result["foreign_topic"] = {
            "topic": topic_b,
            "rc": foreign_rc,
            "denied": foreign_denied,
            "leaked": foreign_leaked,
        }
        if own_delivered and foreign_denied:
            result["status"] = "PASS"
            result["detail"] = (
                "own mTLS publish delivered to central; "
                "foreign-tenant publish not delivered (ACL deny)"
            )
        else:
            result["status"] = "FAIL"
            result["detail"] = (
                f"own_delivered={own_delivered} foreign_denied={foreign_denied} "
                f"(own_rc={own_rc} foreign_rc={foreign_rc})"
            )
            blog = _run(["docker", "logs", name], timeout=15)
            (art / "broker.logs").write_text(
                (blog.stdout or "") + (blog.stderr or ""), encoding="utf-8"
            )
        return result
    finally:
        _run(["docker", "rm", "-f", name], timeout=30)
        _run(["docker", "rm", "-f", f"{name}-sub-allow"], timeout=30)
        _run(["docker", "rm", "-f", f"{name}-sub-deny"], timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)


def observe(
    *,
    out_dir: Path,
    require_live: bool,
    skip_live: bool,
    allow_skip_live: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Ensure committed fixture matches generator (static lint).
    write_acl(DEFAULT_ACL)

    try:
        image, acl_source = resolve_mqtt_acl_image()
    except ValueError as e:
        report = {
            "ok": False,
            "status": "FAIL",
            "soft_open": "mqtt-key-mode-tenant-acl",
            "folded": ["p2c-mqtt-acl-staging"],
            "started_at": now_iso(),
            "error": str(e),
            "checks": [],
        }
        (out_dir / "mqtt_acl_observer.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report

    if acl_source == "provisioner":
        acl_text = render_product_acl()
    else:
        acl_text = render_acl()
    (out_dir / "acl").write_text(acl_text, encoding="utf-8")

    checks = [
        check_key_mode_640(),
        check_acl_content(DEFAULT_ACL),
        {
            "check": "mqtt.acl.broker_image_policy",
            "status": "PASS",
            "image": image,
            "acl_source": acl_source,
            "detail": (
                "product openfdd-mqtt + provisioner ACL"
                if acl_source == "provisioner"
                else "fixture broker allowed via OPENFDD_MQTT_ACL_ALLOW_FIXTURE_BROKER"
            ),
        },
    ]

    live_status = "SKIPPED"
    if require_live and skip_live:
        checks.append(
            {
                "check": "mqtt.acl.live_broker_observer",
                "status": "FAIL",
                "detail": "--require-live and --skip-live are mutually exclusive",
            }
        )
        live_status = "FAIL"
    elif skip_live:
        checks.append(
            {
                "check": "mqtt.acl.live_broker_observer",
                "status": "SKIPPED",
                "detail": "skipped by --skip-live",
            }
        )
    elif docker_available():
        live = run_live_broker(acl_text, out_dir, image=image, acl_source=acl_source)
        checks.append(live)
        live_status = live["status"]
    else:
        detail = "docker unavailable; live broker optional"
        if require_live:
            checks.append(
                {
                    "check": "mqtt.acl.live_broker_observer",
                    "status": "BLOCKED",
                    "detail": detail,
                }
            )
            live_status = "BLOCKED"
        else:
            checks.append(
                {
                    "check": "mqtt.acl.live_broker_observer",
                    "status": "SKIPPED",
                    "detail": detail,
                }
            )
            live_status = "SKIPPED"

    hard = [
        c
        for c in checks
        if c["check"]
        not in ("mqtt.acl.live_broker_observer",)
    ]
    hard_ok = all(c["status"] == "PASS" for c in hard)
    live = next(
        (c for c in checks if c["check"] == "mqtt.acl.live_broker_observer"),
        None,
    )
    if live and live["status"] == "FAIL":
        overall = "FAIL"
        ok = False
    elif live and live["status"] == "ERROR":
        overall = "FAIL"
        ok = False
    elif live and live["status"] == "BLOCKED":
        overall = "BLOCKED"
        ok = False
    elif live and live["status"] == "SKIPPED" and not allow_skip_live:
        overall = "BLOCKED"
        ok = False
    elif hard_ok and live and (
        live["status"] == "PASS"
        or (live["status"] == "SKIPPED" and allow_skip_live and not require_live)
    ):
        overall = "PASS"
        ok = True
    else:
        overall = "FAIL"
        ok = False

    report = {
        "ok": ok,
        "status": overall,
        "soft_open": "mqtt-key-mode-tenant-acl",
        "folded": ["p2c-mqtt-acl-staging"],
        "started_at": now_iso(),
        "fixture_dir": str(FIXTURE_DIR.relative_to(ROOT)),
        "image": image,
        "acl_source": acl_source,
        "live_broker": live_status,
        "checks": checks,
    }
    (out_dir / "mqtt_acl_observer.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "reports" / "security" / "mqtt_acl_observer",
    )
    ap.add_argument(
        "--require-live",
        action="store_true",
        help="fail/BLOCKED when docker live broker cannot run",
    )
    ap.add_argument(
        "--skip-live",
        action="store_true",
        help="content + key-mode only (document live as SKIPPED)",
    )
    ap.add_argument(
        "--allow-skip-live",
        action="store_true",
        help="explicitly allow content-only PASS when live is SKIPPED",
    )
    args = ap.parse_args()
    report = observe(
        out_dir=args.out_dir,
        require_live=args.require_live,
        skip_live=args.skip_live,
        allow_skip_live=args.allow_skip_live,
    )
    print(json.dumps(report, indent=2))
    if report["status"] == "PASS":
        return 0
    if report["status"] == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
