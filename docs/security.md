---
title: Security
nav_order: 8
---

# Security

The **`open-fdd`** PyPI package is a **Python library** for evaluating rules on in-memory (or local) **pandas** data. It does **not** open network ports or ship a hosted service.

---

## Supply chain and dependencies

- **Pinned versions** — follow your organization’s policy for pinning **`open-fdd`** and its dependencies (**pandas**, **numpy**, **pyyaml**, **pydantic**) in applications.
- **Verify PyPI artifacts** — use **`twine check`** and hashes in lockfiles where applicable.

---

## Rule YAML and expressions

- **Trust model** — only load rule YAML from **trusted** paths (version-controlled configs, sealed containers, or signed bundles). Treat rule files like code.
- **Expression rules** — use the documented expression surface; avoid piping untrusted strings directly into rule files without review.

---

## Reporting issues

Report security-sensitive bugs through the repository’s **[Security policy](https://github.com/bbartling/open-fdd/security/policy)** (if enabled) or maintainer contact on the project README.
