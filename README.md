# RISC-VInjection

RISC-VInjection adds custom instructions to the RISC-V toolchain, end to end. Two things live here:

1. **Xattn**, a complete custom extension whose one instruction, `attn`,
   computes a whole transformer attention block. It is implemented by hand
   in binutils, GCC (including a pass that finds attention in plain C),
   Spike and QEMU.
2. **A general method and script for any instruction**:
   `scripts/xinsn.py` takes a short spec (operands, C semantics, optional
   test), finds a free encoding and plugs the instruction into the same
   four projects, then tests it on both simulators.

## Xattn: multi-head self-attention in one instruction

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
| Compiler, core | GCC 16.2 | built in like `fma`: generic `__builtin_attn`, internal function `.ATTN`, the `attn` optab, the RTL code `(attn ...)`, and `__attn` in libgcc when the target lacks the instruction |
| Compiler, RISC-V | GCC 16.2 | default `-march=rv64gc_xattn`, `__riscv_xattn`, `__builtin_riscv_attn`, scheduling under every pipeline model |
| Compiler, automatic | GCC 16.2 | middle-end pass at `-O2`, no flags or headers: proves that C attention loops equal the instruction and replaces all five loop nests with **one** `.ATTN` call behind a runtime guard |
| Simulator | Spike | `--isa=rv64gc_xattn`, precise traps, disassembly |
| Simulator | QEMU | `-cpu rv64,xattn=on`, system and user mode, precise traps, `-d in_asm` |

All three executions (Spike, QEMU, host) run one shared definition,
`include/attn_core.h`, and agree bit for bit. That definition is checked
against an independent float64 model.

## Quick start

```bash
git clone https://github.com/Yash-Awasthi/RISC-VInjection.git && cd RISC-VInjection
scripts/setup.sh              # packages, submodules, patches, build, tests, demo
scripts/attncc.sh --run my_attention.c   # bare excerpt -> one attn, run on Spike
scripts/xattn.sh remove       # take Xattn out again (restore puts it back)
```

`setup.sh` does the steps below; each can be run on its own:

```bash
git submodule update --init gcc binutils spike qemu newlib
scripts/patches.sh apply      # Xattn patches on the pinned upstream commits
make                          # toolchain + simulators, about 15 minutes on 16 cores
make check                    # every test, a few minutes
```

[docs/walkthrough.md](docs/walkthrough.md) follows one excerpt through
every step, from C to the executed instruction.

Step-by-step instructions, package lists and troubleshooting are in
[docs/build-and-test.md](docs/build-and-test.md).

## From C to one instruction

```bash
out/toolchain/bin/riscv64-unknown-elf-gcc -O2 -fopt-info-loop -S demo/mha_plain.c -o - | grep -w attn
demo/mha_plain.c:53:23: optimized: multi-head self-attention (causal, biased) replaced with attn
	attn	s5,s4,a4,a5
```

`demo/mha_plain.c` is ordinary C: three projection loops, the per-head
softmax loops and the output projection, about 90 lines. Or call the
instruction directly, with no header:

```c
__builtin_attn (y, x, &weights, &cfg);   /* one attn with Xattn, libgcc __attn without */
```

`include/attn.h` wraps the same call as `attn_mha()` and also builds with
compilers that lack the builtin.

## Add any instruction

```
# examples/insns/vsum.spec
name   = vsum              # -> extension Xvsum, __builtin_riscv_vsum
inputs = 2                 # rs1, rs2
writes = rd
memory = yes
semantics:
  uint64_t s = 0;
  for (uint64_t i = 0; i < rs2; i++)
    s += LD32 (rs1 + 4 * i);
  return s;
test:
  static uint32_t a[3] = { 1, 2, 3 };
  CHECK (__builtin_riscv_vsum ((uintptr_t) a, 3) == 6);
```

```bash
scripts/xinsn.py new                             # asks for name, operands, C code, test; then all
scripts/xinsn.py all examples/insns/vsum.spec    # free opcode, edit 4 trees, rebuild, test on QEMU and Spike
scripts/xinsn.py list                            # custom instructions and their encodings
scripts/xinsn.py remove vsum                     # or remove 0x0e00302b; reverts the edits, rebuilds
```

Step by step: `find_opcodes.py --inputs 2` (free encodings, checked
against ~3000 known ones), `xinsn.py apply SPEC`, `scripts/build.sh
binutils gcc spike qemu`, `xinsn.py test SPEC`.

Any number of register inputs (0–3), a result or not, with or without
memory access. The C semantics are compiled into both simulators and the
host model, so they agree by construction. Each of the five example
shapes in `examples/insns/` was applied, built and passed on both
simulators.
[docs/new-instruction.md](docs/new-instruction.md) is the full guide: the
automated path, what each tree needs if you do it by hand, and how `attn`
goes beyond the generator (descriptors, precise traps, scheduling,
compiler recognition).

## Documentation

| Document | For |
|----------|-----|
| [docs/walkthrough.md](docs/walkthrough.md) | one excerpt from C to the executed instruction, every step, and removal |
| [docs/theory.md](docs/theory.md) | attention, multi-head, GQA, bf16, stable softmax; RISC-V formats, custom opcodes, vendor extensions |
| [docs/spec.md](docs/spec.md) | the normative definition: encoding, descriptors, exact semantics, exceptions |
| [docs/implementation.md](docs/implementation.md) | every file changed in binutils, GCC, Spike and QEMU, and why |
| [docs/recognizer.md](docs/recognizer.md) | how GCC proves C loops equal to `attn` |
| [docs/build-and-test.md](docs/build-and-test.md) | building and testing on a fresh machine |
| [docs/new-instruction.md](docs/new-instruction.md) | adding any instruction: shapes, encodings, the generator, the manual changes per tree, recognizing it in C |
| [docs/study.md](docs/study.md) | a reading path through the theory and the code |

## Layout

```
include/        attn_abi.h (interface), attn_core.h (definition), attn.h (C API)
demo/           mha_plain.c, the C code the compiler turns into one attn
artifacts/      that code compiled with attn and without: .s, .o, disassembly, GCC dumps, Spike run
patches/        the Xattn change to each upstream project, as git patches
gcc/ binutils/ spike/ qemu/ newlib/    upstream submodules (official mirrors)
scripts/        setup.sh, attncc.sh, artifacts.sh, xattn.sh, build.sh, patches.sh, find_opcodes.py, xinsn.py
examples/insns/ specs for xinsn.py: 1, 2 and 3 inputs, memory read, memory write
tests/          host model tests, bare-metal simulator tests, recognizer tests
tools/          independent float64 model and host runner
docs/           the documents above
```
