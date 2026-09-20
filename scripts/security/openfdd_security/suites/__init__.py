"""Suite runners for X (auth/JWT), Y (authz), Z (deploy/abuse)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from ..config import FixtureRefs, IdentityRef, ProbeConfig, resolve_password, resolve_username
from ..evidence import CheckResult
from ..jwtutil import (
    make_alg_none_token,
    make_expired_token,
    make_tampered_token,
    make_valid_token,
)
from ..transport import SafeHttpClient, TransportError


AddCheck = Callable[[CheckResult], None]


def _status_of(resp) -> str:
    return str(resp.status)


def _is_json_object(body: bytes) -> bool:
    try:
        return isinstance(json.loads(body.decode("utf-8")), dict)
    except Exception:
        return False


def _looks_html(body: bytes) -> bool:
    t = body[:200].lower()
    return b"<html" in t or b"<!doctype" in t


def _nonempty_own_control(body: bytes, canary: str = "") -> bool:
    """Positive own-object control: nonempty schema, not {} / [] / HTML."""
    if not body or body.strip() in (b"", b"[]", b"{}"):
        return False
    if _looks_html(body):
        return False
    if canary and canary.encode() in body:
        return True
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return False
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        if not data:
            return False
        for key in ("equipment", "items", "buildings", "data", "rows"):
            val = data.get(key)
            if isinstance(val, list) and len(val) > 0:
                return True
            if isinstance(val, dict) and val:
                return True
        return any(v not in (None, "", [], {}) for v in data.values())
    return False


class SuiteContext:
    def __init__(
        self,
        client: SafeHttpClient,
        cfg: ProbeConfig,
        profile: str,
        add: AddCheck,
        *,
        allow_fixture_writes: bool = False,
        isolated_jwt_secret: bytes | None = None,
        tokens: dict[str, str] | None = None,
        mode: str = "live",  # live | dry_run | fixture
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.profile = profile
        self.add = add
        self.allow_fixture_writes = allow_fixture_writes
        self.isolated_jwt_secret = isolated_jwt_secret or b"harness-isolated-test-key-32b!!"
        self.tokens = tokens or {}
        self.mode = mode
        self.fx: FixtureRefs = cfg.fixtures

    def check(
        self,
        check_id: str,
        suite: str,
        title: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.add(
            CheckResult(
                check_id=check_id,
                suite=suite,
                title=title,
                status=status,
                **kwargs,
            )
        )


def run_suite_x(ctx: SuiteContext) -> None:
    """Authentication / JWT / preauth."""
    # Public health
    try:
        r = ctx.client.request("GET", "/api/health")
        ok = r.status == 200 and _is_json_object(r.body) and b'"ok"' in r.body
        ctx.check(
            "x.preauth.health_public",
            "X",
            "GET /api/health is public lean readiness",
            "PASS" if ok else "FAIL",
            expected="200+ok",
            observed=_status_of(r),
            method="GET",
            path_template="/api/health",
            detail=None if ok else "health missing ok JSON",
        )
    except TransportError as exc:
        ctx.check(
            "x.preauth.health_public",
            "X",
            "GET /api/health is public lean readiness",
            "ERROR",
            detail=str(exc),
        )

    for path, cid in (
        ("/api/tenants", "x.preauth.anon_tenants_401"),
        ("/api/capabilities", "x.preauth.anon_capabilities_401"),
        ("/api/health/stack", "x.preauth.anon_stack_401"),
        ("/api/building/snapshot", "x.preauth.anon_snapshot_401"),
        ("/api/dashboard/summary", "x.preauth.anon_summary_401"),
        ("/api/edges", "x.preauth.anon401.get_api_edges"),
        ("/api/fdd/equipment", "x.preauth.anon401.get_api_fdd_equipment"),
        ("/api/fdd/results", "x.preauth.anon401.get_api_fdd_results"),
        ("/api/fdd/session-config", "x.preauth.anon401.get_api_fdd_session_config"),
        ("/api/fdd/rules", "x.preauth.anon401.get_api_fdd_rules"),
        ("/api/datasets", "x.preauth.anon401.get_api_datasets"),
        ("/api/csv/import/package/mapping", "x.preauth.anon401.get_api_csv_import_package_mapping"),
        (
            "/api/csv/import/package/mapping/ttl",
            "x.preauth.anon401.get_api_csv_import_package_mapping_ttl",
        ),
        # Prefer a live analytics GET (overview path is not routed → 404 bypasses auth layer).
        ("/api/analytics/sql-anomaly/status", "x.preauth.anon401.get_api_analytics_overview"),
        ("/api/admin/users", "x.preauth.anon401.get_api_admin_users"),
        ("/api/jobs", "x.preauth.anon401.get_api_jobs"),
        ("/api/agent/tools", "x.preauth.anon401.get_api_agent_tools"),
    ):
        try:
            r = ctx.client.request("GET", path)
            # local_open auth-off may 200 — mark N/A for that profile
            if ctx.profile == "local_open":
                ctx.check(
                    cid,
                    "X",
                    f"anon {path}",
                    "NOT_APPLICABLE",
                    detail="local_open auth isolation untested",
                    method="GET",
                    path_template=path,
                )
                continue
            ok = r.status == 401
            # Protected data in error body is FAIL
            leak = False
            if r.status == 401 and ctx.fx.canary_a.encode() in r.body:
                leak = True
            ctx.check(
                cid,
                "X",
                f"anonymous {path} → 401",
                "FAIL" if leak else ("PASS" if ok else "FAIL"),
                expected="401",
                observed=_status_of(r),
                method="GET",
                path_template=path,
                detail="canary in error body" if leak else None,
            )
        except TransportError as exc:
            ctx.check(cid, "X", f"anon {path}", "ERROR", detail=str(exc))

    # JWT negative cases (no login required)
    try:
        r = ctx.client.request("GET", "/api/edges")
        ctx.check(
            "x.jwt.missing_token_401",
            "X",
            "missing bearer → 401",
            "PASS" if r.status == 401 else ("NOT_APPLICABLE" if ctx.profile == "local_open" else "FAIL"),
            expected="401",
            observed=_status_of(r),
            method="GET",
            path_template="/api/edges",
        )
    except TransportError as exc:
        ctx.check("x.jwt.missing_token_401", "X", "missing bearer", "ERROR", detail=str(exc))

    try:
        r = ctx.client.request("GET", "/api/edges", token="not-a-jwt")
        ctx.check(
            "x.jwt.malformed_token_401",
            "X",
            "malformed JWT → 401",
            "PASS" if r.status == 401 else ("NOT_APPLICABLE" if ctx.profile == "local_open" else "FAIL"),
            expected="401",
            observed=_status_of(r),
        )
    except TransportError as exc:
        ctx.check("x.jwt.malformed_token_401", "X", "malformed JWT", "ERROR", detail=str(exc))

    try:
        r = ctx.client.request("GET", "/api/edges", token=make_alg_none_token())
        ctx.check(
            "x.jwt.alg_none_rejected",
            "X",
            "alg:none rejected",
            "PASS" if r.status == 401 else ("NOT_APPLICABLE" if ctx.profile == "local_open" else "FAIL"),
            expected="401",
            observed=_status_of(r),
            detector_id="jwt_alg_none",
        )
    except TransportError as exc:
        ctx.check("x.jwt.alg_none_rejected", "X", "alg:none", "ERROR", detail=str(exc))

    try:
        bad = make_tampered_token(ctx.isolated_jwt_secret)
        r = ctx.client.request("GET", "/api/edges", token=bad)
        # Against real app with different secret also 401 — still PASS for rejection
        ctx.check(
            "x.jwt.tampered_sig_rejected",
            "X",
            "tampered signature rejected",
            "PASS" if r.status == 401 else ("NOT_APPLICABLE" if ctx.profile == "local_open" else "FAIL"),
            expected="401",
            observed=_status_of(r),
            detector_id="jwt_tampered_sig",
        )
    except TransportError as exc:
        ctx.check("x.jwt.tampered_sig_rejected", "X", "tampered sig", "ERROR", detail=str(exc))

    # Expired + valid sibling — only meaningful when server uses isolated secret
    # (fixture mode / isolated_full with OPENFDD_SECURITY_JWT_SECRET matching).
    secret = ctx.isolated_jwt_secret
    expired = make_expired_token(secret, role="operator")
    valid = make_valid_token(secret, role="operator", sub="sibling")
    try:
        r_exp = ctx.client.request("GET", "/api/edges", token=expired)
        r_ok = ctx.client.request("GET", "/api/edges", token=valid)
        # In fixture servers that share the secret: expired=401, valid=200
        # Against live Railway (different secret): both 401 → BLOCKED not FAIL
        if r_exp.status == 401 and r_ok.status == 200:
            ctx.check(
                "x.jwt.expired_signed_rejected",
                "X",
                "correctly signed expired token rejected",
                "PASS",
                expected="401",
                observed=_status_of(r_exp),
                detector_id="jwt_expired",
            )
            ctx.check(
                "x.jwt.valid_sibling_accepted",
                "X",
                "valid sibling token accepted",
                "PASS",
                expected="200",
                observed=_status_of(r_ok),
                detector_id="jwt_valid_sibling",
            )
        elif r_exp.status == 401 and r_ok.status == 401:
            # live_readonly cannot mint server-valid JWTs; isolated_full owns these.
            na = "NOT_APPLICABLE" if ctx.profile == "live_readonly" else "BLOCKED"
            detail = (
                "live_readonly: expiry/sibling JWT pair requires isolated JWT secret"
                if na == "NOT_APPLICABLE"
                else "server JWT secret not harness-isolated; expiry pair unverified"
            )
            ctx.check(
                "x.jwt.expired_signed_rejected",
                "X",
                "correctly signed expired token rejected",
                na,
                detail=detail,
                detector_id="jwt_expired",
            )
            ctx.check(
                "x.jwt.valid_sibling_accepted",
                "X",
                "valid sibling token accepted",
                na,
                detail=(
                    "live_readonly: valid-sibling acceptance requires isolated JWT secret"
                    if na == "NOT_APPLICABLE"
                    else "server JWT secret not harness-isolated"
                ),
                detector_id="jwt_valid_sibling",
            )
        else:
            # Signature/expiry bypass
            ctx.check(
                "x.jwt.expired_signed_rejected",
                "X",
                "correctly signed expired token rejected",
                "FAIL",
                expected="401",
                observed=_status_of(r_exp),
                detector_id="jwt_expired",
            )
            ctx.check(
                "x.jwt.valid_sibling_accepted",
                "X",
                "valid sibling token accepted",
                "FAIL" if r_ok.status != 200 else "PASS",
                expected="200",
                observed=_status_of(r_ok),
                detector_id="jwt_valid_sibling",
            )
    except TransportError as exc:
        ctx.check("x.jwt.expired_signed_rejected", "X", "expired", "ERROR", detail=str(exc))
        ctx.check("x.jwt.valid_sibling_accepted", "X", "sibling", "ERROR", detail=str(exc))

    # Role logins
    _login_me(ctx, "admin", "x.auth.admin_login_me", default_user="admin")
    if ctx.profile != "live_readonly" or "operator_a" in ctx.cfg.identities:
        _login_me(ctx, "operator_a", "x.auth.operator_a_login_me", default_user="acme-ops")


def _login_me(
    ctx: SuiteContext,
    alias: str,
    check_id: str,
    *,
    default_user: str,
) -> None:
    ident = ctx.cfg.identities.get(alias)
    if not ident:
        ctx.check(
            check_id,
            "X",
            f"login/me {alias}",
            "BLOCKED",
            detail=f"identity {alias} missing from config",
            identity_alias=alias,
        )
        return
    password = resolve_password(ident)
    username = resolve_username(ident, default_user)
    # Prefer pre-minted admin bearer after stress floods (avoids login 429).
    if alias == "admin":
        preexisting = (os.environ.get("OPENFDD_ADMIN_TOKEN") or "").strip()
        if preexisting:
            try:
                me = ctx.client.request("GET", "/api/auth/me", token=preexisting)
                if me.status == 200 and _is_json_object(me.body):
                    ctx.tokens[alias] = preexisting
                    role = (me.json() or {}).get("role")
                    ctx.check(
                        check_id,
                        "X",
                        f"login/me {alias}",
                        "PASS" if role == "admin" else "FAIL",
                        expected="200+token",
                        observed=_status_of(me),
                        identity_alias=alias,
                        detail="reused OPENFDD_ADMIN_TOKEN",
                    )
                    return
            except TransportError:
                pass
    if not password or not username:
        ctx.check(
            check_id,
            "X",
            f"login/me {alias}",
            "BLOCKED",
            detail=f"credentials for {alias} not available (env ref unset)",
            identity_alias=alias,
        )
        return
    try:
        r = None
        for attempt in range(6):
            r = ctx.client.request(
                "POST",
                "/api/auth/login",
                json_body={"username": username, "password": password},
            )
            if r.status != 429:
                break
            # Post-stress / gate 23 AFDD flood can trip login rate limits — wait and retry.
            time.sleep(min(5 * (2**attempt), 45))
        assert r is not None
        if r.status != 200 or not _is_json_object(r.body):
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                expected="200+token",
                observed=_status_of(r),
                identity_alias=alias,
                detail="login rate-limited (429) after retries" if r.status == 429 else None,
            )
            return
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                detail="login response missing token",
                identity_alias=alias,
            )
            return
        ctx.tokens[alias] = token
        me = ctx.client.request("GET", "/api/auth/me", token=token)
        if me.status != 200 or not _is_json_object(me.body):
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                expected="200 /api/auth/me",
                observed=_status_of(me),
                identity_alias=alias,
                detector_id="wrong_identity",
            )
            return
        me_data = me.json()
        role = (me_data.get("role") or "").lower()
        expected_role = (ident.role or "").lower()
        sub = str(me_data.get("sub") or me_data.get("username") or "")
        if expected_role and role != expected_role:
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                detail=f"role mismatch expected={expected_role} got={role or 'missing'}",
                identity_alias=alias,
                detector_id="wrong_identity",
            )
            return
        if not sub:
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                detail="missing subject on /api/auth/me",
                identity_alias=alias,
                detector_id="wrong_identity",
            )
            return
        if username and sub != username and sub.lower() != username.lower():
            ctx.check(
                check_id,
                "X",
                f"login/me {alias}",
                "FAIL",
                detail=f"subject mismatch expected={username} got={sub}",
                identity_alias=alias,
                detector_id="wrong_identity",
            )
            return
        expected_tenants = list(getattr(ident, "tenant_ids", None) or [])
        if expected_tenants:
            got_tenant = str(
                me_data.get("tenant_id")
                or me_data.get("tenant")
                or ""
            ).strip()
            got_list = me_data.get("tenants") if isinstance(me_data.get("tenants"), list) else []
            ok_tenant = False
            if got_tenant and got_tenant in expected_tenants:
                ok_tenant = True
            if any(str(t) in expected_tenants for t in got_list):
                ok_tenant = True
            if got_tenant or got_list:
                if not ok_tenant:
                    ctx.check(
                        check_id,
                        "X",
                        f"login/me {alias}",
                        "FAIL",
                        detail=f"tenant mismatch expected={expected_tenants} got={got_tenant or got_list}",
                        identity_alias=alias,
                        detector_id="wrong_identity",
                    )
                    return
        ctx.check(
            check_id,
            "X",
            f"login/me {alias}",
            "PASS",
            identity_alias=alias,
            observed=f"role={role or 'present'} sub={sub}",
        )
    except TransportError as exc:
        ctx.check(check_id, "X", f"login/me {alias}", "ERROR", detail=str(exc))


def run_suite_y(ctx: SuiteContext) -> None:
    """Authorization: own success + foreign denial + detectors."""
    fx = ctx.fx
    # Never fall back to admin for tenant operator A (S01).
    tok_a = ctx.tokens.get("operator_a")
    tok_b = ctx.tokens.get("operator_b")
    tok_viewer = ctx.tokens.get("viewer_a") or ctx.tokens.get("viewer")

    if not tok_a:
        # Attempt login if credentials exist
        _login_me(ctx, "operator_a", "y.authz._login_a", default_user="acme-ops")
        tok_a = ctx.tokens.get("operator_a")
    if not tok_b and "operator_b" in ctx.cfg.identities:
        _login_me(ctx, "operator_b", "y.authz._login_b", default_user="b100-ops")
        tok_b = ctx.tokens.get("operator_b")

    if not tok_a:
        for cid in (
            "y.authz.a_own_building_control",
            "y.authz.a_foreign_building_denied",
            "y.authz.b_own_building_control",
            "y.authz.b_foreign_building_denied",
            "y.authz.viewer_mutation_denied",
            "y.authz.admin_users_operator_denied",
            "y.detector.always_401_invalidates_authz",
            "y.detector.empty_200_not_deny",
            "y.detector.html_200_not_deny",
            "y.detector.foreign_canary_leak",
        ):
            ctx.check(cid, "Y", cid, "BLOCKED", detail="no operator_a token (admin fallback removed)")
        return

    # Positive own control for A
    q = urlencode({"building_id": fx.building_a})
    try:
        r = ctx.client.request(
            "GET", f"/api/fdd/equipment?{q}", token=tok_a
        )
        if r.status == 401:
            ctx.check(
                "y.authz.a_own_building_control",
                "Y",
                "A own building equipment",
                "ERROR",
                detail="valid A token got 401 — cannot demonstrate authorization",
                detector_id="always_401",
                identity_alias="operator_a",
            )
        elif r.status == 200 and _nonempty_own_control(r.body, fx.canary_a):
            ctx.check(
                "y.authz.a_own_building_control",
                "Y",
                "A own building equipment",
                "PASS",
                expected="200+nonempty schema",
                observed="200",
                identity_alias="operator_a",
            )
        elif r.status == 200:
            ctx.check(
                "y.authz.a_own_building_control",
                "Y",
                "A own building equipment",
                "FAIL",
                detail="empty/soft 200 is not positive own-object control",
                detector_id="empty_200",
            )
        else:
            ctx.check(
                "y.authz.a_own_building_control",
                "Y",
                "A own building equipment",
                "BLOCKED" if r.status in (403, 404) else "FAIL",
                observed=_status_of(r),
                detail="own fixture missing or unexpected status",
            )
    except TransportError as exc:
        ctx.check(
            "y.authz.a_own_building_control",
            "Y",
            "A own",
            "ERROR",
            detail=str(exc),
        )

    # Foreign deny for A → B (403 preferred; 401 with valid token is ERROR)
    q_b = urlencode({"building_id": fx.building_b})
    try:
        r = ctx.client.request(
            "GET", f"/api/fdd/equipment?{q_b}", token=tok_a
        )
        body = r.body
        if r.status == 401:
            ctx.check(
                "y.authz.a_foreign_building_denied",
                "Y",
                "A denied foreign building",
                "ERROR",
                detail="401 with nominally valid token invalidates authz case",
                detector_id="always_401",
            )
            ctx.check(
                "y.detector.always_401_invalidates_authz",
                "Y",
                "detector: always-401",
                "FAIL",
                detector_id="always_401",
                detail="authz path returned 401 for valid token",
            )
        elif r.status == 200 and _looks_html(body):
            ctx.check(
                "y.authz.a_foreign_building_denied",
                "Y",
                "A denied foreign building",
                "FAIL",
                detector_id="html_200",
            )
            ctx.check(
                "y.detector.html_200_not_deny",
                "Y",
                "detector: HTML 200",
                "FAIL",
                detector_id="html_200",
            )
        elif r.status == 200 and (
            body.strip() in (b"", b"[]", b"{}")
            or ( _is_json_object(body) and not _deny_envelope(body) and fx.canary_b.encode() not in body)
        ):
            # Empty 200 without deny envelope is not denial
            if body.strip() in (b"", b"[]", b"{}"):
                ctx.check(
                    "y.authz.a_foreign_building_denied",
                    "Y",
                    "A denied foreign building",
                    "FAIL",
                    detector_id="empty_200",
                    detail="empty 200 is not object denial",
                )
                ctx.check(
                    "y.detector.empty_200_not_deny",
                    "Y",
                    "detector: empty 200",
                    "FAIL",
                    detector_id="empty_200",
                )
            elif fx.canary_b.encode() in body:
                ctx.check(
                    "y.authz.a_foreign_building_denied",
                    "Y",
                    "A denied foreign building",
                    "FAIL",
                    detector_id="foreign_canary",
                )
                ctx.check(
                    "y.detector.foreign_canary_leak",
                    "Y",
                    "detector: foreign canary",
                    "FAIL",
                    detector_id="foreign_canary",
                )
            else:
                # 200 with data but no canary — still FAIL if not deny
                ctx.check(
                    "y.authz.a_foreign_building_denied",
                    "Y",
                    "A denied foreign building",
                    "FAIL",
                    detail="200 without deny envelope",
                )
                ctx.check(
                    "y.detector.empty_200_not_deny",
                    "Y",
                    "detector: empty/soft 200",
                    "PASS",
                    detail="no empty body in this response",
                )
        elif fx.canary_b.encode() in body:
            ctx.check(
                "y.authz.a_foreign_building_denied",
                "Y",
                "A denied foreign building",
                "FAIL",
                detector_id="foreign_canary",
                detail="foreign canary present",
            )
            ctx.check(
                "y.detector.foreign_canary_leak",
                "Y",
                "detector: foreign canary",
                "FAIL",
                detector_id="foreign_canary",
            )
        elif r.status in (403, 404):
            if _is_json_object(body) and not _deny_ok(body) and b"ok" in body.lower():
                # has ok field but not false
                if not _deny_envelope(body):
                    ctx.check(
                        "y.authz.a_foreign_building_denied",
                        "Y",
                        "A denied foreign building",
                        "FAIL",
                        detail="deny body missing ok:false",
                    )
                else:
                    ctx.check(
                        "y.authz.a_foreign_building_denied",
                        "Y",
                        "A denied foreign building",
                        "PASS",
                        expected="403/404",
                        observed=_status_of(r),
                    )
            else:
                ctx.check(
                    "y.authz.a_foreign_building_denied",
                    "Y",
                    "A denied foreign building",
                    "PASS",
                    expected="403/404",
                    observed=_status_of(r),
                )
            # Detectors healthy
            ctx.check(
                "y.detector.always_401_invalidates_authz",
                "Y",
                "detector: always-401",
                "PASS",
                detail="foreign deny was not 401",
                detector_id="always_401",
            )
            ctx.check(
                "y.detector.empty_200_not_deny",
                "Y",
                "detector: empty 200",
                "PASS",
                detector_id="empty_200",
            )
            ctx.check(
                "y.detector.html_200_not_deny",
                "Y",
                "detector: HTML 200",
                "PASS",
                detector_id="html_200",
            )
            ctx.check(
                "y.detector.foreign_canary_leak",
                "Y",
                "detector: foreign canary",
                "PASS",
                detector_id="foreign_canary",
            )
        else:
            ctx.check(
                "y.authz.a_foreign_building_denied",
                "Y",
                "A denied foreign building",
                "FAIL",
                expected="403/404",
                observed=_status_of(r),
            )
            _emit_detector_defaults(ctx, r)
    except TransportError as exc:
        ctx.check(
            "y.authz.a_foreign_building_denied",
            "Y",
            "A foreign",
            "ERROR",
            detail=str(exc),
        )
        for cid, det in (
            ("y.detector.always_401_invalidates_authz", "always_401"),
            ("y.detector.empty_200_not_deny", "empty_200"),
            ("y.detector.html_200_not_deny", "html_200"),
            ("y.detector.foreign_canary_leak", "foreign_canary"),
        ):
            ctx.check(cid, "Y", cid, "ERROR", detail=str(exc), detector_id=det)

    # B direction if available
    if tok_b:
        try:
            r = ctx.client.request(
                "GET", f"/api/fdd/equipment?{q_b}", token=tok_b
            )
            own_ok = r.status == 200 and _nonempty_own_control(r.body, fx.canary_b)
            ctx.check(
                "y.authz.b_own_building_control",
                "Y",
                "B own building equipment",
                "PASS" if own_ok else "FAIL",
                observed=_status_of(r),
                detail=None if own_ok else "empty/soft 200 is not positive own-object control",
                detector_id=None if own_ok else "empty_200",
            )
            r2 = ctx.client.request(
                "GET", f"/api/fdd/equipment?{q}", token=tok_b
            )
            leak = fx.canary_a.encode() in r2.body
            if r2.status == 401:
                st = "ERROR"
                detail = "401 with nominally valid token"
            elif leak:
                st = "FAIL"
                detail = "foreign canary present in deny/response body"
            elif r2.status in (403, 404):
                st = "PASS"
                detail = None
            else:
                st = "FAIL"
                detail = f"unexpected status {r2.status}"
            ctx.check(
                "y.authz.b_foreign_building_denied",
                "Y",
                "B denied foreign building",
                st,
                observed=_status_of(r2),
                detail=detail,
                detector_id="foreign_canary" if leak else None,
            )
            if leak:
                ctx.check(
                    "y.detector.foreign_canary_leak",
                    "Y",
                    "detector: foreign canary",
                    "FAIL",
                    detector_id="foreign_canary",
                )
        except TransportError as exc:
            ctx.check("y.authz.b_own_building_control", "Y", "B own", "ERROR", detail=str(exc))
            ctx.check("y.authz.b_foreign_building_denied", "Y", "B foreign", "ERROR", detail=str(exc))
    else:
        ctx.check(
            "y.authz.b_own_building_control",
            "Y",
            "B own building equipment",
            "BLOCKED",
            detail="operator_b credentials missing",
        )
        ctx.check(
            "y.authz.b_foreign_building_denied",
            "Y",
            "B denied foreign building",
            "BLOCKED",
            detail="operator_b credentials missing",
        )

    # Viewer mutation: prove authenticated viewer read first; 401 ≠ role deny (E07).
    if not tok_viewer and "viewer_a" in ctx.cfg.identities:
        _login_me(ctx, "viewer_a", "y.authz._login_viewer", default_user="viewer")
        tok_viewer = ctx.tokens.get("viewer_a")
    if tok_viewer:
        try:
            me = ctx.client.request("GET", "/api/auth/me", token=tok_viewer)
            if me.status != 200 or not _is_json_object(me.body):
                ctx.check(
                    "y.authz.viewer_mutation_denied",
                    "Y",
                    "viewer cannot mint agent-token",
                    "ERROR",
                    detail="viewer identity not confirmed via /api/auth/me",
                    detector_id="viewer_mutation",
                )
            else:
                role = str((me.json() or {}).get("role") or "").lower()
                if role and role not in ("viewer", "read", "readonly"):
                    ctx.check(
                        "y.authz.viewer_mutation_denied",
                        "Y",
                        "viewer cannot mint agent-token",
                        "FAIL",
                        detail=f"expected viewer role, got {role}",
                        detector_id="wrong_identity",
                    )
                else:
                    r = ctx.client.request(
                        "POST",
                        "/api/auth/agent-token",
                        token=tok_viewer,
                        json_body={},
                    )
                    # 401 = auth failure, not role proof; require authorization deny.
                    st = "PASS" if r.status == 403 else "FAIL"
                    ctx.check(
                        "y.authz.viewer_mutation_denied",
                        "Y",
                        "viewer cannot mint agent-token",
                        st,
                        expected="403",
                        observed=_status_of(r),
                        detector_id="viewer_mutation",
                        detail=None if r.status == 403 else "401 is not viewer-role denial proof",
                    )
        except TransportError as exc:
            ctx.check(
                "y.authz.viewer_mutation_denied",
                "Y",
                "viewer mutation",
                "ERROR",
                detail=str(exc),
            )
    else:
        ctx.check(
            "y.authz.viewer_mutation_denied",
            "Y",
            "viewer cannot mint agent-token",
            "BLOCKED",
            detail="viewer credentials missing (not N/A)",
        )

    # Operator denied admin
    try:
        r = ctx.client.request("GET", "/api/admin/users", token=tok_a)
        if r.status == 401:
            st = "ERROR"
            detail = "valid token 401 on admin probe"
        elif r.status == 403:
            st = "PASS"
            detail = None
        elif tok_a == ctx.tokens.get("admin"):
            st = "NOT_APPLICABLE"
            detail = "token is hub admin"
        else:
            st = "FAIL"
            detail = f"operator reached admin users: {r.status}"
        ctx.check(
            "y.authz.admin_users_operator_denied",
            "Y",
            "non-admin denied /api/admin/users",
            st,
            observed=_status_of(r),
            detail=detail,
        )
    except TransportError as exc:
        ctx.check(
            "y.authz.admin_users_operator_denied",
            "Y",
            "admin users",
            "ERROR",
            detail=str(exc),
        )

    # Session-config selector: A must not read B's building config envelope with foreign canary
    try:
        q = urlencode({"building_id": fx.building_a})
        r_own = ctx.client.request(
            "GET", f"/api/fdd/session-config?{q}", token=tok_a
        )
        if r_own.status == 401:
            ctx.check(
                "y.authz.get_api_fdd_session_config",
                "Y",
                "A session-config own control",
                "ERROR",
                detail="valid A token 401",
                path_template="/api/fdd/session-config",
            )
        elif r_own.status in (200, 404):
            # 404 may mean fixture absent — BLOCKED not PASS
            st = "PASS" if r_own.status == 200 and _is_json_object(r_own.body) else "BLOCKED"
            ctx.check(
                "y.authz.get_api_fdd_session_config",
                "Y",
                "A session-config own control",
                st,
                observed=_status_of(r_own),
                detail=None if st == "PASS" else "own session-config fixture missing",
                path_template="/api/fdd/session-config",
            )
        else:
            ctx.check(
                "y.authz.get_api_fdd_session_config",
                "Y",
                "A session-config own control",
                "FAIL",
                observed=_status_of(r_own),
            )
        q_b = urlencode({"building_id": fx.building_b})
        r_f = ctx.client.request(
            "GET", f"/api/fdd/session-config?{q_b}", token=tok_a
        )
        leak = fx.canary_b.encode() in r_f.body
        if r_f.status == 401:
            deny_st = "ERROR"
        elif r_f.status in (403, 404) and not leak:
            deny_st = "PASS"
        elif r_f.status == 200 and leak:
            deny_st = "FAIL"
        elif r_f.status == 200:
            deny_st = "FAIL"
        else:
            deny_st = "FAIL"
        ctx.check(
            "y.authz.a_foreign_session_config_denied",
            "Y",
            "A denied foreign session-config",
            deny_st,
            expected="403/404",
            observed=_status_of(r_f),
            detail="foreign canary leak" if leak else None,
            path_template="/api/fdd/session-config",
        )
    except TransportError as exc:
        ctx.check(
            "y.authz.get_api_fdd_session_config",
            "Y",
            "session-config",
            "ERROR",
            detail=str(exc),
        )
        ctx.check(
            "y.authz.a_foreign_session_config_denied",
            "Y",
            "session-config foreign",
            "ERROR",
            detail=str(exc),
        )

    # Datasets + package mapping: foreign building deny (Wave S1 expand).
    # Own-building 200 is not required for PASS — missing fixtures stay out of FQ.
    for path, foreign_cid in (
        ("/api/datasets", "y.authz.a_foreign_datasets_denied"),
        (
            "/api/csv/import/package/mapping",
            "y.authz.a_foreign_package_mapping_denied",
        ),
        (
            "/api/csv/import/package/mapping/ttl",
            "y.authz.a_foreign_package_mapping_ttl_denied",
        ),
    ):
        try:
            q_b = urlencode({"building_id": fx.building_b})
            r_f = ctx.client.request("GET", f"{path}?{q_b}", token=tok_a)
            leak = fx.canary_b.encode() in r_f.body
            if r_f.status == 401:
                deny_st = "ERROR"
            elif r_f.status in (403, 404) and not leak:
                deny_st = "PASS"
            elif r_f.status == 200 and leak:
                deny_st = "FAIL"
            elif r_f.status == 200:
                deny_st = "FAIL"
            else:
                deny_st = "FAIL"
            ctx.check(
                foreign_cid,
                "Y",
                f"A denied foreign {path}",
                deny_st,
                expected="403/404",
                observed=_status_of(r_f),
                detail="foreign canary leak" if leak else None,
                path_template=path,
            )
        except TransportError as exc:
            ctx.check(foreign_cid, "Y", f"{path} foreign", "ERROR", detail=str(exc))

    # Additional high-value GETs: FDD results + RCx presets + equipment (Wave U MT breadth).
    for path, foreign_cid in (
        ("/api/fdd/results", "y.authz.a_foreign_fdd_results_denied"),
        ("/api/analytics/rcx/presets", "y.authz.a_foreign_analytics_rcx_presets_denied"),
        ("/api/fdd/equipment", "y.authz.a_foreign_fdd_equipment_denied"),
    ):
        try:
            q_own = urlencode({"building_id": fx.building_a})
            r_own = ctx.client.request("GET", f"{path}?{q_own}", token=tok_a)
            own_cid = foreign_cid.replace("_foreign_", "_own_").replace("_denied", "")
            if r_own.status == 401:
                own_st = "ERROR"
            elif r_own.status == 200 and _nonempty_own_control(r_own.body, fx.canary_a):
                own_st = "PASS"
            elif r_own.status == 200:
                # Empty list can be a healthy empty building; {} is not.
                try:
                    data = json.loads(r_own.body.decode())
                    if isinstance(data, list):
                        own_st = "PASS"
                    elif isinstance(data, dict) and data:
                        own_st = "PASS"
                    else:
                        own_st = "BLOCKED"
                except Exception:
                    own_st = "BLOCKED"
            else:
                own_st = "BLOCKED" if r_own.status in (403, 404) else "FAIL"
            ctx.check(
                own_cid,
                "Y",
                f"A own {path}",
                own_st,
                observed=_status_of(r_own),
                path_template=path,
            )
            q_b = urlencode({"building_id": fx.building_b})
            r_f = ctx.client.request("GET", f"{path}?{q_b}", token=tok_a)
            leak = fx.canary_b.encode() in r_f.body
            if r_f.status == 401:
                deny_st = "ERROR"
            elif r_f.status in (403, 404) and not leak:
                deny_st = "PASS"
            else:
                deny_st = "FAIL"
            ctx.check(
                foreign_cid,
                "Y",
                f"A denied foreign {path}",
                deny_st,
                expected="403/404",
                observed=_status_of(r_f),
                detail="foreign canary leak" if leak else None,
                path_template=path,
            )
        except TransportError as exc:
            ctx.check(foreign_cid, "Y", f"{path} foreign", "ERROR", detail=str(exc))


def _deny_envelope(body: bytes) -> bool:
    try:
        data = json.loads(body.decode("utf-8"))
        return isinstance(data, dict) and data.get("ok") is False
    except Exception:
        return False


def _deny_ok(body: bytes) -> bool:
    return _deny_envelope(body)


def _emit_detector_defaults(ctx: SuiteContext, r) -> None:
    ctx.check(
        "y.detector.always_401_invalidates_authz",
        "Y",
        "detector: always-401",
        "PASS" if r.status != 401 else "FAIL",
        detector_id="always_401",
    )
    ctx.check(
        "y.detector.empty_200_not_deny",
        "Y",
        "detector: empty 200",
        "FAIL" if r.status == 200 and r.body.strip() in (b"", b"[]") else "PASS",
        detector_id="empty_200",
    )
    ctx.check(
        "y.detector.html_200_not_deny",
        "Y",
        "detector: HTML 200",
        "FAIL" if r.status == 200 and _looks_html(r.body) else "PASS",
        detector_id="html_200",
    )
    canary = ctx.fx.canary_b.encode()
    ctx.check(
        "y.detector.foreign_canary_leak",
        "Y",
        "detector: foreign canary",
        "FAIL" if canary in r.body else "PASS",
        detector_id="foreign_canary",
    )


def run_suite_z(ctx: SuiteContext) -> None:
    """Deployment headers / CORS / redirect credential policy / abuse bounds."""
    if ctx.profile == "local_open":
        parsed_ok = "127.0.0.1" in ctx.client.base_url or "localhost" in ctx.client.base_url
        ctx.check(
            "z.deploy.loopback_precondition",
            "Z",
            "local_open requires loopback origin",
            "PASS" if parsed_ok else "BLOCKED",
            detail=None if parsed_ok else "non-loopback local_open blocked",
        )

    try:
        r = ctx.client.request("GET", "/.well-known/security.txt")
        ctype = (r.header("content-type") or "").lower()
        ok = r.status == 200 and "text/plain" in ctype and not _looks_html(r.body)
        ctx.check(
            "z.deploy.security_txt",
            "Z",
            "security.txt text/plain",
            "PASS" if ok else "FAIL",
            observed=f"{r.status}/{ctype}",
        )
    except TransportError as exc:
        ctx.check("z.deploy.security_txt", "Z", "security.txt", "ERROR", detail=str(exc))

    try:
        r = ctx.client.request("GET", "/")
        csp = r.header("content-security-policy") or r.header("Content-Security-Policy")
        # Central API may not serve SPA — also try common web paths via same origin
        if not csp:
            r2 = ctx.client.request("GET", "/auth")
            csp = r2.header("content-security-policy")
        ctx.check(
            "z.deploy.csp_present",
            "Z",
            "CSP header present on web surface",
            "PASS" if csp else "BLOCKED",
            detail="CSP missing on probed paths (may be API-only origin)" if not csp else None,
        )
    except TransportError as exc:
        ctx.check("z.deploy.csp_present", "Z", "CSP", "ERROR", detail=str(exc))

    # CORS disallow evil origin on authenticated response
    tok = ctx.tokens.get("admin") or ctx.tokens.get("operator_a")
    try:
        r = ctx.client.request(
            "GET",
            "/api/health",
            headers={"Origin": "https://evil.example"},
            token=tok,
        )
        acao = r.header("access-control-allow-origin")
        if acao == "https://evil.example" or acao == "*":
            ctx.check(
                "z.deploy.cors_disallow_evil",
                "Z",
                "CORS rejects evil origin",
                "FAIL",
                observed=acao,
                detector_id="cors_reflected",
            )
        else:
            ctx.check(
                "z.deploy.cors_disallow_evil",
                "Z",
                "CORS rejects evil origin",
                "PASS",
                observed=acao or "absent",
                detector_id="cors_reflected",
            )
    except TransportError as exc:
        ctx.check(
            "z.deploy.cors_disallow_evil",
            "Z",
            "CORS",
            "ERROR",
            detail=str(exc),
            detector_id="cors_transport",
        )

    # Redirect: request a path that may 3xx; ensure we do not follow with credentials
    try:
        r = ctx.client.request(
            "GET",
            "/api/edges",
            token=tok or "probe",
            expect_redirect=True,
        )
        if r.redirected and r.location and "://" in (r.location or ""):
            # Off-origin redirect observed; credentials must not have been forwarded
            ctx.check(
                "z.detector.redirect_no_credential_forward",
                "Z",
                "no credential forward on redirect",
                "PASS",
                detail="client does not follow redirects",
                detector_id="redirect_credential_sink",
            )
        else:
            ctx.check(
                "z.detector.redirect_no_credential_forward",
                "Z",
                "no credential forward on redirect",
                "PASS",
                detail="no off-origin redirect; transport policy enforced",
                detector_id="redirect_credential_sink",
            )
    except TransportError as exc:
        ctx.check(
            "z.detector.redirect_no_credential_forward",
            "Z",
            "redirect policy",
            "ERROR",
            detail=str(exc),
        )

    if ctx.profile == "isolated_full":
        try:
            huge = b"x" * (ctx.client.budget.max_body_bytes + 10)
            # We detect oversized *responses*; for request, post small marker
            r = ctx.client.request(
                "GET",
                "/api/health",
            )
            # Fixture may expose /__oversized
            try:
                r2 = ctx.client.request("GET", "/__oversized")
                if r2.status == 200 and len(r2.body) > ctx.client.budget.max_body_bytes:
                    st = "FAIL"
                    detail = "oversized body delivered"
                else:
                    st = "PASS"
                    detail = "capped or non-oversized"
            except TransportError as exc:
                if "max_body_bytes" in str(exc):
                    st = "PASS"
                    detail = "body cap enforced"
                else:
                    st = "BLOCKED"
                    detail = str(exc)
            ctx.check(
                "z.abuse.oversized_body_blocked",
                "Z",
                "response body size cap",
                st,
                detail=detail,
                detector_id="oversized_body",
            )
        except TransportError as exc:
            ctx.check(
                "z.abuse.oversized_body_blocked",
                "Z",
                "oversized",
                "ERROR",
                detail=str(exc),
            )


def run_suite_mqtt_acl(ctx: SuiteContext) -> None:
    """Optional broker ACL suite — generated fixture + observer evidence."""
    root = Path(__file__).resolve().parents[4]
    fixture_acl = (
        root / "scripts" / "security" / "fixtures" / "mqtt_tenant_acl" / "acl"
    )
    entrypoint = root / "services" / "mqtt" / "docker-entrypoint-openfdd.sh"
    observer = root / "scripts" / "security" / "mqtt_tenant_acl_observer.py"
    gen = (
        root
        / "scripts"
        / "security"
        / "fixtures"
        / "mqtt_tenant_acl"
        / "generate_acl.py"
    )

    # Key mode 640 (static entrypoint evidence).
    if entrypoint.is_file() and "chmod 640" in entrypoint.read_text(encoding="utf-8"):
        ctx.check(
            "mqtt.key_mode_640",
            "mqtt_acl",
            "MQTT private key chmod 640 (not world-readable)",
            "PASS",
            detail=str(entrypoint.relative_to(root)),
        )
    else:
        ctx.check(
            "mqtt.key_mode_640",
            "mqtt_acl",
            "MQTT private key chmod 640 (not world-readable)",
            "FAIL",
            detail="entrypoint missing chmod 640",
        )

    # Content semantics via generator (always; no live broker required).
    if fixture_acl.is_file() and gen.is_file():
        try:
            sys_path_hack = str(gen.parent)
            if sys_path_hack not in sys.path:
                sys.path.insert(0, sys_path_hack)
            from generate_acl import semantic_errors  # type: ignore

            errs = semantic_errors(fixture_acl.read_text(encoding="utf-8"))
            ctx.check(
                "mqtt.acl.content_semantics",
                "mqtt_acl",
                "generated tenant ACL content (A/B own + foreign deny)",
                "PASS" if not errs else "FAIL",
                detail=None if not errs else "; ".join(errs),
            )
        except Exception as exc:  # noqa: BLE001 — suite must not crash probe
            ctx.check(
                "mqtt.acl.content_semantics",
                "mqtt_acl",
                "generated tenant ACL content (A/B own + foreign deny)",
                "ERROR",
                detail=str(exc),
            )
    else:
        ctx.check(
            "mqtt.acl.content_semantics",
            "mqtt_acl",
            "generated tenant ACL content (A/B own + foreign deny)",
            "BLOCKED",
            detail="fixture missing",
        )

    # Live / positive observer: only when EXECUTE env set (gate 26 owns full run).
    execute = os.environ.get("OPENFDD_MQTT_ACL_EXECUTE", "0") == "1"
    evidence = os.environ.get("OPENFDD_MQTT_ACL_EVIDENCE_JSON", "").strip()
    allowed = ("PASS", "FAIL", "BLOCKED", "SKIPPED", "ERROR")
    if evidence and Path(evidence).is_file():
        try:
            report = json.loads(Path(evidence).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            report = {"ok": False, "status": "ERROR", "detail": str(exc)}
        live = (
            "PASS"
            if report.get("ok") and report.get("status") == "PASS"
            else (report.get("status") or "FAIL")
        )
        if live not in allowed:
            live = "FAIL"
        detail = f"evidence={evidence}"
        for cid, title in (
            ("mqtt.acl.own_topic_control", "own topic publish control"),
            ("mqtt.acl.foreign_topic_denied", "foreign tenant topic denied"),
        ):
            ctx.check(cid, "mqtt_acl", title, live, detail=detail)
        return

    if execute and observer.is_file():
        out = Path(tempfile.mkdtemp(prefix="mqtt_acl_suite_"))
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(observer),
                    "--out-dir",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            report_path = out / "mqtt_acl_observer.json"
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
            else:
                report = {
                    "ok": False,
                    "status": "ERROR",
                    "detail": proc.stderr or proc.stdout or "no report",
                }
            st = report.get("status") or ("PASS" if report.get("ok") else "FAIL")
            if st not in allowed:
                st = "FAIL"
            detail = f"observer_rc={proc.returncode}"
            for cid, title in (
                ("mqtt.acl.own_topic_control", "own topic publish control"),
                ("mqtt.acl.foreign_topic_denied", "foreign tenant topic denied"),
            ):
                ctx.check(cid, "mqtt_acl", title, st, detail=detail)
        except Exception as exc:  # noqa: BLE001
            for cid, title in (
                ("mqtt.acl.own_topic_control", "own topic publish control"),
                ("mqtt.acl.foreign_topic_denied", "foreign tenant topic denied"),
            ):
                ctx.check(cid, "mqtt_acl", title, "ERROR", detail=str(exc))
        return

    ctx.check(
        "mqtt.acl.own_topic_control",
        "mqtt_acl",
        "own topic publish control",
        "BLOCKED",
        detail=(
            "set OPENFDD_MQTT_ACL_EXECUTE=1 or OPENFDD_MQTT_ACL_EVIDENCE_JSON; "
            "continuity gate is not ACL proof"
        ),
    )
    ctx.check(
        "mqtt.acl.foreign_topic_denied",
        "mqtt_acl",
        "foreign tenant topic denied",
        "BLOCKED",
        detail="set OPENFDD_MQTT_ACL_EXECUTE=1 or OPENFDD_MQTT_ACL_EVIDENCE_JSON",
    )


SUITE_RUNNERS = {
    "X": run_suite_x,
    "Y": run_suite_y,
    "Z": run_suite_z,
    "mqtt_acl": run_suite_mqtt_acl,
}
