import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
checks = []

def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {label}")
    checks.append(cond)

check("validation doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/RAILWAY_VALIDATION_752.md")))
check("railway deployment doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/RAILWAY_DEPLOYMENT.md")))
check("standalone compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.standalone.yml")))
check("react compose exists", os.path.isfile(os.path.join(ROOT, "docker/compose.react.yml")))
check("caddy overlay exists", os.path.isfile(os.path.join(ROOT, "docker/compose.caddy.react.yml")))
check("security doc exists", os.path.isfile(os.path.join(ROOT, "docs/operations/security.md")))
check("SECURITY.md exists", os.path.isfile(os.path.join(ROOT, "SECURITY.md")))
check("operations index exists", os.path.isfile(os.path.join(ROOT, "docs/operations/index.md")))

validation_path = os.path.join(ROOT, "docs/operations/RAILWAY_VALIDATION_752.md")
if os.path.isfile(validation_path):
    text = open(validation_path, "r", encoding="utf-8").read().lower()
    check("validation doc references go/no-go", "go/no-go" in text or "go no go" in text)
    check("validation doc references mqtt", "mqtt" in text)
    check("validation doc references secrets", "openfdd_jwt_secret" in text)
    check("validation doc references https", "https" in text)
else:
    check("validation doc references go/no-go", False)
    check("validation doc references mqtt", False)
    check("validation doc references secrets", False)
    check("validation doc references https", False)

print()
passed = sum(1 for c in checks if c)
failed = sum(1 for c in checks if not c)
print(f"RESULTS: pass={passed} fail={failed}")
sys.exit(0 if failed == 0 else 1)
