# Disposable authenticated ZAP qualification

`run_af_disposable.sh` evaluates scanner-origin evidence. It does not authorize
a scan of a public deployment, production database, OT network or forwarded
production service. Use a disposable stack and short-lived test credentials.
Loopback reachability alone does not prove that a target is disposable.

The normal plan imports the staged OpenAPI document, spiders and drains the
passive queue. Active scanning is a separate opt-in. A successful preflight is
a precondition; only nonce-bound ZAP HAR probes before, during and after the
scan establish scanner authentication. Duplicate and stale probes invalidate
that proof. Raw HAR is hashed and removed because it contains credentials.

## Negative control

`--negative-control` uses the real credential only for the independent positive
preflight, then injects a generated invalid bearer into ZAP. Its rendered plan
contains three `GET /api/auth/me` probes plus export/report jobs. It imports no
API routes and runs no spider or active scan. Positive HTTP 200 and logged-in
statistics expectations are removed so an expected denial cannot stop the plan
after its first probe.

`zap_af_negative_control_v2` passes only when every probe:

- has exactly one current phase/nonce tag and the exact injected invalid header;
- targets the configured origin and auth path, in phase order;
- receives HTTP 401 or 403 and JSON containing `ok: false`;
- is present in an in-scope, bounded, otherwise probe-only HAR from a scanner
  process that exited successfully.

Any probe returning HTTP 200 is **FAIL**, regardless of body or identity.
Missing headers/probes, duplicates, stale nonces, HTTP 500, redirects, malformed
JSON, unexpected traffic and unrelated scanner failures are **ERROR**. These
conditions do not demonstrate credential rejection. A negative-control PASS
proves this narrow denial contract; it is not a vulnerability scan PASS.

## Verdict interpretation and remaining limits

- Alert counts are JSON `null` until evaluated, with `alert_counts_evaluated:
  false`. Selftests, missing evidence and the probe-only negative control do not
  report fictional High=0 results. A normal scan PASS requires known counts.
- `scanner_error_count` is `null`: traditional JSON is not a complete scanner
  error counter. Read the explicit exit code, passive drain evidence, stopping
  insight, scope/auth proof and verdict status; do not coerce unknown to zero.
- Wall time is enforced by terminating the owned process/container. Request
  count is checked against the completed HAR; `request_limit_preventive: false`
  deliberately exposes that this is **not** a hard traffic cutoff. A restrictive
  egress proxy/firewall is still required for a preventive request/route budget.
- Origin and redirect checks reject unsafe evidence but cannot retract traffic
  already sent. Do not infer ownership or network confinement from these checks.
- Offline fake-scanner tests prove evaluator behavior, not live ZAP/add-on
  compatibility, tenant middleware behavior, or candidate qualification.

## Final artifact integrity

The isolated wrapper snapshots artifact byte hashes before final redaction and
verifies them afterward. Its snapshot and buffered evaluator output stay in the
private runner directory. Added, deleted, rewritten, unreadable or symlinked
evidence, a corrupt snapshot, or failed redaction invalidates the top-level
normal and negative verdicts as ERROR and exits nonzero. It never silently
repairs hashes or reuses PASS after changing evaluated evidence. The guard's
PASS means only that wrapper processing preserved the evaluated bytes; the
scanner verdict and its own exit code must still pass. File hashing uses
bounded reads and persists no raw contents or filenames in the snapshot.

Run its offline regressions with:

```bash
python3 -B -m unittest discover -s tests/qualification -p test_zap_artifact_integrity.py -v
```

## Scanner compatibility still needs an isolated run

The plan omits the redundant global `env.parameters.maxDuration`: current
[AF environment documentation](https://www.zaproxy.org/docs/desktop/addons/automation-framework/environment/)
supports it, but older pinned add-ons can reject it. The runner's own wall-clock
termination remains enforced, and `passiveScan-wait.maxDuration: 0` still means
wait for the passive queue to drain. The pinned scanner/add-on combination has
not been re-qualified by these offline tests.

There is also a known injection compatibility question for nondefault ports.
The runner currently configures `ZAP_AUTH_HEADER_SITE` as `host:port`. The
[current upstream listener](https://github.com/zaproxy/zaproxy/blob/main/zap/src/main/java/org/zaproxy/zap/extension/authentication/HttpSenderAuthHeaderListener.java)
and its [v2.16.1 implementation](https://github.com/zaproxy/zaproxy/blob/v2.16.1/zap/src/main/java/org/zaproxy/zap/extension/authentication/HttpSenderAuthHeaderListener.java)
compare that value using a substring check against
[`getHostName()`](https://github.com/zaproxy/zaproxy/blob/main/zap/src/main/java/org/parosproxy/paros/network/HttpRequestHeader.java),
which returns the URI host without its port. That source behavior does not match
the runner's authority value at a nondefault port. The setting is unchanged:
changing it to host-only can expose the credential to other ports and is not an
exact-origin control. A future fix needs exact-origin/port-safe injection and
network confinement, followed by scanner-origin positive and negative evidence
from the actual pinned image. Do not loosen scope or skip the HAR auth proof to
get a green verdict. The existing evaluator fails when injection is missing.

Run offline regressions (three tests use a disposable loopback HTTP fixture):

```bash
python3 -B -m unittest discover -s tests/qualification -p test_zap_af_disposable.py -v
```

`--selftest` is hygiene-only and deliberately exits 2 with **BLOCKED**. Do not
rewrite historical v1 negative-control PASS artifacts as v2-qualified evidence.
