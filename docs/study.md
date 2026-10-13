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

## Stage 3: RISC-V encoding (1 day)

1. *The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA*:
   chapter "RV32I Base Integer Instruction Set" (formats), the opcode map
   table, and chapter "Extending RISC-V" (custom opcodes, non-standard
   extensions).
2. Volume II (privileged): `mcause`, `mtval`, `mepc`, `mret`. Enough to
   read `tests/baremetal/crt.S`.
3. Run `scripts/find_opcodes.py --inputs 3 --all` and pick three slots by
   hand. Check the `(m1 ^ m2) & k1 & k2` rule on paper.

## Stage 4: binutils (half a day)

1. Read `opcodes/riscv-opc.c` around the vendor tables, and the operand
   letters at the top of `gas/config/tc-riscv.c` (`d`, `s`, `t`, `r`).
2. `git -C binutils show xattn` shows the whole Xattn change: 13 lines
   plus tests.

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

## Stage 7: hardware context (reading)

- Dao et al., *FlashAttention: Fast and Memory-Efficient Exact Attention
  with IO-Awareness* (NeurIPS 2022): how a fused unit can avoid storing
  the `[n x n]` score matrix.
- Jouppi et al., *In-Datacenter Performance Analysis of a Tensor
  Processing Unit* (ISCA 2017): the bf16/fp32 split and systolic arrays.
- The Arm SME and Intel AMX architecture references: matrix extensions of
  general-purpose ISAs, a different trade-off (tile registers, many
  instructions) from one fused instruction.

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
