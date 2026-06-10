# Open-FDD edge deploy shortcuts — run from infra/ansible (see README.md).
#
#   make help
#   OPENFDD_IMAGE_TAG=latest make docker HOST=acme_vm_bbartling
#   make check HOST=acme_vm_bbartling

HOST ?= bacnet_pi
DEPLOY := ./deploy.sh
ROOT := ../..

.PHONY: help docker check maintain ops os build-test docker-deploy

help:
	@$(DEPLOY) help

docker check maintain ops os:
	@$(DEPLOY) $@ --limit $(HOST)

build-test:
	@cd $(ROOT) && ./scripts/build_and_test.sh

# GHCR image pull + compose (no workstation file sync)
docker-deploy:
	@OPENFDD_IMAGE_TAG=$${OPENFDD_IMAGE_TAG:-latest} $(DEPLOY) docker --limit $(HOST)
