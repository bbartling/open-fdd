---
name: openfdd-nf-paid-support
description: >-
  Pointer for paid Normal Framework support work (nf-support GitHub issues,
  demo-tenant or portal invites). Use with nf-support, demo tenant, portal
  invite, or paid NF support tickets. The queue and customer details stay private.
---

# NF paid support

This is not Open-FDD product work. Keep it out of this repo.

1. Issues: `gh issue list -R normalframework/nf-support`
   (https://github.com/normalframework/nf-support/issues).
2. The ticket queue, invitees, and chat threads live in the owner's private notes,
   not in git. Read and update them there.
3. Install, license, scan and portal checks: [`openfdd-nf-edge-bench`](../openfdd-nf-edge-bench/SKILL.md).
   Portal-tunnel check after an upgrade: read one live point through
   `https://<installation-uuid>.normal-online.net` with an API key.

Never commit customer names or emails, portal admin steps, private chat IDs,
IP addresses, or credentials.
