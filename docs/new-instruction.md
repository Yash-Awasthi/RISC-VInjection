# Adding any instruction

This guide takes an idea for a custom RISC-V instruction to a working
instruction in the assembler, the compiler and both simulators. One script
does the mechanical part for any instruction that fits the common shapes.
The rest of the guide explains what the script changes, so you can do the
same by hand and go further. `attn` is the worked example of going
further.

```
idea --> shape --> free encoding --> spec --> apply --> build --> test --> patches
         sec 1      sec 2             sec 3    sec 4                sec 4    sec 6
```

## 1. Decide the shape

Answer four questions. They map one-to-one onto the spec keys.

| Question | Spec key | Choices | Example |
|----------|----------|---------|---------|
| How many registers does it read? | `inputs` | 0, 1, 2, 3 | `mac` reads 3 |
| Does it write a result register? | `writes` | `rd` (result in rd) or `none` (rd is one more input) | `fill` writes none |
| Does it touch memory or have effects beyond its result? | `memory` | `yes` / `no` | `vsum` reads memory |
| What does it compute? | `semantics:` | a C function body | `return rs1 * rs2 + rs3;` |

The number of register fields fixes the encoding format:

| Registers named | Format | Fixed bits (MASK) | Examples |
|-----------------|--------|-------------------|----------|
| rd only | R, rs1 = rs2 = 0 | `0xfffff07f` | read a counter |
| rd, rs1 | R, rs2 = 0 | `0xfff0707f` | `bitrev` |
| rd, rs1, rs2 | R | `0xfe00707f` | `avgu`, `vsum`, `fill` |
| rd, rs1, rs2, rs3 | R4 | `0x0600707f` | `mac`, `attn` |

An operation with more operands than registers, like `attn` with its
dozen pointers and dimensions, passes the address of a descriptor in
memory instead. See section 5.2.

## 2. Find a free encoding

```bash
scripts/find_opcodes.py --inputs 3          # candidate R4 slots, best first
scripts/find_opcodes.py --inputs 2 --first
scripts/find_opcodes.py --inputs 1 --strict --json
```

The script loads every `MATCH_*`/`MASK_*` pair from binutils and Spike
(about 3000: all standard extensions and every upstream vendor's). It then
checks each slot of custom-0..3 with the exact overlap test
`(m1 ^ m2) & k1 & k2 == 0`.
- Default: a slot shared only with vendor extensions counts as free, and
  slots shared with fewer vendor instructions come first. Vendor
  extensions are enabled one at a time through `-march`.
- `--strict`: only slots nobody uses at all.

`xinsn.py` picks a strict slot automatically (`slot = auto`). Pin one
with `slot = custom-1:2:0` (major, funct3, funct7 or funct2).

## 3. Write the spec

```
name   = vsum                 # mnemonic; the extension becomes Xvsum
inputs = 2
writes = rd
memory = yes
slot   = auto
semantics:
  uint64_t s = 0;
  if (rs2 > 65536)
    ILLEGAL ();
  for (uint64_t i = 0; i < rs2; i++)
    s += LD32 (rs1 + 4 * i);
  return s;
test:
  static uint32_t a[100];
  for (int i = 0; i < 100; i++)
    a[i] = i * 2654435761u;
  uint64_t want = 0;
  for (int i = 0; i < 100; i++)
    want += a[i];
  CHECK (__builtin_riscv_vsum ((uintptr_t) a, 100) == want);
```

**`semantics:`** is the body of

```c
uint64_t <name>_exec (..., unsigned xlen, uint64_t rd, uint64_t rs1,
                      uint64_t rs2, uint64_t rs3, ...)
```

- Registers arrive zero-extended. Registers the format does not have
  read as 0.
- `rd` holds the destination register's old value. That only matters
  with `writes = none`, where rd is an input.
- `LD8 LD16 LD32 LD64 (addr)` and `ST8 ST16 ST32 ST64 (addr, value)`
  access guest memory with the simulator's normal translation and
  protection. A fault is precise: the instruction traps with the faulting
  address and can be re-executed.
- `ILLEGAL ()` raises an illegal-instruction exception. Use it for
  operand values you reserve.
- The return value goes to rd, truncated to XLEN and sign-extended on
  RV32.

The same body is compiled into Spike, QEMU and the host model, so the
three cannot disagree. Keep it deterministic: no globals, no host calls
apart from pure math functions.

**`test:`** (optional) is the body of `main` in a bare-metal program,
compiled with `-march=rv64gc_x<name>` and run on QEMU and on Spike.
`CHECK (cond)` reports a failure and makes the run fail. Without a
`test:` block, an instruction that writes rd from registers only is
tested automatically against the host model on 64 vectors (27 edge
values and 37 random ones). Memory instructions and instructions that
write no register need a `test:` block.

The spec is checked before anything is written: an unknown key (a typo
like `writse = rd`), a missing `name`, `semantics:` or `test:` block
where one is required, and a value outside the documented range each
stop the run with exit code 1 and a message naming the spec file and
the expected text.

`examples/insns/` has one spec for each shape: `bitrev` (1 input),
`avgu` (2), `mac` (3), `vsum` (memory read, result), `fill` (memory
write, no result).

## 4. Apply, build, test

```bash
scripts/xinsn.py show  examples/insns/vsum.spec   # encoding and files it would touch
scripts/xinsn.py apply examples/insns/vsum.spec   # edits the trees; safe to repeat
scripts/build.sh binutils gcc spike qemu          # incremental, a few minutes
scripts/xinsn.py test  examples/insns/vsum.spec
```

To take it out again without rebuilding: `scripts/xinsn.py remove vsum
--no-rebuild` edits the four trees back and leaves them clean
(`git -C gcc status --porcelain` is empty); without the flag `remove`
also runs `scripts/build.sh` and checks that the assembler now rejects
the mnemonic.

```
qemu  vsum: all checks passed
spike vsum: all checks passed
objdump: 3 vsum instruction(s) in the test
```

`test` also checks with objdump that the program really contains the
instruction, so a builtin that silently did nothing would be caught.

Using it afterwards:

| Tool | How |
|------|-----|
| assembler | `vsum a0, a1, a2` with `-march=rv64gc_xvsum` |
| C | `__builtin_riscv_vsum (addr, count)`; `#ifdef __riscv_xvsum` |
| Spike | `spike --isa=rv64gc_xvsum prog.elf` |
| QEMU | `qemu-system-riscv64 -cpu rv64,xvsum=on ...`, `qemu-riscv64 -cpu rv64,xvsum=on prog` |

Several instructions can live side by side. Apply them one after
another: each `apply` sees the encodings added before it and picks a
different slot.

## 5. What `apply` does, and how to do it by hand

Every change uses the same anchors as the hand-written Xattn patches.
`git -C <tree> show` on the `xattn` branch shows the real thing for
`attn`.

### 5.1 The mechanical part

**binutils**

| File | Addition |
|------|----------|
| `include/opcode/riscv-opc.h` | `#define MATCH_<N>` / `MASK_<N>`, `DECLARE_INSN(<n>, ...)` |
| `include/opcode/riscv.h` | `INSN_CLASS_X<N>` |
| `opcodes/riscv-opc.c` | `{"<n>", 0, INSN_CLASS_X<N>, "d,s,t", MATCH_<N>, MASK_<N>, match_opcode, 0}`. Operand letters: `d` rd, `s` rs1, `t` rs2, `r` rs3 |
| `bfd/elfxx-riscv.c` | `{"x<n>", ISA_SPEC_CLASS_DRAFT, 1, 0, 0}` in the vendor table; a case in `riscv_multi_subset_supports` and in `riscv_multi_subset_supports_ext` |
| `gas/testsuite/gas/riscv/x-<n>.{s,d}` | assembler/disassembler test |

**GCC**

| File | Addition |
|------|----------|
| `config/riscv/riscv-ext-x<n>.def` | `DEFINE_RISCV_EXT` for `x<n>`; listed in `riscv-ext.def` and `t-riscv`, then `riscv-ext.opt` and `doc/riscv-ext.texi` regenerated |
| `config/riscv/<n>.md` | `define_insn "riscv_<n>_<mode>"`. A pure instruction is `(set rd (unspec:X [inputs] UNSPEC_X<N>))`, so GCC may combine, move or delete it like arithmetic. With memory effects, or with no result, it is `unspec_volatile` plus `(clobber (mem:BLK (scratch)))`, so it stays in place and in order with all other memory accesses |
| `config/riscv/riscv.md` | the unspec constant, `(include "<n>.md")` |
| `config/riscv/riscv-ftypes.def` | the C prototype, if new |
| `config/riscv/riscv-builtins.cc`, `<n>.def` | `AVAIL (<n>32/<n>64)` and one builtin per XLEN, both named `__builtin_riscv_<n>` |

**Spike**: `riscv/x<n>.cc` (an `extension_t` with the decoder entry and
disassembly), `riscv/<n>_core.h` (the semantics), one line in
`riscv/extensions.cc`, and one in `riscv/riscv.mk.in`.

**QEMU**: `target/riscv/x<n>.decode` (decodetree pattern),
`tcg/insn_trans/trans_x<n>.c.inc` (checks the CPU flag, calls the
helper, writes rd), `tcg/<n>_helper.c` + `<n>_core.h`, the CPU flag and
property in `cpu.c`, `cpu_cfg.h` and `cpu_cfg_fields.h.inc`, the helper
prototype, and the meson and decoder-table entries.

### 5.2 Beyond the generator

These are the decisions `attn` needed that a spec cannot express. Each
row points to where the Xattn patches do it.

| Need | Technique | In Xattn |
|------|-----------|----------|
| more operands than four registers | pass pointers to descriptor structs in memory; define the layout once in a header shared by C, the simulators and the tests | `include/attn_abi.h` |
| large or floating-point computation | one definition file with memory callbacks, compiled into every simulator; fix the operation order and forbid FMA contraction so results are bit-identical | `include/attn_core.h` |
| a trap in the middle of a long operation | load every input before the first store, then re-execute after the fault; keep no resources across loads, because a fault leaves by exception or longjmp | `attn_execute`, Spike/QEMU scratch buffers |
| the scheduler must know the instruction | give it its own insn type with a reservation every pipeline model sees (a type without one crashes `riscv_sched_variable_issue`) | `xattn.md` |
| an encoding that coexists with every vendor | `find_opcodes.py --strict` | custom-3 funct3 1 funct2 3 |
| the compiler should use it without a builtin | a middle-end GIMPLE pass that proves equivalence, emits an internal function, and an optab the target implements (section 5.3) | `tree-ssa-loop-attn.cc` |
| a C API that also works without the extension | `#ifdef __riscv_x<n>` builtin, else the shared definition in software | `include/attn.h` |

### 5.3 Teaching the compiler to find your instruction

Recognizing an instruction in ordinary C is worth it when it replaces a
lot of code. `attn` replaces five loop nests. The approach generalizes:

1. **Fix the semantics exactly**, down to the order of floating-point
   operations. Without that, no rewrite can be proven correct.
2. **Run early in the loop pipeline**, after `pass_tree_loop_init`, before
   distribution, interchange, unrolling and vectorization reshape the
   loops. Register the pass from the target in `riscv-passes.def`, so the
   middle end stays untouched.
3. **Evaluate addresses symbolically.** Reduce every load and store to
   `base + polynomial(dimensions, loop counters)` and bound every
   intermediate, so integer casts are provably exact.
4. **Match every statement**, not just the interesting ones. Each float
   operation, load, store and call in the region must be accounted for.
   A partial match is how unsound recognizers happen.
5. **Decide control flow** under explicit assumptions on the dimensions.
   Then check those assumptions at run time and keep the original code
   as the fallback.
6. **Prove the memory side**: outputs do not alias inputs, and scratch
   buffers are local and never read afterwards.
7. **Test both paths at run time**: recognized vs. not recognized on the
   same inputs, plus cases that fail the guard.

`docs/recognizer.md` walks through each step for `attn`, and
`tree-ssa-loop-attn.cc` is the code. Its helpers (polynomials, `analyze_loop`,
`walk_body`, `decide`, `find_region`, `materialize`) do not depend on
attention and can be reused.

## 6. Keep the change as patches

```bash
git -C gcc commit -am "RISC-V: add Xfoo"     # same in binutils, spike, qemu
scripts/patches.sh export                    # writes patches/<tree>/*.patch
```

The submodules stay pinned to official upstream commits, and the change
lives in `patches/`. `scripts/patches.sh apply` reproduces it on a fresh
clone.

## 7. Limits

- Register operands are integer registers. Floating-point register
  operands and immediates need a hand-written pattern and decoder entry.
- The generated instruction has insn type `arith`, so the scheduler
  assumes one cycle of latency.
- `apply` does not record what it added. Undo it with
  `git checkout -- . && git clean -f` in each tree.

## 8. Failure modes

### 8.1 Encoding exhaustion per major opcode

A major opcode holds a fixed number of slots: 1024 for R (8 funct3 x 128
funct7) and 32 for R4 (8 funct3 x 4 funct2), so the four custom opcodes
give 4096 R slots and 128 R4 slots. `find_opcodes.py` reports what is
left; `--strict` counts a slot shared with a vendor extension as taken.

```bash
scripts/find_opcodes.py --inputs 2 --major custom-0 --strict --first
```
```
no free R slot
```

custom-0 has no R slot left, and the script exits 1. For R4 the same
search answers with the remaining count on stderr and one slot on stdout:

```bash
scripts/find_opcodes.py --inputs 3 --major custom-3 --strict --first
```
```
format R4, 3006 known encodings, 3 of 32 slots free
custom-3 funct3=3 funct2=2      MATCH=0x0400307b MASK=0x0600707f
```

custom-0 has no R4 slot either:

```bash
scripts/find_opcodes.py --inputs 3 --major custom-0 --strict --first
```
```
no free R4 slot
```

When the last strict slot goes, `slot = auto` stops instead of writing a
colliding encoding: `no R4 slot is free of every known encoding`.

### 8.2 Conflicts with other vendor extensions

Without `--strict`, a slot shared only with vendor extensions counts as
free, and the slots with the fewest vendor instructions come first.
`--all` shows the ones at the end of the list:

```bash
scripts/find_opcodes.py --inputs 3 --major custom-3 --all | tail -3
```
```
custom-3 funct3=0 funct2=0      MATCH=0x0000007b MASK=0x0600707f shared with 25 vendor insns (cv_add_h,cv_sub_h,cv_avg_h)
custom-3 funct3=1 funct2=0      MATCH=0x0000107b MASK=0x0600707f shared with 25 vendor insns (cv_add_b,cv_sub_b,cv_avg_b)
custom-3 funct3=7 funct2=0      MATCH=0x0000707b MASK=0x0600707f shared with 25 vendor insns (cv_add_sci_b,cv_sub_sci_b,cv_avg_sci_b)
```

A shared slot still works because `-march` enables one vendor extension
at a time, so two instructions that decode the same word are never
enabled together. `--strict` refuses those slots, and `verify` refuses a
spec pinned to one. With `slot = custom-3:0:0`, saved as
`C:/tmp/fm/shared.spec`:

```
name   = sharer
inputs = 3
writes = rd
memory = no
slot   = custom-3:0:0
semantics:
  return rs1 + rs2 + rs3;
```

```bash
scripts/xinsn.py verify C:/tmp/fm/shared.spec
```
```
sharer: format R4, custom-3:0:0, MATCH=0x0000007b MASK=0x0600707f, -march=..._xsharer
C:/tmp/fm/shared.spec: custom-3:0:0 collides with cv_abs_h, cv_add_h, cv_and_h, cv_avg_h, cv_avgu_h, cv_dotsp_h, cv_dotup_h, cv_dotusp_h, cv_extract_h, cv_max_h, cv_maxu_h, cv_min_h, cv_minu_h, cv_or_h, cv_pack, cv_sdotsp_h, cv_sdotup_h, cv_sdotusp_h, cv_shuffle2_h, cv_shuffle_h, cv_sll_h, cv_sra_h, cv_srl_h, cv_sub_h, cv_xor_h already in the trees; pick a free slot
```

`verify` exits 1 and names every vendor instruction in the slot.

### 8.3 Attribute naming

The name becomes an extension name (`x<name>`), so it must match
`[a-z][a-z0-9]{1,15}`. That keeps `-march=..._x<name>`,
`__riscv_x<name>`, `ext_x<name>`, `-cpu rv64,x<name>=on` and the ELF
attribute `x<name>1p0` valid. A name that cannot form an extension stops
before any encoding is chosen. With `name = MAC`:

```bash
scripts/xinsn.py show C:/tmp/fm/MAC.spec
```
```
C:/tmp/fm/MAC.spec: name 'MAC' must match [a-z][a-z0-9]{1,15}
```

A name whose extension already exists fails later, because its ELF
attribute tag is taken. With `name = ventanacondops`:

```
name   = ventanacondops
inputs = 2
writes = rd
memory = no
slot   = auto
semantics:
  return rs1 + rs2;
```

```bash
scripts/xinsn.py verify C:/tmp/fm/vend.spec
```
```
ventanacondops: format R, custom-1 funct3=3 funct7=3, MATCH=0x0600302b MASK=0xfe00707f, -march=..._xventanacondops
ok: 3006 known encodings checked; the slot collides with none
C:/tmp/fm/vend.spec: the ELF attribute xventanacondops1p0 is taken; xventanacondops is an existing vendor extension
```

Both exits are 1.
