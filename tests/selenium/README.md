# Soft-OPEN 371 — real Selenium product browser

Physical browser acceptance for **both** `BUILDING_100` (package/historical) and
`ACME` (MQTT live). Curl/API-only, page-heading, empty Plotly host, spinner
screenshot, or skipped browser is **never** Soft-OPEN PASS.

Contract: [`.cursor/agents/grok-real-browser-ui-acceptance-20261011.md`](../../.cursor/agents/grok-real-browser-ui-acceptance-20261011.md).

## Install

```bash
python3 -m pip install -r tests/selenium/requirements.txt
# Chrome/Chromium + matching chromedriver on PATH (or webdriver-manager fallback)
```

## Invoke (Grok / lab)

```bash
export OPENFDD_UI_BASE="https://<public-web>"
export OPENFDD_EXPECTED_REVISION="3.5.71+4002de0e628c"   # must match hub tip
export OPENFDD_AGENT_PASSWORD  # from private env — never CLI
export OPENFDD_UI_ARTIFACT_DIR="reports/product_browser_$(date -u +%Y%m%dT%H%M%SZ)"
export OPENFDD_UI_HEADED=1    # prefer headed so operator can watch

python3 tests/selenium/openfdd_product_browser.py \
  --base-url "$OPENFDD_UI_BASE" \
  --expected-revision "$OPENFDD_EXPECTED_REVISION" \
  --manifest tests/selenium/fixtures/product_ui_acceptance_v1.json \
  --artifact-dir "$OPENFDD_UI_ARTIFACT_DIR" \
  --headed --require-all
```

Or:

```bash
OPENFDD_UI_HEADED=1 ./tests/selenium/openfdd_frontend_rigorous.sh
```

## Honesty exits

| Verdict | rc | Meaning |
| --- | --- | --- |
| PASS | 0 | All required browser rows PASS (rare until oracles bound) |
| PARTIAL | 4 | Some coverage missing — not Soft-OPEN |
| BLOCKED | 3 | Missing browser/driver/password/base |
| FAIL | 2 | VERSION_MISMATCH, 502 markers, action timeout, etc. |

`OPENFDD_UI_SELF_CHECK=1` runs offline schema-only (does **not** claim Soft-OPEN).

## What this replaces

The old wrapper that ran `openfdd_ui_smoke.sh` and wrote `{"ok":true}` while calling
Selenium optional is **removed**. That path greenwashed Soft-OPEN.
