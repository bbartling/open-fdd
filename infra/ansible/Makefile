# Open-FDD edge deploy shortcuts (run from infra/ansible)
#
#   make help
#   make ui HOST=acme_vm_bbartling
#   make all HOST=bacnet_pi
#   SSHPASS='...' make os HOST=acme_vm_bbartling

HOST ?= bacnet_pi
DEPLOY := ./deploy.sh
BUILD := ../../scripts/build_operator_dashboard.sh
ROOT := ../..

.PHONY: help all ui web backend core drivers data config caddy systemd pip commission mcp ai os check build build-test

help:
	@$(DEPLOY) help

all ui web backend core drivers data config caddy systemd pip commission mcp ai os check:
	@$(DEPLOY) $@ --limit $(HOST)

build:
	@cd $(ROOT) && $(BUILD) prod

build-test:
	@cd $(ROOT) && ./scripts/build_and_test.sh

# UI deploy: build dashboard then push static files only
ui-deploy: build ui
