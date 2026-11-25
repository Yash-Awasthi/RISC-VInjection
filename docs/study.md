# Study guide

A path through the material, in the order that makes each step easy.
Each stage lists what to read and the file in this repository where you
can see it applied.

## Stage 1: the computation (1–2 days)

1. Vaswani et al., *Attention Is All You Need* (NeurIPS 2017), sections
   3.2–3.2.2: scaled dot-product and multi-head attention.
2. Jay Alammar, *The Illustrated Transformer* (blog), for the picture of
   Q, K, V and heads.
3. Ainslie et al., *GQA: Training Generalized Multi-Query Transformer
   Models from Multi-Head Checkpoints* (2023): grouped-query attention.
4. Read `tools/attn_model.py::reference` (40 lines of NumPy), then
   `include/attn_core.h::attn_execute`, which does the same thing in C in
   the order the instruction defines.

Exercise: change a weight in `tests/test_core.py` and predict which
outputs move.

**Answer.** A change in `wq` moves Q, so the changed Q column re-enters every score, every softmax row and every output element. With `Case(rng, n=5, e=8, h=1)` and `wq[0,0] += 1.0`, 40 of 40 outputs change: one Wq column feeds all five rows and each row mixes all five keys.
`.venv/Scripts/python.exe -c 'import sys, numpy as np; sys.path.insert(0, "tools"); import attn_model as am; c = am.Case(np.random.default_rng(20261126), n=5, e=8, h=1); b = am.round_dtype(c.expected(), c.out_dt); c.wq[0, 0] += 1.0; print(np.count_nonzero(b != am.round_dtype(c.expected(), c.out_dt)), "of", b.size)'` -> `40 of 40`

## Stage 2: floating point (half a day)

1. Goldberg, *What Every Computer Scientist Should Know About
   Floating-Point Arithmetic* (1991), sections on rounding and on why
   addition is not associative.
2. Google's bfloat16 description (cloud.google.com/tpu/docs/bfloat16),
   and why the exponent width matters more than the mantissa for deep
   learning.
3. Read `attn_bf16_from_f32` in `include/attn_core.h` (round to nearest
   even in four lines) and the `fp-contract` pragma at its top.

Exercise: on a host with FMA, remove the pragma, build
`tests/host/attn_host.c` with `-O2 -march=native`, and diff its output
against the build with the pragma. The last bits differ: that is why the
pragma exists.

**Answer.** With `a = -(1+2^-12)`, `b = 1+2^-12` and `c = 1+2^-11`, the float32 product rounds to `-1.0004883`, the separate add gives `0.0`, and the exactly fused result rounds to `-2^-24` (`0xb3800000`). The tempting pair `(1+2^-12)(1-2^-12) - 1` separates nothing: `1-2^-24` lies exactly on the float32 grid just below 1.0, so separate and fused both give `-2^-24`, measured. `include/attn_core.h:26-29` turns contraction off because `docs/spec.md:84` requires every product and sum to be rounded separately. bf16 rounds `1+2^-8` to `0x3f80`: the value is a tie and the even mantissa wins.
`.venv/Scripts/python.exe -c 'import math, sys, numpy as np; sys.path.insert(0, "tools"); import attn_model as am; f = np.float32; a = f(-(1 + 2**-12)); b = f(1 + 2**-12); c = f(1 + 2**-11); sep = f(f(a * b) + c); fus = f(math.fma(float(a), float(b), float(c))); print("sep", sep, "fused", fus, "hex", fus.tobytes()[::-1].hex(), "bf16", hex(int(am.bf16_bits(np.array([f(1 + 2**-8)]))[0])))'` -> `sep 0.0 fused -5.9604645e-08 hex b3800000 bf16 0x3f80`

## Stage 3: RISC-V encoding (1 day)

1. *The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA*:
   chapter "RV32I Base Integer Instruction Set" (formats), the opcode map
   table, and chapter "Extending RISC-V" (custom opcodes, non-standard
   extensions).
2. Volume II (privileged): `mcause`, `mtval`, `mepc`, `mret`. Enough to
   read `tests/baremetal/crt.S`.
3. Run `scripts/find_opcodes.py --inputs 3 --all` and pick three slots by
   hand. Check the `(m1 ^ m2) & k1 & k2` rule on paper.

**Answer.** The run reports `format R4, 3006 known encodings, 128 of 128 slots free`; three free slots are custom-3 funct3=3 funct2=2 (`MATCH=0x0400307b`), funct3=3 funct2=3 (`MATCH=0x0600307b`) and funct3=5 funct2=3 (`MATCH=0x0600507b`), all with `MASK=0x0600707f`. Their pairwise `(m1 ^ m2) & k1 & k2` values are `0x02000000`, `0x02006000` and `0x00006000`, and in slot order against attn's `0x0600107b` they are `0x02002000`, `0x00002000` and `0x00004000`; none is zero, so no word matches two encodings. `encode(13, 10, 11, 12)` is `0x66b516fb`, matching `docs/spec.md:30`.
`.venv/Scripts/python.exe scripts/find_opcodes.py --inputs 3 --all 2>&1 | head -4` -> `format R4, 3006 known encodings, 128 of 128 slots free` then the `MATCH=0x0400307b`, `MATCH=0x0600307b` and `MATCH=0x0600507b` lines.

## Stage 4: binutils (half a day)

1. Read `opcodes/riscv-opc.c` around the vendor tables, and the operand
   letters at the top of `gas/config/tc-riscv.c` (`d`, `s`, `t`, `r`).
2. `git -C binutils show xattn` shows the whole Xattn change: 13 lines
   plus tests.

**Answer.** The owned patch adds 50 lines across 9 files: 13 non-test lines (`bfd/elfxx-riscv.c` 5, `include/opcode/riscv-opc.h` 4, `include/opcode/riscv.h` 1, `opcodes/riscv-opc.c` 3) plus 37 test lines. So "13 lines plus tests" is exact when lines means the source change; counting every added line gives 50, of which `opcodes/riscv-opc.c` contributes 3.
`git apply --numstat patches/binutils/0001-RISC-V-add-the-Xattn-vendor-extension.patch` -> nine rows from `5 0 bfd/elfxx-riscv.c` to `3 0 opcodes/riscv-opc.c`, 50 added lines in total.

## Stage 5: GCC (several days, the deepest part)

1. *GCC Internals* manual (gcc.gnu.org/onlinedocs/gccint/): "Passes and
   Files of the Compiler", "GIMPLE", "Tree SSA" (especially SSA form and
   PHI nodes), "Loop Analysis and Representation", "Machine Descriptions"
   (`define_insn`, `unspec`, `unspec_volatile`), and "Target Description
   Macros and Functions".
2. Dump the pipeline yourself:
   `gcc -O2 -fdump-tree-all -S demo/mha_plain.c`. Open the `loopinit`
   dump and find the five nests.
3. Read in order: `xattn.md` (30 lines), `riscv-builtins.cc` (the AVAIL
   lines), `expand_ATTN` in `internal-fn.cc`, then `tree-ssa-loop-attn.cc`:
   `poly`, `expand_int`, `analyze_loop`, `walk_body`, `match_matmul`,
   `match_attention`, `account`, `find_region`, `rewrite`.
4. Related work inside GCC: `gimple-crc-optimization.cc` (GCC 15), which
   recognizes CRC loops and verifies them by symbolic execution. It is the
   closest relative of the attention recognizer.

Exercise: write a variant of `demo/mha_plain.c` that the recognizer
rejects, read the reason with `-fopt-info-loop-missed`, and decide
whether the rejection protects correctness.

**Answer.** A variant that moves the sum of `expf` values into a second loop over `p` is refused: the recognizer matches the attention nest statement by statement and needs `expf (p[j] - mx)` stored back to `p[j]` and summed into `l` in the same loop, and every statement in the five nests must be accounted for (`docs/recognizer.md:159-174`). The extra loop is also a statement the match does not know, and a region may not contain other loops (`docs/recognizer.md:199`). `-fopt-info-loop-missed` was not run here: this unit has no patched GCC build, so the reason is read from the pass description, not observed.
`grep -n "accounted for" docs/recognizer.md` -> `170:Then every statement in all five nests must be accounted for. Each`

## Stage 6: simulators (1–2 days)

1. Spike: `riscv/extension.h`, `riscv/processor.cc` (how `--isa`
   extensions are registered), `riscv/mmu.h` (`load`, `store`, traps as
   exceptions).
2. QEMU: `docs/devel/decodetree.rst`, `docs/devel/tcg.rst`, then
   `target/riscv/tcg/insn_trans/trans_xlrbr.c.inc` as the smallest vendor
   example, then `trans_xattn.c.inc` and `attn_helper.c`.
3. Why a fault in the middle of `attn` is safe: read section 5 of
   `docs/spec.md`, then `load_fault_precise` and `reexecute_after_fault`
   in `tests/baremetal/attn_test.c`.

**Answer.** A fault in the middle of `attn` is safe because every load happens before the first store (`docs/spec.md:133-136`): a load fault leaves `Y` unchanged and re-execution completes, while a store fault may leave `Y` partly written and re-execution overwrites all of it (`docs/spec.md:137-138`). `tests/baremetal/attn_test.c:163` asserts `load_fault_precise` and `tests/baremetal/attn_test.c:174` asserts `reexecute_after_fault`. This was read, not executed: no Spike or QEMU run was made here.
`grep -n "load_fault_precise" tests/baremetal/attn_test.c` -> `163:	   && filled (t->y, t->bytes, 0x5a), "load_fault_precise");`

## Stage 7: hardware context (reading)

- Dao et al., *FlashAttention: Fast and Memory-Efficient Exact Attention
  with IO-Awareness* (NeurIPS 2022): how a fused unit can avoid storing
  the `[n x n]` score matrix.
- Jouppi et al., *In-Datacenter Performance Analysis of a Tensor
  Processing Unit* (ISCA 2017): the bf16/fp32 split and systolic arrays.
- The Arm SME and Intel AMX architecture references: matrix extensions of
  general-purpose ISAs, a different trade-off (tile registers, many
  instructions) from one fused instruction.

**Answer.** At the limit `ATTN_MAX_N` = 4096 (`include/attn_abi.h:43`) the explicit score matrix needs 4096*4096*4 = 67108864 bytes (64 MiB), while a 128x128 tile needs 128*128*4 = 65536 bytes, a ratio of 1024. FlashAttention keeps a tile in on-chip memory and streams K and V, which is the memory argument a fused unit can make for avoiding the stored matrix.
`.venv/Scripts/python.exe -c 'print(4096*4096*4, 128*128*4, (4096*4096*4)//(128*128*4))'` -> `67108864 65536 1024`

Answers are checked by tests/test_study_answers.py.

## Glossary

| Term | Meaning |
|------|---------|
| GIMPLE | GCC's three-address intermediate language, between parsing and RTL |
| SSA | static single assignment: every value defined once; PHI nodes merge values at control-flow joins |
| LCSSA | loop-closed SSA: a value leaving a loop passes through a PHI in the exit block |
| RTL | GCC's low-level representation, close to machine instructions |
| `unspec` | an RTL operation the compiler does not interpret; `unspec_volatile` also may not be deleted, merged or reordered |
| decodetree | QEMU's generator that turns instruction patterns into a decoder |
| TCG | QEMU's tiny code generator, the JIT that translates guest code |
| HTIF | host-target interface Spike uses for console output and exit |
| medany | code model allowing code and data anywhere in a 2 GiB window around the PC |
| R4 | instruction format with three source registers and one destination |
