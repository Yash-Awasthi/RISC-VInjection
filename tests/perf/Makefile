# Per-shape measurement of the recognizer, on QEMU and Spike.
#   make            build both images
#   make check      run them, writing build/perf/<sim>.csv
#
# mha_attn is demo/mha_plain.c at plain -O2 (one attn plus the guard);
# mha_loops is the same file with -fno-tree-loop-attn.

REPO   := $(abspath ../..)
OUT    ?= $(REPO)/build/perf
BIN    ?= $(REPO)/out/toolchain/bin
CC     := $(BIN)/riscv64-unknown-elf-gcc
OD     := $(BIN)/riscv64-unknown-elf-objdump
SPIKE  ?= $(REPO)/out/spike/bin/spike
QEMU   ?= $(REPO)/build/qemu/qemu-system-riscv64
BM     := $(REPO)/tests/baremetal

CFLAGS := -march=rv64gc_xattn -mabi=lp64d -mcmodel=medany -O2 -g \
	  -ffp-contract=off -Wall -I$(BM) -I$(REPO)/include
LDFLAGS := -nostartfiles -T $(BM)/link.ld -static -Wl,--no-warn-rwx-segments
QEMU_RUN = $(QEMU) -M virt -bios none -nographic -monitor none -serial stdio

all: $(OUT)/perf-qemu.elf $(OUT)/perf-spike.elf

$(OUT)/mha_attn.o: $(REPO)/demo/mha_plain.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -Dmha=mha_attn -c $< -o $@
	@test "$$($(OD) -d $@ | grep -cw attn)" = 1

$(OUT)/mha_loops.o: $(REPO)/demo/mha_plain.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -Dmha=mha_loops -fno-tree-loop-attn -c $< -o $@
	@test "$$($(OD) -d $@ | grep -cw attn)" = 0

$(OUT)/perf-%.elf: bench.c $(OUT)/mha_attn.o $(OUT)/mha_loops.o \
		   $(BM)/bm.c $(BM)/crt.S $(BM)/link.ld
	$(CC) $(CFLAGS) $(if $(filter spike,$*),-DBM_SPIKE) $(LDFLAGS) \
	  $(BM)/crt.S $(BM)/bm.c bench.c $(OUT)/mha_attn.o $(OUT)/mha_loops.o \
	  -lm -lc -lgcc -o $@

check: all
	$(SPIKE) --isa=rv64gc_xattn $(OUT)/perf-spike.elf > $(OUT)/spike.csv
	$(QEMU_RUN) -cpu rv64,xattn=on -icount shift=0,sleep=off -kernel $(OUT)/perf-qemu.elf > $(OUT)/qemu.csv
	@echo "build/perf/spike.csv and build/perf/qemu.csv written"

clean:
	rm -rf $(OUT)

.PHONY: all check clean


