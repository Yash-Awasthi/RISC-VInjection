# Bare-metal attn tests for Spike and QEMU virt.
#   make CC=clang          (encoding via .insn)
#   make CC=riscv64-unknown-elf-gcc ARCH=rv64gc_xattn   (builtin)

REPO    := $(abspath ../..)
OUT     ?= $(REPO)/build/baremetal
CC      ?= clang
ARCH    ?= rv64gc
PYTHON  ?= $(REPO)/.venv/bin/python
SPIKE   ?= $(REPO)/out/spike/bin/spike
QEMU    ?= $(REPO)/build/qemu/qemu-system-riscv64
export PATH := $(REPO)/out/host/bin:$(PATH)

ifneq ($(findstring clang,$(CC)),)
TARGET  := --target=riscv64-unknown-elf -fuse-ld=lld
else
NOWARN  := -Wl,--no-warn-rwx-segments
endif
CFLAGS  := $(TARGET) -march=$(ARCH) -mabi=lp64d -mcmodel=medany -O2 -g \
	   -ffreestanding -fno-builtin -nostdlib -nostartfiles -Wall \
	   -I$(REPO)/include -I$(OUT)
LDFLAGS := -T link.ld -static $(NOWARN)

QEMU_USER ?= $(dir $(QEMU))qemu-riscv64

all: $(OUT)/attn_test-spike.elf $(OUT)/attn_test-qemu.elf \
     $(OUT)/noext_test-spike.elf $(OUT)/noext_test-qemu.elf \
     $(OUT)/attn_test-linux.elf

$(OUT)/cases.h: gen_cases.py $(REPO)/include/attn_core.h $(REPO)/tools/attn_model.py
	@mkdir -p $(OUT)
	$(PYTHON) gen_cases.py $@

$(OUT)/%-spike.elf: %.c bm.c crt.S link.ld $(OUT)/cases.h
	$(CC) $(CFLAGS) -DBM_SPIKE $(LDFLAGS) crt.S bm.c $< -o $@

$(OUT)/%-qemu.elf: %.c bm.c crt.S link.ld $(OUT)/cases.h
	$(CC) $(CFLAGS) $(LDFLAGS) crt.S bm.c $< -o $@

$(OUT)/%-linux.elf: %.c bm.c crt-linux.S $(OUT)/cases.h
	$(CC) $(CFLAGS) -DBM_LINUX -static $(NOWARN) crt-linux.S bm.c $< -o $@

QEMU_RUN = $(QEMU) -M virt -bios none -nographic -monitor none -serial stdio

check: all
	$(QEMU_RUN) -cpu rv64,xattn=on -kernel $(OUT)/attn_test-qemu.elf
	$(QEMU_RUN) -cpu rv64 -kernel $(OUT)/noext_test-qemu.elf
	$(SPIKE) --isa=rv64gc_xattn $(OUT)/attn_test-spike.elf
	$(SPIKE) --isa=rv64gc $(OUT)/noext_test-spike.elf
	$(QEMU_USER) -cpu rv64,xattn=on $(OUT)/attn_test-linux.elf

check-qemu: all
	$(QEMU_RUN) -cpu rv64,xattn=on -kernel $(OUT)/attn_test-qemu.elf
	$(QEMU_RUN) -cpu rv64 -kernel $(OUT)/noext_test-qemu.elf

clean:
	rm -rf $(OUT)

.PHONY: all check check-qemu clean
