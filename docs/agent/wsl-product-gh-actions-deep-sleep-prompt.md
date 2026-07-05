# WSL product agent — GH Actions deep sleep (paste prompt)

**Repo-only**. Paste on **`/home/ben/src/open-fdd`** to monitor CI, fix failures, ship nightly.

---

```
Deep sleep: check master GH Actions every 30m. Fix red CI immediately. Go silent when all green.
Acknowledged. Product WSL. Channel: master → GHCR :nightly.
```

```bash
./scripts/openfdd_product_gh_actions_watch.sh   # 0=green 1=fail 2=pending
```
