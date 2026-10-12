# Xattn: build everything and run every check.
#
#   make             build toolchain and simulators (scripts/build.sh)
#   make check       all tests below
#   make check-core  attn_core.h against the float64 model (host only)
#   make check-gcc   GCC testsuite files for Xattn (compile only)
#   make check-sim   bare-metal tests on QEMU and Spike
#   make check-recog recognizer: recognized loops vs plain loops, at run time

PY      := .venv/bin/python
GCC     := $(CURDIR)/out/toolchain/bin/riscv64-unknown-elf-gcc
export TMPDIR := $(CURDIR)/build/tmp

all:
	scripts/build.sh

$(PY):
	python3 -m venv .venv
	$(PY) -m pip install -q numpy pytest

check: check-core check-gcc check-sim check-recog

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

.PHONY: all check check-core check-gcc check-sim check-recog
