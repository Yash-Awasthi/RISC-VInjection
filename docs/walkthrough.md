# From a C excerpt to one instruction: every step

This is the whole path the project takes, in the order it was done. It
starts from a bare piece of C that computes multi-head self-attention and
ends with a single `attn` instruction executing on two simulators. It also
covers how the instruction is removed again, and how the same steps apply
to any other instruction.

## 0. The input

`demo/mha_plain.c` without its `#include` lines is exactly what a
developer would hand over: one function, `mha`, about 90 lines of plain
loops, with no `main`, no project header and no compiler flags:

```c
void
mha (float *restrict y, const float *restrict x,
     const float *restrict wq, ...,  int n, int e, int h)
{
  int d = e / h;
  float scale = 1.0f / sqrtf ((float) d);
  float *q = malloc (sizeof (float) * n * e);
  ...                       /* Q, K, V projections, softmax per head, Y = C Wo + bo */
}
```

Compiled by a stock RISC-V GCC, this is five loop nests and a few hundred
branch and arithmetic instructions. For n = 16, e = 32, h = 4 it executes
508,421 instructions.

## 1. One command to set everything up

```bash
git clone https://github.com/Yash-Awasthi/RISC-V_Injection.git
cd RISC-V_Injection
scripts/setup.sh
```

`scripts/setup.sh` checks the build tools and offers the install command
for apt, dnf, pacman, zypper or brew. It then fetches the upstream
submodules, applies `patches/`, builds binutils, GCC, newlib, libgcc, Spike
and QEMU, runs `make check`, and finishes with step 3 below on the demo.
Every step is incremental, so running it again is cheap.
`docs/build-and-test.md` explains each step in detail.

## 2. Choosing the encoding

`attn` has four register operands: Y, X, the weights descriptor and the
configuration descriptor. The only R4 (four-register) slots that collide
with no standard or vendor instruction are in the custom-3 major opcode.
`scripts/find_opcodes.py --strict` lists the free slots. Xattn takes
custom-3, funct3 = 1, funct2 = 3:

```
MATCH 0x0600107b   MASK 0x0600707f
attn a3, a0, a1, a2   =   0x66b516fb
```

`docs/spec.md` defines the instruction bit for bit: the descriptor
layouts, the computation, limits, traps and precise faults.

## 3. Compile the excerpt and look at the result

```bash
scripts/attncc.sh --run excerpt.c
```

The script puts `<math.h>` and `<stdlib.h>` in front of the excerpt.
These are standard headers only, and line numbers stay unchanged. It
compiles at plain `-O2`:

```
== compile: riscv64-unknown-elf-gcc -O2 excerpt.c
excerpt.c:51:23: optimized: multi-head self-attention (causal, biased) replaced with attn

== disassembly around attn
 112:	08bc                	addi	a5,sp,88
 114:	06f12827          	fsw	fa5,112(sp)
 118:	0118                	addi	a4,sp,128
 11a:	7eea1afb          	attn	s5,s4,a4,a5

== run on Spike: mha(n=16, e=32, h=4)
instructions executed, attn build:  991
instructions executed, loops build: 508421
largest output difference (ulp-scale expf only): <= 1e-5, PASS
```

At n = 64, e = 128, h = 8 the counts are 1,207 against 29,809,188. The
remaining instructions fill in the two descriptors and check the guard.

The loops are still in the binary, but they run only when the guard
fails. The guard rejects sizes the instruction would refuse with a trap:
n above 4096, e above 2048, or e not a multiple of h. In those cases the
original C must still run correctly. Every valid size executes the single
`attn`.

## 4. What happens inside the compiler

The instruction is built into GCC at the same levels as `fma`:

| Level | fma | attn | Where |
|-------|-----|------|-------|
| C builtin | `__builtin_fma` | `__builtin_attn (y, x, w, cfg)` | `builtins.def`, `builtins.cc` |
| GIMPLE internal function | `.FMA` | `.ATTN` | `internal-fn.def` |
| Optab | `fma<mode>4` | `attn<mode>` | `optabs.def`, `xattn.md` |
| RTL code | `(fma ...)` | `(attn r0 r1 r2 r3)` | `rtl.def` |
| Library fallback | libm `fma` | libgcc `__attn` | `libgcc/attn.c` |
| Found automatically | `a*b+c` in widening_mul | five attention loop nests in `attn_recog` | `tree-ssa-loop-attn.cc` |

The excerpt goes through these stages:

1. **Parsing and early optimization.** The loops become GIMPLE in SSA
   form. Inlining, constant propagation and the early loop passes leave
   five loop nests.
2. **`attn_recog`**, a middle-end pass that runs right after
   `pass_tree_loop_init` at `-O2` (`-ftree-loop-attn`). It runs only on
   targets that provide the `attn` optab. It proves, statement by
   statement, that the nests compute exactly the definition in
   `docs/spec.md` (`docs/recognizer.md` explains the proof). It then
   builds the two descriptors on the stack, adds the runtime guard and
   replaces the region with one internal call. From
   `-fdump-tree-attn_recog`:

   ```
   MEM <unsigned int> [(void *)&attn_cfg.25] = _468;           /* n */
   MEM <unsigned int> [(void *)&attn_cfg.25 + 4B] = _467;      /* e */
   ...
   .ATTN (y_212(D), x_237(D), &attn_w.24, &attn_cfg.25);
   ```

3. **Expansion to RTL.** `IFN_ATTN` is an optab internal function, the
   same mechanism `IFN_FMA` uses. It expands through `attn<mode>`, which
   RISC-V defines when Xattn is enabled. From `-fdump-rtl-expand`:

   ```
   (parallel [
       (attn (reg/v/f:DI 336 [ y ]) (reg/v/f:DI 337 [ x ])
             (reg:DI 399) (reg:DI 400))
       (clobber (mem:BLK (scratch)))])
   ```

   `attn` is a real RTL code, like `prefetch`. It uses four registers and
   sets none. The memory clobber orders it against every load and store,
   because it reads and writes memory reached through the descriptors.
   Unlike an `unspec_volatile`, it is not a barrier to register
   arithmetic, so the scheduler may move independent work across it
   (`xattn-rtl-2.c`).
4. **Register allocation, scheduling, final.** `riscv_attn_<mode>` in
   `xattn.md` prints `attn rd, rs1, rs2, rs3`.
5. **binutils.** The assembler encodes it in custom-3. The disassembler
   prints it back, and the object gets the `xattn1p0` ELF attribute.

The toolchain is configured with `--with-arch=rv64gc_xattn`, so no
`-march` flag is needed. `expf` normally may set `errno`; the pass drops
that side effect, as `-fno-math-errno` would, unless `-fmath-errno` is
given explicitly.

Called directly, `__builtin_attn` needs no header and works at every
optimization level. Without Xattn it calls `__attn` in libgcc, which runs
the same definition in software (link with `-lm` for `expf`).

## 5. Execution

Spike (`--isa=rv64gc_xattn`) and QEMU (`-cpu rv64,xattn=on`, system and
user mode) decode the instruction and run `include/attn_core.h`. This is
the one executable definition of the instruction; libgcc and the tests use
it too. All of them agree bit for bit. `make check` proves it:

- against an independent float64 model;
- byte by byte on both simulators;
- precise traps for reserved configurations and load faults;
- the loop code against the `attn` code at run time.

## 6. Removing it again

```bash
scripts/xattn.sh remove     # upstream sources, rebuilt: no attn anywhere
scripts/xattn.sh status
scripts/xattn.sh restore    # back to Xattn, rebuilt
```

`remove` checks out the pinned upstream commit in binutils, GCC, Spike and
QEMU, keeps branch `xattn`, and rebuilds. The default `-march` falls back
to `rv64gc`, and `build.sh` reconfigures GCC because its configure
arguments changed. `scripts/xinsn.py remove attn` (or `remove 0x66b516fb`)
does the same.

## 7. Any other instruction

`scripts/xinsn.py` automates every step above for a new instruction:

```bash
scripts/xinsn.py new            # asks: name, operands, C code, test
scripts/xinsn.py all SPEC       # find a free opcode, edit binutils, GCC,
                                # Spike and QEMU, rebuild, test on both
scripts/xinsn.py list           # every custom instruction and its encoding
scripts/xinsn.py remove NAME    # or an opcode (0x...) or a SPEC
```

`remove` replays the same edits in reverse. It cuts exactly the inserted
text, deletes the generated files, drops builtin types no other builtin
uses, rebuilds, and checks that the assembler now rejects the mnemonic.
Adding `mac`, `fill` and `vsum` and removing them again leaves the four
source trees byte-identical to before. `docs/new-instruction.md` explains
each edit.

The automatic loop recognition in step 4 is specific to attention. For a
new instruction, `xinsn.py` provides the builtin; a recognizer for its
loops would be another pass built like `tree-ssa-loop-attn.cc`.
