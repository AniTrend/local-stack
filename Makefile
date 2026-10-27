ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON ?= python3
PLATFORM_ARTIFACT_ROOT ?= $(ROOT)/.artifacts/platform

.PHONY: platform-inventory platform-inventory-validate

platform-inventory:
	@$(PYTHON) "$(ROOT)/tools/platform/inventory.py" collect \
		--environment "$(ENV)" \
		--repo-root "$(ROOT)" \
		--artifact-root "$(PLATFORM_ARTIFACT_ROOT)" \
		$(if $(strip $(DOCKER_CONTEXT)),--context "$(DOCKER_CONTEXT)",)

platform-inventory-validate:
	@$(PYTHON) "$(ROOT)/tools/platform/inventory.py" validate \
		--environment "$(ENV)" \
		--artifact-root "$(PLATFORM_ARTIFACT_ROOT)" \
		$(if $(strip $(INVENTORY_FILE)),--input "$(INVENTORY_FILE)",)
