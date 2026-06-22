# Rust edge bootstrap

## GHCR one-liner

```bash
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/rust-rewrite-1/scripts/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start
```

## Options

| Flag | Purpose |
| --- | --- |
| `--start` | pull image and `docker compose up -d` |
| `--image-tag TAG` | GHCR tag (default `latest`) |
| `--platform auto\|linux/amd64\|linux/arm64` | pull platform |
| `--root PATH` | install root (default `~/open-fdd`) |
| `--force-auth` | regenerate `workspace/auth.env.local` |
| `--restart` | `compose up -d --force-recreate` (reload env files) |
| `--show-secrets` | lab only — print generated passwords |

## Created layout

```text
~/open-fdd/
  docker-compose.yml          # from docker/compose.edge.rust.yml
  workspace/
    auth.env.local            # chmod 600, never commit
    data.env.local
    bacnet/commissioning/commission.env
    data/drivers/
    data/historian/
    logs/
  scripts/
    openfdd_rust_site_*.sh
```

## After bootstrap

```bash
cd ~/open-fdd
./scripts/openfdd_rust_edge_validate.sh
```

Login at `http://127.0.0.1:8080` with integrator user from `workspace/auth.env.local`.

## Network

Default compose binds `127.0.0.1:8080`. Expose via Tailscale, VPN, or reverse proxy — not direct public internet.
