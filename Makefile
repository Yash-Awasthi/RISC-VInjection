# Xattn: build everything and run every check.
#
#   make             build toolchain and simulators (scripts/build.sh)
#   make check       all tests below (and copies out/BUILD-INFO to artifacts/)
#   make check-info  copy out/BUILD-INFO to artifacts/BUILD-INFO alone
#   make check-core  attn_core.h against the float64 model (host only)
#   make check-gcc   GCC testsuite files for Xattn (compile only)
#   make check-sim   bare-metal tests on QEMU and Spike
#   make check-recog recognizer: recognized loops vs plain loops, at run time
#   make check-xinsn-sim  a generated instruction run on QEMU and Spike (slow)
#   make check-three-way  Spike, QEMU and the host model agree bit for bit

PY      := .venv/bin/python
GCC     := $(CURDIR)/out/toolchain/bin/riscv64-unknown-elf-gcc
export TMPDIR := $(CURDIR)/build/tmp

all:
	scripts/build.sh

$(PY):
	python3 -m venv .venv
	$(PY) -m pip install -q numpy pytest

check: check-info check-core check-gcc check-sim check-recog

# The build these results belong to.  No BUILD-INFO (nothing built yet) is not
# an error: the tests that do not need a build still run.
check-info:
	@mkdir -p artifacts
	@if [ -f out/BUILD-INFO ]; then \
	  cp out/BUILD-INFO artifacts/BUILD-INFO; \
	  echo "artifacts/BUILD-INFO: $$(sed -n '2p' out/BUILD-INFO)"; \
	else \
	  echo "artifacts/BUILD-INFO: skipped, no out/BUILD-INFO (run scripts/build.sh)"; \
	fi

check-core: $(PY)
	$(PY) -m pytest -q tests/test_core.py

check-gcc:
	@mkdir -p $(TMPDIR)
	python3 tests/run_dg.py gcc/gcc/testsuite/gcc.target/riscv/xattn-*.c

check-sim: $(PY)
	$(MAKE) -C tests/baremetal CC=$(GCC) ARCH=rv64gc_xattn \
	  OUT=$(CURDIR)/build/baremetal-gcc PYTHON=$(CURDIR)/$(PY) check

check-recog:
	$(MAKE) -C tests/recog check

# Slow: applies examples/insns/mac.spec to the four trees, rebuilds them and
# runs the generated test on QEMU and Spike.  Needs scripts/build.sh first.
check-xinsn-sim: $(PY)
	XATTN_XINSN_SIM=1 $(PY) -m pytest -q tests/test_xinsn.py \
	  -k both_simulators

# Spike, QEMU and the host model, case by case, printing the largest
# absolute difference.  Needs scripts/build.sh first.
check-three-way: $(PY)
	XATTN_SIM=1 $(PY) -m pytest -q -s tests/test_three_way.py

.PHONY: all check check-info check-core check-gcc check-sim check-recog check-xinsn-sim check-three-way
