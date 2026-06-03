# Open-FDD edge deploy shortcuts — run from infra/ansible (see ../README.md).
#
#   make help
#   make ui-deploy HOST=acme_vm_bbartling   # prod dashboard build + rsync
#   make docker-deploy HOST=acme_vm_bbartling
#   make build-test                         # vitest + pytest before push
#   SSHPASS='...' make os HOST=acme_vm_bbartling

HOST ?= bacnet_pi
DEPLOY := ./deploy.sh
BUILD := ../../scripts/build_operator_dashboard.sh
ROOT := ../..

.PHONY: help all ui web backend core drivers data config caddy systemd pip commission mcp ai os check docker build build-test docker-build docker-up ui-deploy docker-deploy

help:
	@$(DEPLOY) help

all ui web backend core drivers data config caddy systemd pip commission mcp ai os check docker:
	@$(DEPLOY) $@ --limit $(HOST)

build:
	@cd $(ROOT) && $(BUILD) prod

build-test:
	@cd $(ROOT) && ./scripts/build_and_test.sh

docker-build:
	@cd $(ROOT) && chmod +x scripts/docker_build.sh && ./scripts/docker_build.sh --save

docker-up:
	@cd $(ROOT) && docker compose -f docker/compose.dev.yml up -d

# UI deploy: build dashboard then push static files only
ui-deploy: build ui

# Docker deploy: build bundle then push to HOST
docker-deploy: docker-build docker
