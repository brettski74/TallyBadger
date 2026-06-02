# Configuration seed — see data/README.md
REPO_ROOT := ..
PYTHON ?= $(REPO_ROOT)/.venv/bin/python
SCRIPTS := $(REPO_ROOT)/scripts

-include seed_data.deps.mk
SEED_MANIFEST_OUTPUTS ?=

.PHONY: default regen upgrade

default: regen

ifeq ($(strip $(SEED_MANIFEST_OUTPUTS)),)
regen:
	PYTHONPATH=$(REPO_ROOT)/src $(PYTHON) $(SCRIPTS)/seed_regen regen --data-dir .
else
regen: $(SEED_MANIFEST_OUTPUTS)

$(SEED_MANIFEST_OUTPUTS): seed_data.tar.gz
	PYTHONPATH=$(REPO_ROOT)/src $(PYTHON) $(SCRIPTS)/seed_regen regen --data-dir .
endif

upgrade:
	$(SCRIPTS)/tbload --mode erase-reload -i .
	$(SCRIPTS)/tbsave -f -o seed_data.tar.gz --scope configuration
	$(MAKE) regen
