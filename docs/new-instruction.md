# Adding your own instruction

Two scripts turn the work done by hand for `attn` into a repeatable
procedure for any instruction:

- `scripts/find_opcodes.py` finds encodings nobody uses;
- `scripts/xinsn.py` writes the instruction into binutils, GCC, Spike and
  QEMU and tests it on both simulators.

## 1. Find a free encoding

```bash
scripts/find_opcodes.py --inputs 3          # R4: rd, rs1, rs2, rs3
scripts/find_opcodes.py --inputs 2 --first  # R:  rd, rs1, rs2
scripts/find_opcodes.py --inputs 1 --json   # R with rs2 fixed
scripts/find_opcodes.py --format R4 --all --major custom-0
```

It loads every `MATCH_*`/`MASK_*` pair from
`binutils/include/opcode/riscv-opc.h` and `spike/riscv/encoding.h`
(about 3000 encodings, all standard extensions plus every upstream
vendor's). It then tests each candidate slot in custom-0..3 with the exact
overlap condition `(m1 ^ m2) & k1 & k2 == 0`. By default a slot shared
only with vendor extensions counts as free, sorted by how many vendor
instructions share it, because vendor extensions are enabled one at a time
by `-march`. `--strict` treats vendor encodings as taken too.

| Inputs | Format | Fixed fields | Slots in custom-0..3 |
|--------|--------|--------------|----------------------|
| 3 | R4 | opcode, funct3, funct2 | 128 |
| 2 | R | opcode, funct3, funct7 | 4096 |
| 1 | R, rs2 = 0 | + rs2 | 4096 (shares R slots) |
| 0 | R, rs1 = rs2 = 0 | + rs1, rs2 | 4096 (shares R slots) |

At the time of writing only 4 of the 128 R4 slots overlap nothing at all.

## 2. Describe the instruction

```
# examples/insns/mac.spec
name   = mac          # mnemonic; the ISA extension becomes Xmac
inputs = 3            # source registers rs1..rs3 (0 to 3)
writes = rd           # rd: result goes to rd.  none: rd is one more source
memory = no           # yes if the semantics use LD*/ST*
slot   = auto         # or major:funct3:funct, e.g. custom-1:2:0
semantics:
  return rs1 * rs2 + rs3;
```

The semantics are the body of a C function that receives `uint64_t rd,
rs1, rs2, rs3` (zero-extended register values) and `unsigned xlen`. Inside
it you can use:

- `LD8/LD16/LD32/LD64(addr)` and `ST8/ST16/ST32/ST64(addr, v)` for guest
  memory. Faults are precise in both simulators.
- `ILLEGAL()` to raise an illegal-instruction exception.

The value returned goes to `rd`, truncated to XLEN and sign-extended on
RV32. The same body is compiled into Spike, QEMU and the host model, so
they cannot disagree.

## 3. Plug it in, build, test

```bash
scripts/xinsn.py show  examples/insns/mac.spec   # encoding + files it would change
scripts/xinsn.py apply examples/insns/mac.spec   # edit the trees (idempotent)
scripts/build.sh binutils gcc spike qemu         # incremental
scripts/xinsn.py test  examples/insns/mac.spec
```

`apply` makes these changes, using the same anchors as the hand-written
Xattn patches:

| Tree | Generated or edited |
|------|---------------------|
| binutils | MATCH/MASK + `DECLARE_INSN`, `INSN_CLASS_X<NAME>`, opcode table row, extension table and both `riscv_multi_subset_supports*` cases, a gas test |
| GCC | `riscv-ext-x<name>.def` (then `riscv-ext.opt` and `riscv-ext.texi` regenerated), `<name>.md` (`unspec`; `unspec_volatile` with a memory clobber if it touches memory or writes no register), unspec enum, function type, `AVAIL` predicates, `<name>.def` builtins for RV32 and RV64 |
| Spike | `riscv/x<name>.cc` + `<name>_core.h`, registration in `extensions.cc`, build list |
| QEMU | `x<name>.decode`, `trans_x<name>.c.inc`, `tcg/<name>_helper.c` + `<name>_core.h`, CPU flag, property and ISA string entry (kept in canonical order), helper prototype, meson and decoder-table entries |

In C, the instruction is `__builtin_riscv_<name>(...)` with
`-march=..._x<name>`. Spike runs it with `--isa=rv64gc_x<name>`, QEMU with
`-cpu rv64,x<name>=on`.

`test` evaluates the semantics on the host for 64 input vectors (27 edge
values such as 0, -1, INT_MIN and INT_MAX, plus 37 random). It writes a
bare-metal program that calls the builtin on each vector and compares
with the host result, then runs that program on QEMU and on Spike and
checks with objdump that the instruction is really in it:

```
$ scripts/xinsn.py test examples/insns/mac.spec
qemu  mac: all vectors passed
spike mac: all vectors passed
objdump: 1 mac instruction(s) in the test
```

The three examples, `bitrev` (1 input), `avgu` (2) and `mac` (3), were
applied together, built and passed this test on both simulators. Applying
them one after another gives each its own slot, because `apply` sees the
encodings added before it. They are kept out of the Xattn patch series:
apply them in your own checkout to try the tool.

## 4. Limits

- `test` covers instructions that write `rd` from registers. An
  instruction that touches memory or writes no register (like `attn`)
  needs its own test. `tests/baremetal` is the model to copy.
- A pure instruction (no memory, writes `rd`) is a plain `unspec`. GCC
  may then delete it if the result is unused, or merge two identical
  ones. That is correct for a pure function. Use `memory = yes` if the
  instruction has effects the compiler must keep.
- The generated `.md` uses insn type `arith`, which every RISC-V pipeline
  model reserves. Give the instruction its own type if the scheduler
  should know its latency.
- To remove an applied instruction, use `git checkout -- . && git clean -f`
  in each tree. The tool does not track what it added.
