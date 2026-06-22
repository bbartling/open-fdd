# GitHub Actions added

This branch should now run:

- Rust format/check/test
- Frontend syntax check
- Legacy UI guard
- Docker image build
- Docker Compose smoke test
- Auth login smoke
- BACnet driver tree smoke
- BACnet override scan-once smoke
- BACnet override CSV export smoke
- Workspace CSV file existence checks
- Python project-shape guard

Important PR branch note:

If the PR source branch is `rust-rewrite-1`, update the Linux checkout from that branch, not a stale local `pr-354` branch:

```bash
git status
git diff README.md
git stash push -m "local README before PR354 sync" README.md
git fetch origin rust-rewrite-1
git switch -C rust-rewrite-1 origin/rust-rewrite-1
```

Or refresh a local PR branch directly from the PR ref:

```bash
git fetch origin pull/354/head
git switch pr-354
git reset --hard FETCH_HEAD
```
