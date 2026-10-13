# Runtime check of the attention recognizer on QEMU and Spike.

REPO   := $(abspath ../..)
OUT    ?= $(REPO)/build/recog-test
BIN    ?= $(REPO)/out/toolchain/bin
CC     := $(BIN)/riscv64-unknown-elf-gcc
SPIKE  ?= $(REPO)/out/spike/bin/spike
QEMU   ?= $(REPO)/build/qemu/qemu-system-riscv64
BM     := $(REPO)/tests/baremetal
export PATH := $(REPO)/out/host/bin:$(PATH)
export TMPDIR := $(REPO)/build/tmp

CFLAGS := -march=rv64gc_xattn -mabi=lp64d -mcmodel=medany -O2 -g \
	  -ffp-contract=off -Wall -I$(BM) -I$(REPO)/include
LDFLAGS := -nostartfiles -T $(BM)/link.ld -static -Wl,--no-warn-rwx-segments

all: $(OUT)/recog-qemu.elf $(OUT)/recog-spike.elf

# Each source is built twice: recognized (one attn) and as plain loops.
T := $(REPO)/gcc/gcc/testsuite/gcc.target/riscv
SRC_mha := $(REPO)/demo/mha_plain.c
SRC_mha2 := $(T)/xattn-recog-2.c
SRC_mha3 := $(T)/xattn-recog-3.c
FNS := mha mha2 mha3
OBJS := $(foreach f,$(FNS),$(OUT)/$(f)_attn.o $(OUT)/$(f)_loops.o) \
	$(OUT)/mha_builtin.o

$(OUT)/%_attn.o:
	@mkdir -p $(OUT) $(TMPDIR)
	$(CC) $(CFLAGS) -Dmha=$* -fopt-info-loop-optimized -c $(SRC_$*) -o $@
	@test "$$($(BIN)/riscv64-unknown-elf-objdump -d $@ | grep -cw attn)" = 1

$(OUT)/%_loops.o:
	@mkdir -p $(OUT) $(TMPDIR)
	$(CC) $(CFLAGS) -Dmha=$*_loops -fno-tree-loop-attn -c $(SRC_$*) -o $@

# __builtin_attn without Xattn: a call to __attn in libgcc, no attn.
$(OUT)/mha_builtin.o: mha_builtin.c
	@mkdir -p $(OUT) $(TMPDIR)
	$(CC) $(CFLAGS) -march=rv64gc -c $< -o $@
	@test "$$($(BIN)/riscv64-unknown-elf-objdump -dr $@ | grep -cw attn)" = 0
	@$(BIN)/riscv64-unknown-elf-objdump -dr $@ | grep -q 'R_RISCV_CALL_PLT.*__attn'

$(OUT)/recog-%.elf: recog_test.c $(OBJS) $(BM)/bm.c $(BM)/crt.S
	$(CC) $(CFLAGS) $(if $(filter spike,$*),-DBM_SPIKE) $(LDFLAGS) \
	  $(BM)/crt.S $(BM)/bm.c recog_test.c $(OBJS) -lm -lc -lgcc -o $@

check: all
	$(QEMU) -M virt -bios none -nographic -monitor none -serial stdio \
	  -cpu rv64,xattn=on -kernel $(OUT)/recog-qemu.elf
	$(SPIKE) --isa=rv64gc_xattn $(OUT)/recog-spike.elf

clean:
	rm -rf $(OUT)

.PHONY: all check clean
