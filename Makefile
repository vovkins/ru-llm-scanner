# Four public operations. Keep command-line values inert, including GNU Make 3.81.
.DEFAULT_GOAL := help
.PHONY: build scan diff test help
# Inspect origins/names only; never recursively expand command-line values.
override _SCANNER_EXPLICIT := $(foreach k,$(.VARIABLES),$(if $(filter command line,$(origin $(k))),$(k)))
unexport $(foreach k,$(.VARIABLES),$(if $(filter command line,$(origin $(k))),$(k)))
override MAKEOVERRIDES :=
unexport MAKEFLAGS MFLAGS
unexport REPO COMMIT FROM TO OUTPUT CONFIG BASELINE REQUIRE_BASELINE ANALYZER_CPUS SCANNER_CPUS ANALYZER_MEMORY SCANNER_MEMORY RUN_TIMEOUT_SECONDS STOP_GRACE_SECONDS
override _SCANNER_MAKEFILE := $(value MAKEFILE_LIST)
export _SCANNER_MAKEFILE _SCANNER_EXPLICIT
ifeq ($(origin REPO),command line)
override _SCANNER_REPO := $(value REPO)
else
override _SCANNER_REPO :=
endif
export _SCANNER_REPO
ifeq ($(origin COMMIT),command line)
override _SCANNER_COMMIT := $(value COMMIT)
else
override _SCANNER_COMMIT :=
endif
export _SCANNER_COMMIT
ifeq ($(origin FROM),command line)
override _SCANNER_FROM := $(value FROM)
else
override _SCANNER_FROM :=
endif
export _SCANNER_FROM
ifeq ($(origin TO),command line)
override _SCANNER_TO := $(value TO)
else
override _SCANNER_TO :=
endif
export _SCANNER_TO
ifeq ($(origin OUTPUT),command line)
override _SCANNER_OUTPUT := $(value OUTPUT)
else
override _SCANNER_OUTPUT :=
endif
export _SCANNER_OUTPUT
ifeq ($(origin CONFIG),command line)
override _SCANNER_CONFIG := $(value CONFIG)
else
override _SCANNER_CONFIG :=
endif
export _SCANNER_CONFIG
ifeq ($(origin BASELINE),command line)
override _SCANNER_BASELINE := $(value BASELINE)
else
override _SCANNER_BASELINE :=
endif
export _SCANNER_BASELINE
ifeq ($(origin REQUIRE_BASELINE),command line)
override _SCANNER_REQUIRE_BASELINE := $(value REQUIRE_BASELINE)
else
override _SCANNER_REQUIRE_BASELINE :=
endif
export _SCANNER_REQUIRE_BASELINE
ifeq ($(origin ANALYZER_CPUS),command line)
override _SCANNER_ANALYZER_CPUS := $(value ANALYZER_CPUS)
else
override _SCANNER_ANALYZER_CPUS :=
endif
export _SCANNER_ANALYZER_CPUS
ifeq ($(origin SCANNER_CPUS),command line)
override _SCANNER_SCANNER_CPUS := $(value SCANNER_CPUS)
else
override _SCANNER_SCANNER_CPUS :=
endif
export _SCANNER_SCANNER_CPUS
ifeq ($(origin ANALYZER_MEMORY),command line)
override _SCANNER_ANALYZER_MEMORY := $(value ANALYZER_MEMORY)
else
override _SCANNER_ANALYZER_MEMORY :=
endif
export _SCANNER_ANALYZER_MEMORY
ifeq ($(origin SCANNER_MEMORY),command line)
override _SCANNER_SCANNER_MEMORY := $(value SCANNER_MEMORY)
else
override _SCANNER_SCANNER_MEMORY :=
endif
export _SCANNER_SCANNER_MEMORY
ifeq ($(origin RUN_TIMEOUT_SECONDS),command line)
override _SCANNER_RUN_TIMEOUT_SECONDS := $(value RUN_TIMEOUT_SECONDS)
else
override _SCANNER_RUN_TIMEOUT_SECONDS :=
endif
export _SCANNER_RUN_TIMEOUT_SECONDS
ifeq ($(origin STOP_GRACE_SECONDS),command line)
override _SCANNER_STOP_GRACE_SECONDS := $(value STOP_GRACE_SECONDS)
else
override _SCANNER_STOP_GRACE_SECONDS :=
endif
export _SCANNER_STOP_GRACE_SECONDS

# The recipe is constant: no user path/value is inserted into shell source.
build scan diff test help:
	@python3 -I -S -c 'import os,runpy; from pathlib import Path; runpy.run_path(str(Path(os.environ["_SCANNER_MAKEFILE"].strip()).resolve().with_name("scripts") / "workflow.py"),run_name="__main__")' --make $@
