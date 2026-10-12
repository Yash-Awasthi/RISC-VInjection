# RISC-V Xattn: multi-head self-attention in one instruction

```
Y = concat_j softmax(Q_j K_j^T * scale + M) V_j  Wo + bo,   Q = X Wq + bq, K = X Wk + bk, V = X Wv + bv

attn  a3, a0, a1, a2        # 0x66b516fb: Y, X, &weights, &config
```

This repository adds a custom RISC-V extension, **Xattn**. Its single
instruction, `attn`, computes a complete transformer attention block:
- the Q/K/V projections with biases;
- scaled dot-product attention for every head, with optional causal
  masking, an additive mask, grouped-query attention and an explicit scale;
- the output projection.

Inputs can be binary32 or bfloat16, with binary32 arithmetic throughout.

The extension is implemented end to end on current upstream sources:

| Layer | Project | What works |
|-------|---------|------------|
| Assembler, disassembler | binutils 2.47 branch | `attn` under `-march=..._xattn`, ELF attribute `xattn1p0`, objdump |
| Compiler | GCC 16.2 | `-march=..._xattn`, `__riscv_xattn`, `__builtin_riscv_attn`, scheduling under every pipeline model |
| Compiler, automatic | GCC 16.2 | `-mattn-recognize`: proves that C attention loops equal the instruction and replaces all five loop nests with **one** `attn`, behind a runtime guard |
| Simulator | Spike | `--isa=rv64gc_xattn`, precise traps, disassembly |
| Simulator | QEMU | `-cpu rv64,xattn=on`, system and user mode, precise traps, `-d in_asm` |

All three executions (Spike, QEMU, host) run one shared definition,
`include/attn_core.h`, and agree bit for bit. That definition is checked
against an independent float64 model.

## Quick start

```bash
git clone https://github.com/Yash-Awasthi/RISC-V_Injection.git && cd RISC-V_Injection
git submodule update --init gcc binutils spike qemu newlib
scripts/patches.sh apply      # Xattn patches on the pinned upstream commits
make                          # toolchain + simulators, about 15 minutes on 16 cores
make check                    # every test, a few minutes
```

Step-by-step instructions, package lists and troubleshooting are in
[docs/build-and-test.md](docs/build-and-test.md).

## From C to one instruction

```bash
out/toolchain/bin/riscv64-unknown-elf-gcc -march=rv64gc_xattn -O2 -fno-math-errno \
    -mattn-recognize -fopt-info-loop -S demo/mha_plain.c -o - | grep -w attn
demo/mha_plain.c:53:23: optimized: multi-head self-attention (causal, biased) replaced with attn
	attn	s6,s9,a5,a4
```

`demo/mha_plain.c` is ordinary C: three projection loops, the per-head
softmax loops and the output projection, about 90 lines. Or call the
instruction directly through `include/attn.h`:

```c
#include "attn.h"
attn_mha (y, x, &weights, &cfg);   /* one attn with Xattn, attn_core.h without */
```

## Add your own instruction

```bash
scripts/find_opcodes.py --inputs 2            # free encodings, checked against ~3000 known ones
scripts/xinsn.py apply examples/insns/mac.spec   # into binutils, GCC, Spike and QEMU
scripts/build.sh binutils gcc spike qemu
scripts/xinsn.py test examples/insns/mac.spec    # runs on QEMU and Spike
```

See [docs/new-instruction.md](docs/new-instruction.md).

## Documentation

| Document | For |
|----------|-----|
| [docs/theory.md](docs/theory.md) | attention, multi-head, GQA, bf16, stable softmax; RISC-V formats, custom opcodes, vendor extensions |
| [docs/spec.md](docs/spec.md) | the normative definition: encoding, descriptors, exact semantics, exceptions |
| [docs/implementation.md](docs/implementation.md) | every file changed in binutils, GCC, Spike and QEMU, and why |
| [docs/recognizer.md](docs/recognizer.md) | how GCC proves C loops equal to `attn` |
| [docs/build-and-test.md](docs/build-and-test.md) | building and testing on a fresh machine |
| [docs/new-instruction.md](docs/new-instruction.md) | the opcode finder and the instruction generator |
| [docs/study.md](docs/study.md) | a reading path through the theory and the code |

## Layout

```
include/        attn_abi.h (interface), attn_core.h (definition), attn.h (C API)
demo/           mha_plain.c, the C code the compiler turns into one attn
patches/        the Xattn change to each upstream project, as git patches
gcc/ binutils/ spike/ qemu/ newlib/    upstream submodules (official mirrors)
scripts/        build.sh, patches.sh, find_opcodes.py, xinsn.py
examples/insns/ instruction specs for xinsn.py (1, 2 and 3 inputs)
tests/          host model tests, bare-metal simulator tests, recognizer tests
tools/          independent float64 model and host runner
docs/           the documents above
```
