---
name: security-checks
description: Run the Open-FDD security checks (ZAP against the mock NF, npm audit, gitleaks, CSP).
---
# Security checks

CI workflow: `.github/workflows/security.yml` (every push and PR, weekly).

1. **CSP**: no inline scripts or styles; every library vendored, pinned, never younger than two weeks. The meta tag
   in `nf-app/static/index.html` is `default-src 'self'` plus `wasm-unsafe-eval`, and `script-src`/`connect-src` also
   allow `https:` for exactly one reason: the portal login loads `clerk-js` from the host in the portal's
   publishable key (unknown until runtime). Keep it at an exact pinned version (`CLERK_JS_VERSION` in both
   `nf.js` files, at least two weeks old), add no other remote script, and never write "self-only" or "no CDN at
   runtime" in docs. Also check: SPARQL stays read-only (no UPDATE/SERVICE), CSV cells stay formula-safe, and
   `api()` retries only reads.
2. **npm audit**: `cd nf-app && npm audit --audit-level=high`.
3. **gitleaks**: `gitleaks detect` (allowlist in `.gitleaks.toml`). Never commit passwords, tokens, `auth.caddy` or certs.
4. **ZAP baseline against the mock**: `node nf-app/dev/mock-nf.mjs 8765 &`, then run the ZAP baseline on
   `http://127.0.0.1:8765/api/v1/apps/static/open-fdd/` (CI uses `zaproxy/action-baseline`). Fix, do not silence, new alerts.
5. Vulnerabilities are reported privately (`SECURITY.md`), never in public issues.

The app only writes its own result points and weather variables; keep it that way.
