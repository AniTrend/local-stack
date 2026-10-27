SHELL := /bin/sh
.DEFAULT_GOAL := help

PLATFORM_VENV ?= .venv-platform
PLATFORM_NODE_DIR ?= .tools/platform/node/bin
PLATFORM_TOOLS_BIN ?= .tools/platform/bin
PLATFORM_PYTHON_BIN ?= $(if $(wildcard $(PLATFORM_VENV)/bin/python),$(PLATFORM_VENV)/bin/python,python3.14)
PLATFORM_NODE_BIN ?= $(if $(wildcard $(PLATFORM_NODE_DIR)/node),$(PLATFORM_NODE_DIR)/node,node)
PLATFORM_NPM_BIN ?= $(if $(wildcard $(PLATFORM_NODE_DIR)/npm),$(PLATFORM_NODE_DIR)/npm,npm)
PLATFORM_PULUMI_BIN ?= $(if $(wildcard $(PLATFORM_TOOLS_BIN)/pulumi),$(abspath $(PLATFORM_TOOLS_BIN)/pulumi),pulumi)
PLATFORM_ANSIBLE_BIN ?= $(if $(wildcard $(PLATFORM_VENV)/bin/ansible-playbook),$(PLATFORM_VENV)/bin/ansible-playbook,ansible-playbook)
PLATFORM_MOLECULE_BIN ?= $(if $(wildcard $(PLATFORM_VENV)/bin/molecule),$(PLATFORM_VENV)/bin/molecule,molecule)
PLATFORM_ANSIBLE_GALAXY_BIN ?= $(if $(wildcard $(PLATFORM_VENV)/bin/ansible-galaxy),$(PLATFORM_VENV)/bin/ansible-galaxy,ansible-galaxy)
PLATFORM_ANSIBLE_COLLECTIONS_PATH ?= .tools/platform/collections
LAB_CLI := tools/platform/lab.py
PLATFORM_ANSIBLE_RUNNER := tools/platform/ansible_runner.py

export PLATFORM_PYTHON_BIN PLATFORM_NODE_BIN PLATFORM_NPM_BIN PLATFORM_PULUMI_BIN
export PLATFORM_ANSIBLE_BIN PLATFORM_ANSIBLE_GALAXY_BIN PLATFORM_MOLECULE_BIN PLATFORM_ANSIBLE_COLLECTIONS_PATH
export ANSIBLE_COLLECTIONS_PATH := $(abspath $(PLATFORM_ANSIBLE_COLLECTIONS_PATH))
export ANSIBLE_CONFIG := $(abspath ansible/ansible.cfg)
export ANSIBLE_ROLES_PATH := $(abspath ansible/roles)

ifneq ($(wildcard $(PLATFORM_VENV)/bin/python),)
export PATH := $(abspath $(PLATFORM_VENV))/bin:$(PATH)
endif
ifneq ($(wildcard $(PLATFORM_NODE_DIR)/node),)
export PATH := $(abspath $(PLATFORM_NODE_DIR)):$(PATH)
endif
ifneq ($(wildcard $(PLATFORM_TOOLS_BIN)/pulumi),)
export PATH := $(abspath $(PLATFORM_TOOLS_BIN)):$(PATH)
endif

.PHONY: help platform-doctor platform-lab-up platform-lab-test platform-lab-down platform-pulumi-test platform-ansible-test platform-host-verify platform-preview platform-evidence-validate

help:
	@printf '%s\n' \
	  'Platform lab:' \
	  '  make platform-doctor ENV=lab' \
	  '  make platform-lab-up ENV=lab' \
	  '  make platform-lab-test ENV=lab' \
	  '  make platform-lab-down ENV=lab' \
	  'Platform Pulumi:' \
	  '  make platform-pulumi-test ENV=lab' \
	  '  make platform-preview ENV=lab|rehearsal|production' \
	  'Platform Ansible:' \
	  '  make platform-ansible-test ENV=lab' \
	  '  make platform-host-verify ENV=lab TIER=vm' \
	  'Platform evidence (record validation, not gate approval):' \
	  '  make platform-evidence-validate ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_SHA'

platform-doctor:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-doctor' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(LAB_CLI) doctor --environment "$(ENV)"

platform-lab-up:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-lab-up' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(LAB_CLI) up --environment "$(ENV)"

platform-lab-test:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-lab-test' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(LAB_CLI) test --environment "$(ENV)"

platform-lab-down:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-lab-down' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(LAB_CLI) down --environment "$(ENV)"

platform-pulumi-test:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-pulumi-test' >&2; exit 2; }
	@$(PLATFORM_NPM_BIN) test --prefix infra/pulumi/docker
	@$(PLATFORM_NPM_BIN) test --prefix infra/pulumi/hcloud
	@$(PLATFORM_PYTHON_BIN) -m pytest -q tests/platform

platform-preview:
	@test -n "$(ENV)" || { printf '%s\n' 'ENV is required for platform-preview' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) tools/platform/pulumi_preview.py --environment "$(ENV)"

platform-ansible-test:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-ansible-test' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(PLATFORM_ANSIBLE_RUNNER) container-test --environment "$(ENV)"

platform-host-verify:
	@test "$(ENV)" = "lab" || { printf '%s\n' 'ENV=lab is required for platform-host-verify' >&2; exit 2; }
	@test "$(TIER)" = "vm" || { printf '%s\n' 'TIER=vm is required for platform-host-verify' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) $(PLATFORM_ANSIBLE_RUNNER) host-verify --environment "$(ENV)" --tier "$(TIER)"

platform-evidence-validate:
	@test -n "$(ENV)" || { printf '%s\n' 'ENV is required for platform-evidence-validate' >&2; exit 2; }
	@test -n "$(TIER)" || { printf '%s\n' 'TIER=docker or TIER=vm is required' >&2; exit 2; }
	@test -n "$(MANIFEST)" || { printf '%s\n' 'MANIFEST must identify an existing evidence record' >&2; exit 2; }
	@test -n "$(COMMIT)" || { printf '%s\n' 'COMMIT must be the exact full candidate SHA' >&2; exit 2; }
	@$(PLATFORM_PYTHON_BIN) tools/platform/evidence.py --manifest "$(MANIFEST)" --environment "$(ENV)" --tier "$(TIER)" --commit "$(COMMIT)"

.DEFAULT:
	@printf 'No rule for target "%s"; unimplemented platform commands fail closed.\n' "$@" >&2
	@exit 2
