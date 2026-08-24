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

check("validation doc exists", os.path.isfile(validation_path))
check("railway deployment doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/RAILWAY_DEPLOYMENT.md")))
check("standalone compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.standalone.yml")))
check("react compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.react.yml")))
check("security doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/security.md")))
check("SECURITY.md exists", os.path.isfile(os.path.join(ROOT, "SECURITY.md")))
check("operations index exists", os.path.isfile(os.path.join(ROOT, "docs/operations/index.md")))

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
    check("restart marked not verified", "services recover successfully after restart or redeployment | **not verified**" in lower)
    check("bacnet mqtt marked not verified", "bacnet data reaches open-fdd through mqtts | **not verified**" in lower)
    check("mqtt acl marked not verified", "mqtt authentication and topic permissions are verified | **not verified**" in lower)
    check("log claim not overstated", "no credentials or secrets appear in application logs | **conditional**" in lower)
    check("security link correct", "(../../security.md)" in lower)
    check("image tag resolution command documented", "ghcr_newest_by_created.py --json openfdd-central openfdd-mqtt openfdd-fieldbus" in lower)
else:
    for label in (
        "go/no-go present",
        "web explicitly local bundle",
        "central immutable sha policy",
        "mqtt immutable sha policy",
        "fieldbus immutable sha policy",
        "no nightly deployment tags",
        "jwt secret unconditional",
        "central private exposure documented",
        "central health value documented",
        "restart marked not verified",
        "bacnet mqtt marked not verified",
        "mqtt acl marked not verified",
        "log claim not overstated",
        "security link correct",
        "image tag resolution command documented",
    ):
        check(label, False)

print()
passed = sum(checks)
failed = len(checks) - passed
print(f"RESULTS: pass={passed} fail={failed}")
sys.exit(0 if failed == 0 else 1)
