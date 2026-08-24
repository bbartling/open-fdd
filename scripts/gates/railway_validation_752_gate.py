import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
checks = []

def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {label}")
    checks.append(bool(cond))

validation_path = os.path.join(ROOT, "docs/operations/RAILWAY_VALIDATION_752.md")
security_ops_path = os.path.join(ROOT, "docs/operations/security.md")

check("validation doc exists", os.path.isfile(validation_path))
check("railway deployment doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/RAILWAY_DEPLOYMENT.md")))
check("standalone compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.standalone.yml")))
check("react compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.react.yml")))
check("security doc exists", os.path.isfile(security_ops_path))
check("SECURITY.md exists", os.path.isfile(os.path.join(ROOT, "SECURITY.md")))
check("operations index exists", os.path.isfile(os.path.join(ROOT, "docs/operations/index.md")))

security_lower = ""
if os.path.isfile(security_ops_path):
    security_lower = open(security_ops_path, "r", encoding="utf-8").read().lower()

check(
    "security policy evidence is LAN/VPN local-first",
    "local-first" in security_lower and "lan" in security_lower and "vpn" in security_lower and "not internet-ready" in security_lower,
)
check(
    "security policy documents deployment-secret controls",
    "openfdd_jwt_secret" in security_lower and "openfdd_admin_password" in security_lower and ("never log" in security_lower or "without secrets" in security_lower),
)

if os.path.isfile(validation_path):
    text = open(validation_path, "r", encoding="utf-8").read()
    lower = text.lower()

    check("go/no-go present", "go/no-go" in lower or "go no go" in lower)
    check("web explicitly local bundle", "local overview bundle, not ghcr" in lower)
    check("central immutable sha policy", bool(re.search(r"openfdd-central:sha-<newest-by-created>", text, re.I)))
    check("mqtt immutable sha policy", bool(re.search(r"openfdd-mqtt:sha-<newest-by-created>", text, re.I)))
    check("fieldbus immutable sha policy", bool(re.search(r"openfdd-fieldbus:sha-<newest-by-created>", text, re.I)))
    check("no nightly deployment tags", ":nightly" not in lower)
    check("jwt secret unconditional", "openfdd_jwt_secret` is required for every compose deployment" in lower)
    check("central private exposure documented", "central must remain authenticated and private" in lower)
    check("central health value documented", "get /api/health" in lower)
    check(
        "LAN/VPN-only exposure enforced",
        "lan/vpn-only" in lower and "no public-internet exposure" in lower and "| public https |" not in lower and "**public:**" not in lower,
    )
    check("public-internet stack exposure explicitly rejected", "never expose the stack directly to the public internet" in lower)
    check("restart marked not verified", "services recover successfully after restart or redeployment | **not verified**" in lower)
    check("bacnet mqtt marked not verified", "bacnet data reaches open-fdd through mqtts | **not verified**" in lower)
    check("mqtt acl marked not verified", "mqtt authentication and topic permissions are verified | **not verified**" in lower)
    check("log claim not overstated", "no credentials or secrets appear in application logs | **conditional**" in lower)
    check(
        "security findings documented",
        "## security findings and reproduction guidance" in lower
        and "public-internet exposure is outside the supported security posture" in lower
        and "central authentication secrets are mandatory deployment controls" in lower,
    )
    check(
        "security reproduction guidance documented",
        "reproduction guidance:" in lower
        and "inspect [`docs/operations/security.md`](security.md)" in lower
        and "capture dated railway logs" in lower,
    )
    check("security acceptance remains conditional", "security findings have documented reproduction guidance | **conditional**" in lower)
    check("security link correct", "(../../security.md)" in lower)
    check("image tag resolution command documented", "ghcr_newest_by_created.py --json openfdd-central openfdd-mqtt openfdd-fieldbus" in lower)
else:
    for label in (
        "go/no-go present","web explicitly local bundle","central immutable sha policy","mqtt immutable sha policy",
        "fieldbus immutable sha policy","no nightly deployment tags","jwt secret unconditional",
        "central private exposure documented","central health value documented","LAN/VPN-only exposure enforced",
        "public-internet stack exposure explicitly rejected","restart marked not verified","bacnet mqtt marked not verified",
        "mqtt acl marked not verified","log claim not overstated","security findings documented",
        "security reproduction guidance documented","security acceptance remains conditional","security link correct",
        "image tag resolution command documented",
    ):
        check(label, False)

print()
passed = sum(checks)
failed = len(checks) - passed
print(f"RESULTS: pass={passed} fail={failed}")
sys.exit(0 if failed == 0 else 1)
