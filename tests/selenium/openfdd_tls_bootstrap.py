#!/usr/bin/env python3
"""Self-signed TLS ingress bootstrap + MCP README clarity eval for WSL agents."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path

from openfdd_test_lib import Check, OpenFddClient, RunResult, bench_root, log, resolve_password, utc_now

MCP_README_URL = os.environ.get(
    "OPENFDD_MCP_README_RAW_URL",
    "https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/mcp/README.md",
)
MAIN_README_URL = os.environ.get(
    "OPENFDD_README_RAW_URL",
    "https://raw.githubusercontent.com/bbartling/open-fdd/refs/heads/master/README.md",
)
TLS_BASE = os.environ.get("OPENFDD_CADDY_TLS_BASE", "https://127.0.0.1:443").rstrip("/")


def fetch_url(url: str, dest: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            dest.write_text(resp.read().decode("utf-8", errors="replace"), encoding="utf-8")
        return True
    except OSError as exc:
        dest.write_text(f"# fetch failed: {exc}\n", encoding="utf-8")
        return False


def eval_mcp_docs_clarity(out_dir: Path) -> list[Check]:
    """Score MCP README for agent bootstrap clarity (TLS cross-refs, stdio, JWT)."""
    checks: list[Check] = []
    mcp_readme = out_dir / "mcp.README.master.md"
    main_readme = out_dir / "README.master.md"

    if fetch_url(MCP_README_URL, mcp_readme):
        checks.append(Check("mcp-docs-fetch", "PASS", f"fetched {MCP_README_URL}"))
    else:
        checks.append(Check("mcp-docs-fetch", "FAIL", f"could not fetch {MCP_README_URL}"))
        return checks

    text = mcp_readme.read_text(encoding="utf-8")
    for needle, name in (
        ("stdio", "mcp-docs-stdio"),
        ("OPENFDD_MCP_TOKEN", "mcp-docs-jwt-env"),
        ("OPENFDD_API_BASE", "mcp-docs-api-base"),
    ):
        if needle.lower() in text.lower():
            checks.append(Check(name, "PASS", f"MCP README documents `{needle}`"))
        else:
            checks.append(Check(name, "FAIL", f"MCP README missing `{needle}` — WSL agents need explicit JWT/stdio steps"))

    if "tools/list" in text.lower() or "tools/call" in text.lower() or "| Tool |" in text:
        checks.append(Check("mcp-docs-tools-list", "PASS", "MCP README documents tool surface (list/call or tools table)"))
    else:
        checks.append(Check("mcp-docs-tools-list", "FAIL", "MCP README missing tools/list or tools table"))

    # TLS / self-signed ingress: agents hit :8090/:443 on LAN; MCP README is silent today.
    tls_terms = ("caddy-tls", "self-signed", "tls generate", "443", "OPENFDD_CADDY")
    if any(t.lower() in text.lower() for t in tls_terms):
        checks.append(Check("mcp-docs-tls-bootstrap", "PASS", "MCP README mentions TLS/self-signed ingress"))
    else:
        checks.append(
            Check(
                "mcp-docs-tls-bootstrap",
                "FAIL",
                "MCP README has no TLS/self-signed bootstrap — agents must also read "
                "scripts/openfdd_caddy_test_recipe.sh caddy-tls + haystack tls_verify=false",
                product_bug=True,
            )
        )

    if fetch_url(MAIN_README_URL, main_readme):
        main = main_readme.read_text(encoding="utf-8")
        if "caddy-tls" in main or "openfdd_caddy_test_recipe" in main:
            checks.append(
                Check(
                    "mcp-docs-tls-crossref",
                    "PASS" if "caddy" in text.lower() or "tls" in text.lower() else "FAIL",
                    "main README documents caddy-tls; MCP README should cross-link for HTTPS benches",
                )
            )
            if "caddy" not in text.lower() and "tls" not in text.lower():
                checks[-1] = Check(
                    checks[-1].name,
                    "FAIL",
                    "main README has caddy-tls recipe but mcp/README.md does not cross-link — add HTTPS OPENFDD_API_BASE note",
                    product_bug=True,
                )
        else:
            checks.append(Check("mcp-docs-tls-crossref", "SKIP", "main README caddy-tls section not found on master"))
    else:
        checks.append(Check("mcp-docs-tls-crossref", "SKIP", "main README fetch failed"))

    clarity = {
        "mcp_readme_url": MCP_README_URL,
        "has_stdio": "stdio" in text.lower(),
        "has_jwt_env": "OPENFDD_MCP_TOKEN" in text,
        "has_tls_bootstrap": any(t.lower() in text.lower() for t in tls_terms),
        "recommended_agent_steps": [
            "./scripts/openfdd_caddy_test_recipe.sh caddy-tls",
            "curl -k https://127.0.0.1:443/api/health",
            "export OPENFDD_API_BASE=https://127.0.0.1:443  # MCP sidecar over self-signed TLS",
            "workspace/haystack/local.nhaystack.toml → tls_verify=false for Niagara self-signed",
        ],
    }
    (out_dir / "mcp_docs_clarity.json").write_text(json.dumps(clarity, indent=2), encoding="utf-8")
    return checks


def run_tls_bootstrap(out_dir: Path, skip_caddy: bool = False) -> RunResult:
    root = bench_root()
    result = RunResult(
        artifact_dir=str(out_dir),
        started_at=utc_now(),
        meta={"phase": "tls_bootstrap", "tls_base": TLS_BASE},
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    cert_dir = Path(os.environ.get("OPENFDD_CADDY_CERT_DIR", root / "workspace/deploy/caddy/certs"))
    caddy_sh = root / "scripts/openfdd_caddy_test_recipe.sh"

    for check in eval_mcp_docs_clarity(out_dir):
        result.add(check)

    if skip_caddy or os.environ.get("OPENFDD_TLS_SKIP_CADDY", "0") == "1":
        result.add(Check("tls-caddy-recipe", "SKIP", "OPENFDD_TLS_SKIP_CADDY=1"))
        result.finalize()
        result.write(out_dir)
        return result

    if not caddy_sh.exists():
        result.add(Check("tls-caddy-recipe", "FAIL", f"missing {caddy_sh}"))
        result.finalize()
        result.write(out_dir)
        return result

    log(f"tls bootstrap → caddy-tls certs in {cert_dir}")
    proc = subprocess.run(
        [str(caddy_sh), "caddy-tls"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    (out_dir / "caddy_tls_stdout.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        result.add(Check("tls-caddy-recipe", "FAIL", f"caddy-tls exit={proc.returncode} — see caddy_tls_stdout.txt"))
        result.finalize()
        result.write(out_dir)
        return result
    result.add(Check("tls-caddy-recipe", "PASS", "caddy-tls profile up"))

    if (cert_dir / "cert.pem").exists() and (cert_dir / "key.pem").exists():
        result.add(Check("tls-self-signed-certs", "PASS", f"cert.pem + key.pem in {cert_dir}"))
    else:
        result.add(Check("tls-self-signed-certs", "FAIL", f"expected self-signed certs in {cert_dir}"))

    user, pw = resolve_password(root, "integrator")
    try:
        client = OpenFddClient.login(TLS_BASE, user, pw, verify_tls=False)
    except Exception as exc:
        result.add(Check("tls-login", "FAIL", str(exc)))
        _restore_direct(root, caddy_sh)
        result.finalize()
        result.write(out_dir)
        return result

    st, health = client.get("/api/health")
    client.save_json(out_dir / "tls_health.json", st, health)
    if st == 200 and isinstance(health, dict) and health.get("ok"):
        result.add(Check("tls-health", "PASS", f"HTTPS /api/health ok version={health.get('version', '?')}"))
    else:
        result.add(Check("tls-health", "FAIL", f"HTTPS health status={st}"))

    st, host_stats = client.get("/api/host/stats")
    client.save_json(out_dir / "tls_host_stats.json", st, host_stats)
    if st == 200 and isinstance(host_stats, dict) and host_stats.get("ok", True):
        ollama = host_stats.get("ollama")
        detail = "ollama present" if ollama is not None else "ollama omitted (external-agents refactor)"
        result.add(Check("tls-host-stats", "PASS", f"HTTPS /api/host/stats ok — {detail}"))
        if ollama is None:
            result.add(
                Check(
                    "tls-host-stats-ollama-schema",
                    "PASS",
                    "API omits ollama over TLS — HostStatsPage must tolerate absence (FIX-13)",
                )
            )
        elif isinstance(ollama, dict):
            result.add(
                Check(
                    "tls-host-stats-ollama-schema",
                    "PASS",
                    f"ollama.api_ok={ollama.get('api_ok')}",
                )
            )
    else:
        result.add(Check("tls-host-stats", "FAIL", f"HTTPS host/stats status={st}"))

    # MCP sidecar smoke over HTTPS base (same env WSL agents use)
    mcp_image = os.environ.get(
        "OPENFDD_MCP_GHCR_IMAGE",
        f"ghcr.io/bbartling/openfdd-mcp:{os.environ.get('OPENFDD_GHCR_TAG', 'latest')}",
    )
    if client.token and subprocess.run(["docker", "image", "inspect", mcp_image], capture_output=True).returncode == 0:
        call = '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"openfdd_health","arguments":{}}}'
        ndjson = out_dir / "mcp_tls_health.ndjson"
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f"""{{
                  echo '{{"jsonrpc":"2.0","id":1,"method":"initialize","params":{{"protocolVersion":"2024-11-05","capabilities":{{}},"clientInfo":{{"name":"bench-tls","version":"1"}}}}}}'
                  sleep 0.2
                  echo '{{"jsonrpc":"2.0","method":"notifications/initialized","params":{{}}}}'
                  sleep 0.2
                  echo '{call}'
                }} | timeout 25 docker run --rm -i --network host \\
                  -e OPENFDD_API_BASE={TLS_BASE} \\
                  -e OPENFDD_MCP_TOKEN={client.token} \\
                  {mcp_image}""",
            ],
            capture_output=True,
            text=True,
        )
        ndjson.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if '"content"' in proc.stdout:
            result.add(Check("tls-mcp-openfdd_health", "PASS", f"MCP openfdd_health over {TLS_BASE}"))
        else:
            result.add(Check("tls-mcp-openfdd_health", "FAIL", "MCP health call failed over HTTPS — see mcp_tls_health.ndjson"))
    else:
        result.add(Check("tls-mcp-openfdd_health", "SKIP", f"MCP image {mcp_image} not local"))

    _restore_direct(root, caddy_sh)
    result.add(Check("tls-restore-direct", "PASS", "restored direct :8080 ingress"))

    result.finalize()
    result.write(out_dir)
    return result


def _restore_direct(root: Path, caddy_sh: Path) -> None:
    if os.environ.get("OPENFDD_TLS_LEAVE_CADDY", "0") == "1":
        return
    subprocess.run([str(caddy_sh), "direct"], cwd=str(root), capture_output=True, text=True, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-FDD TLS bootstrap + MCP docs clarity")
    parser.add_argument("--out", default=os.environ.get("OPENFDD_TLS_ARTIFACT_DIR", ""))
    parser.add_argument("--docs-only", action="store_true", help="MCP README clarity only (no caddy-tls)")
    args = parser.parse_args()
    out = Path(args.out) if args.out else bench_root() / "workspace/logs/tls_bootstrap_latest"
    log(f"tls bootstrap → {out}")
    result = run_tls_bootstrap(out, skip_caddy=args.docs_only)
    log(f"done pass={result.pass_count} fail={result.fail_count} skip={result.skip_count}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
