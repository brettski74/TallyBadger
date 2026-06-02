# Configuration seed — see data/README.md
REPO_ROOT := $(abspath ..)
PYTHON := $(REPO_ROOT)/.venv/bin/python
SCRIPTS := $(REPO_ROOT)/scripts

-include seed_data.deps.mk
SEED_MANIFEST_OUTPUTS ?=

.PHONY: default help regen upgrade

default: regen

help:
	@echo "Configuration seed targets (see data/README.md):"
	@echo "  make            Default: regen when seed_data.tar.gz is newer than outputs"
	@echo "  make regen      Expand seed_data.tar.gz into *.json, metadata.json, seed_data.deps.mk"
	@echo "  make upgrade    tbload → tbsave (configuration) → regen (API must be running)"

ifeq ($(strip $(SEED_MANIFEST_OUTPUTS)),)
regen:
	PYTHONPATH=$(REPO_ROOT)/src $(PYTHON) $(SCRIPTS)/seed_regen --data-dir .
else
regen: $(SEED_MANIFEST_OUTPUTS)

$(SEED_MANIFEST_OUTPUTS): seed_data.tar.gz
	PYTHONPATH=$(REPO_ROOT)/src $(PYTHON) $(SCRIPTS)/seed_regen --data-dir .
endif

upgrade:
	$(SCRIPTS)/tbload --mode erase-reload -i .
	$(SCRIPTS)/tbsave -f -o seed_data.tar.gz --scope configuration
	$(MAKE) regen
