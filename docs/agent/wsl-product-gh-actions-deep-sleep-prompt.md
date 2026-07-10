# WSL product agent — GH Actions deep sleep (paste prompt)

**Repo-only** (not on GitHub Pages). Paste into Cursor on **`/home/ben/src/open-fdd`** when you want the product agent to monitor CI and fix failures without chatter until green.

Edge tester counterpart: [linux-edge-tester-gh-actions-watch-prompt.md](./linux-edge-tester-gh-actions-watch-prompt.md)

---

```
You are the Open-FDD WSL product agent on /home/ben/src/open-fdd.

Deep sleep mode: check GitHub Actions on master every 30 minutes.
Fix failures immediately (code PR, re-dispatch, cancel stuck GHCR publish).
Redeploy Docs/Pages or verify GHCR when a fix lands.
Go SILENT when all critical workflows are success on master HEAD — no status spam.

Acknowledged. Product tree /home/ben/src/open-fdd. Channel: master CI → GHCR :nightly.
Critical workflows: Rust Edge CI, Publish Rust edge to GHCR, Security Guards, AppSec, Docs.
Will wake only on failure or stuck publish (>2h in_progress).
```

---

## Watch command (one shot)

```bash
./scripts/openfdd_product_gh_actions_watch.sh
echo $?   # 0=all green, 1=failure (fix now), 2=pending (silent wait)
```

## Background loop (30 min, wake agent only on failure)

```bash
cd /home/ben/src/open-fdd
while true; do
  sleep 1800
  ./scripts/openfdd_product_gh_actions_watch.sh || true
done
```

The script prints `AGENT_LOOP_WAKE_GH_ACTIONS` only when a workflow **failed** on the current `master` HEAD.

---

## On wake (failure)

1. Identify run: `gh run list --repo bbartling/open-fdd --branch master --limit 10`
2. Logs: `gh run view <id> --log-failed`
3. Fix in WSL → PR → merge (or `workflow_dispatch` / cancel stuck GHCR if transient)
4. Wait for green on new HEAD; **do not** message until failure or user asks

### Stuck GHCR publish (>2 h `in_progress`)

```bash
gh run list --repo bbartling/open-fdd --workflow "Publish Rust edge to GHCR" --limit 3
gh run cancel <run_id>   # if hung
gh workflow run rust-ghcr.yml --ref master   # if workflow supports dispatch
```

---

## Green lit (stay silent)

When `./scripts/openfdd_product_gh_actions_watch.sh` exits **0** with no output:

- Rust CI + GHCR publish + guards + AppSec + Pages all **success** on `master` HEAD
- `:nightly` is published for edge to pull
- No comment on #429 unless edge is waiting for explicit handoff

---

## Division of labor

| Agent | Host | CI role |
|-------|------|---------|
| **Product (you)** | WSL | Build via GH Actions, fix red CI, publish GHCR |
| **Edge tester** | `/home/ben/open-fdd` | Pull GHCR only (no local build — insufficient RAM), re-gate #429 |
