# Xattn: build everything and run every check.
#
#   make             build toolchain and simulators (scripts/build.sh)
#   make check       all tests below (needs out/BUILD-INFO, copies it to artifacts/)
#   make check-info  copy out/BUILD-INFO to artifacts/BUILD-INFO alone
#   make check-core  attn_core.h against the float64 model (host only)
#   make check-gcc   GCC testsuite files for Xattn (compile only)
#   make check-sched every pipeline model in this GCC port schedules attn
#   make check-demo  demo/mha_plain.c: one .ATTN and one attn at -O2
#   make check-sim   bare-metal tests on QEMU and Spike
#   make check-recog recognizer: recognized loops vs plain loops, at run time
#   make check-perf  the published per-shape numbers against their raw CSV
#   make check-lint  ruff and mypy over scripts/ and tools/
#   make check-shell  shellcheck on scripts/*.sh
#   make check-artifacts  every file in artifacts/ names the command that produced it
#   make check-xinsn-sim  a generated instruction run on QEMU and Spike (slow)
#   make check-three-way  Spike, QEMU and the host model agree bit for bit
#   make setup       packages, submodules, patches, build, check, demo
#   make artifacts   regenerate artifacts/ (scripts/artifacts.sh)
#   make patches-<cmd>  scripts/patches.sh <cmd>; cmd is apply, export, remove,
#                    restore, check or status

# POSIX keeps the interpreter in .venv/bin/python; on Windows it is
# .venv/Scripts/python.exe, so run `make PYTHON=python` there.
PYTHON  ?= python3
PY      := $(firstword $(wildcard .venv/bin/python) $(wildcard .venv/Scripts/python.exe) .venv/bin/python)
GCC     := $(CURDIR)/out/toolchain/bin/riscv64-unknown-elf-gcc
SHCK    := $(firstword $(wildcard .venv/bin/shellcheck) $(wildcard .venv/Scripts/shellcheck.exe) shellcheck)
export TMPDIR := $(CURDIR)/build/tmp

all:
	scripts/build.sh

# Per-step builds: a change that only touches one tree runs one step, so a
# QEMU-only change does not rebuild GCC.  scripts/build.sh reuses each
# configured build directory, so every target is incremental after the first.
build-binutils build-gcc build-newlib build-libgcc build-dtc build-spike \
build-qemu build-info: build-%:
	scripts/build.sh $*

build: all

$(PY):
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -q --require-hashes -r requirements.lock
	$(PY) -m pip install -q --no-deps -e .

# One summary row per target at the end; a failing row exits non-zero.
CHECK_TARGETS := check-build-info check-info check-core check-gcc check-sched check-demo check-sim check-recog check-perf check-lint check-shell check-artifacts

check:
	bash scripts/check-summary.sh $(CHECK_TARGETS)

# The build record must exist, be at least as new as patches/, and name the
# SHAs versions.env pins.  The check only reads; scripts/build.sh refreshes it.
check-build-info:
	scripts/check-build-info.sh

# Copy the build record these results belong to.  check-build-info has already
# failed if it is missing or stale, so all this has to do is copy it.
check-info:
	@mkdir -p artifacts
	@cp out/BUILD-INFO artifacts/BUILD-INFO
	@echo "artifacts/BUILD-INFO: $$(sed -n '2p' out/BUILD-INFO)"

check-core: $(PY)
	$(PY) -m pytest -q tests/test_core.py

check-gcc:
	@mkdir -p $(TMPDIR)
	python3 tests/run_dg.py gcc/gcc/testsuite/gcc.target/riscv/xattn-*.c

# Reads the tuning table from riscv-cores.def and compiles with -dp per model.
check-sched: $(PY)
	$(PY) -m pytest -q -s tests/test_sched_models.py

# The demo claim: five loop nests become one .ATTN and one attn.
check-demo: $(PY)
	$(PY) -m pytest -q -s tests/test_attn_replacement.py

check-sim: $(PY)
	$(MAKE) -C tests/baremetal CC=$(GCC) ARCH=rv64gc_xattn \
	  OUT=$(CURDIR)/build/baremetal-gcc PYTHON=$(CURDIR)/$(PY) check

check-recog:
	$(MAKE) -C tests/recog check

check-lint: $(PY)
	$(PY) -m ruff check scripts tools
	$(PY) -m mypy scripts tools

check-shell: $(PY)
	$(SHCK) -x scripts/*.sh

# Every file in artifacts/ carries the command and commit that produced it.
check-artifacts:
	scripts/check-artifacts.sh

# Slow: applies examples/insns/mac.spec to the four trees, rebuilds them and
# runs the generated test on QEMU and Spike.  Needs scripts/build.sh first.
check-xinsn-sim: $(PY)
	XATTN_XINSN_SIM=1 $(PY) -m pytest -q tests/test_xinsn.py \
	  -k both_simulators

# Spike, QEMU and the host model, case by case, printing the largest
# absolute difference.  Needs scripts/build.sh first.
check-three-way: $(PY)
	XATTN_SIM=1 $(PY) -m pytest -q -s tests/test_three_way.py

# One script call each.  The scripts stay because they probe the environment
# (packages, versions.env pins, toolchain paths, TMPDIR), which make cannot.
setup:
	scripts/setup.sh

artifacts:
	scripts/artifacts.sh

# apply, export, remove, restore, check, status; every component by default.
PATCH_CMDS := apply export remove restore check status
$(addprefix patches-,$(PATCH_CMDS)): patches-%:
	scripts/patches.sh $*

.PHONY: all build build-binutils build-gcc build-newlib build-libgcc build-dtc build-spike build-qemu build-info check check-build-info check-info check-core check-gcc check-sched check-demo check-sim check-recog check-xinsn-sim check-three-way check-lint check-shell check-artifacts \
  setup artifacts patches-apply patches-export patches-remove \
  patches-restore patches-check patches-status

