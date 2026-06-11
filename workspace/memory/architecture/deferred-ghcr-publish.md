# Deferred: GHCR Docker publish

**Do not publish automatically.** Operator said to do this later.

When asked to publish Open-FDD addon images:

1. Read `docs/howto/publish_docker_addons.md`
2. Use GitHub Actions **Publish Docker addons** (`workflow_dispatch`) with a non-`local` tag, **or** local `OPENFDD_IMAGE_TAG=… ./scripts/docker_build.sh` + `docker_publish.sh`
3. Edge deploy **today** still uses `scripts/docker_build.sh --save` + `infra/ansible/deploy.sh docker` — registry pull on Acme is not wired yet

Images: `openfdd-bridge`, `openfdd-commission`, `openfdd-bacnet-poll`, `openfdd-mcp-rag` → `ghcr.io/bbartling/<name>:<tag>`

Manifest: `supervisor/manifest.yaml`, catalog: `docker/images.yaml`
