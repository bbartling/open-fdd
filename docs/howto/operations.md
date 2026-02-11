---
title: Operations
parent: How-to Guides
nav_order: 2
---

# Operations

---

## Start / stop / restart

```bash
cd platform
docker compose down
docker compose up -d
```

Reboot: containers stop unless Docker or systemd is configured to start them on boot.

---

## Resource check

```bash
free -h && uptime && echo "---" && docker stats --no-stream 2>/dev/null
```

---

## Database

```bash
cd platform
docker compose exec db psql -U postgres -d openfdd -c "\dt"
```

---

## Unit tests

```bash
cd /home/ben/open-fdd
.venv/bin/python -m pytest open_fdd/tests/ -v
```
