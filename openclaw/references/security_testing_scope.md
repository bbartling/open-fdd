# Security and web-app testing — scope

## In scope (lab / dev)

- **Smoke-level** web checks: auth flows as documented, obvious misconfigurations, safe HTTP checks (`curl` to own host).
- **Dependency and header hygiene** notes for follow-up (CORS, cookies, TLS termination) — file as **recommendations** in `issues_log.md` with **no exploit code**.
- **Link rot** on public docs sites.

## Out of scope without explicit written authorization

- Brute force, credential stuffing, or bypass attempts against production or third-party systems.
- **Destructive** tests (data wipe, DoS, `docker system prune` on shared hosts).
- Publishing unpatched **0day** details in the public repo; use **private** GitHub security reporting if the project enables it.

## Recording

For each finding: **date**, **environment** (local dev only vs other), **severity guess**, **repro** (safe), **suggested GitHub issue** title. Escalate “next phase security” as discrete issues on **bbartling/open-fdd**, not only `issues_log.md`.
