# Theory

This page explains the two ideas the project joins: the self-attention
computation at the heart of a transformer, and the way a RISC-V processor
can be given a new instruction for it. Neither part assumes prior
knowledge beyond linear algebra and a first course in computer
architecture.

## 1. Self-attention

### 1.1 One head

A transformer layer receives a sequence of `n` tokens, each represented by
a vector of `e` numbers (the model width). Stack them as the rows of a
matrix `X` of shape `[n x e]`.

Self-attention lets every token look at every other token and build its
new representation as a weighted mix of theirs. Three learned matrices
project `X` into queries, keys and values:

```
Q = X Wq        K = X Wk        V = X Wv        (each [n x d])
```

The score of query `i` against key `j` is their dot product, scaled by
`1/sqrt(d)` so that its variance does not grow with the head width `d`:

```
S[i][j] = (Q[i] . K[j]) / sqrt(d)
```

Each row of scores becomes a probability distribution through softmax,
and the output row is the probability-weighted sum of the value rows:

```
P[i][j] = exp(S[i][j]) / sum_k exp(S[i][k])
A[i]    = sum_j P[i][j] V[j]
```

In one line this is the formula from *Attention Is All You Need*
(Vaswani et al., 2017):

```
Attention(Q, K, V) = softmax(Q K^T / sqrt(d)) V
```

### 1.2 Many heads

One head can only express one notion of "relevant". Multi-head attention
runs `h` heads side by side on slices of width `d = e / h`, concatenates
their outputs and mixes them with a final projection `Wo`:

```
head_j = Attention(Q_j, K_j, V_j)          Q_j = columns j*d .. j*d+d-1 of Q
Y      = concat(head_0, ..., head_{h-1}) Wo + bo
```

With the input projections and their biases included, this is the whole
attention block of a transformer layer, and it is exactly what one `attn`
instruction computes:

```
Q = X Wq + bq    K = X Wk + bk    V = X Wv + bv
for each head j: A_j = softmax(Q_j K_j^T * scale + M) V_j
Y = concat(A_0 .. A_{h-1}) Wo + bo
```

### 1.3 Variants the instruction supports

- **Causal masking.** A language model generating text must not let token
  `i` see tokens after it. With the causal flag, row `i` only attends to
  keys `0..i`.
- **Additive mask.** An `[n x n]` matrix `M` added to the scores before
  softmax. `-inf` entries remove a key (padding, block structure);
  finite entries bias the scores (ALiBi-style position biases).
- **Grouped-query attention (GQA) and multi-query attention (MQA).** Large
  models share each key/value head among several query heads to shrink
  the key/value cache. With `h_kv` key/value heads, query head `j` uses
  key/value head `j / (h / h_kv)`. `h_kv = 1` is MQA, `h_kv = h` is the
  classic form.
- **Explicit scale.** Some models use a scale other than `1/sqrt(d)`.

### 1.4 Numerics

**Stable softmax.** `exp` overflows binary32 above about 88.7. Subtracting
the row maximum first leaves the result mathematically unchanged and makes
every exponent at most zero:

```
softmax(s)_j = exp(s_j - max(s)) / sum_k exp(s_k - max(s))
```

The instruction does this, and so does the C code the compiler recognizes.
A row whose scores are all `-inf` (fully masked) yields NaN, as plain C and
PyTorch do.

**bfloat16.** bf16 keeps binary32's 8-bit exponent and cuts the mantissa
to 7 bits. It has the same range as float, so large activations do not
overflow, and it halves memory traffic. Training and inference hardware
(TPU, Intel AMX, Arm SME) therefore stores tensors in bf16 but multiplies
and accumulates in binary32. `attn` follows the same split: inputs and
weights may be bf16, all arithmetic is binary32, and the output may be
rounded back to bf16 (round to nearest, ties to even).

**Order of operations.** Floating-point addition is not associative, so
the order of a sum changes the last bits of the result. The specification
fixes the order (index order, no fused multiply-add). Spike, QEMU and the
host model therefore give bit-identical results, and the compiler can
prove that a C loop computes exactly the same values.

### 1.5 Cost

For one layer the work is dominated by the four projections
(`4 n e^2` multiply-adds) and the score and value products (`2 n^2 e`).
Software spends a large share of time moving `Q`, `K`, `V` and the
`[n x n]` score matrix through memory. A fused unit never has to write the
intermediate matrices out. That is the argument for one instruction
covering the whole block: it describes the complete data flow to the
hardware, which may then tile it the way FlashAttention (Dao et al., 2022)
does in software.

## 2. Adding an instruction to RISC-V

### 2.1 Instruction formats

Every base RISC-V instruction is 32 bits. The low 7 bits are the major
opcode, and the remaining fields depend on the format. `attn` uses the
R4 format, the one the fused multiply-add instructions use, because it
names four registers:

```
 31   27 26 25 24  20 19  15 14  12 11   7 6      0
+-------+-----+------+------+------+------+--------+
|  rs3  | f2  | rs2  | rs1  |  f3  |  rd  | opcode |
+-------+-----+------+------+------+------+--------+
```

A decoder recognizes an instruction by masking: an instruction word `w`
is `attn` when `(w & MASK) == MATCH`. MASK has a 1 in every fixed bit
(opcode, funct3, funct2) and a 0 in every register field.

### 2.2 The custom opcode space

The ISA manual reserves four major opcodes for non-standard extensions:
custom-0 (`0x0b`), custom-1 (`0x2b`), custom-2 (`0x5b`) and custom-3
(`0x7b`). Standard extensions will never use them. custom-2 and custom-3
are reserved for RV128 but free on RV32 and RV64.

Vendors use that space. T-Head, CORE-V (OpenHW), MIPS, SiFive and others
have their encodings in upstream binutils. Two vendor extensions may reuse
the same bits, because a toolchain enables them by name in `-march` and a
real core implements only its own. Even so, an encoding that collides
with nobody can be combined freely with any vendor extension. Two
encodings collide exactly when some word satisfies both:

```
(match1 ^ match2) & mask1 & mask2 == 0
```

`scripts/find_opcodes.py` applies that test against every encoding in
binutils and Spike. For an R4 instruction only four slots in the whole
custom space are free of every known encoding, all in custom-3. `attn`
takes the first: custom-3, funct3 = 1, funct2 = 3, `MATCH = 0x0600107b`,
`MASK = 0x0600707f`.

### 2.3 Vendor extensions in the toolchain

A new instruction becomes usable when every layer knows it:

| Layer | What it needs |
|-------|---------------|
| Assembler and disassembler (binutils) | name, operands, MATCH/MASK, the ISA extension that enables it |
| Compiler (GCC) | the extension in `-march`, an RTL pattern that prints the instruction, a builtin to call it from C, and optionally a pass that finds it in ordinary code |
| Simulators (Spike, QEMU) | decoding, and code that performs the operation on the simulated machine |

The extension name `xattn` (a leading `x` marks a non-standard extension)
ties them together. `-march=rv64gc_xattn` makes GCC define
`__riscv_xattn`, accept the builtin and record `xattn1p0` in the ELF
attributes. The assembler then accepts `attn`, the disassembler shows it,
and Spike (`--isa=rv64gc_xattn`) and QEMU (`-cpu rv64,xattn=on`) execute
it. Without the extension, the assembler rejects the mnemonic and the
simulators raise an illegal-instruction trap.

### 2.4 Memory operands and precise exceptions

`attn` reads megabytes and writes the output matrix, but it names only
four registers. Each register holds an address: of the output, of the
input, and of two small descriptor structs that carry the remaining
pointers and the dimensions (see `docs/spec.md`). This is how other
"big" instructions work too, for example vector loads and memory copy
extensions.

A page fault in the middle must be restartable. The definition loads
every input before writing any output. So a fault while reading leaves
`Y` untouched, the operating system maps the page and returns, and the
instruction simply executes again. The bare-metal tests check this on
both simulators.

### 2.5 From C to the instruction

GCC reaches the instruction in two ways.

1. **The builtin.** `__builtin_riscv_attn(y, x, w, cfg)` expands to the
   RTL pattern `riscv_attn_<mode>`, which prints `attn rd, rs1, rs2, rs3`.
   The pattern is an `unspec_volatile` with a memory clobber. That tells
   the optimizers it reads and writes memory they cannot see, so loads
   and stores are never moved across it.
2. **Recognition.** A GIMPLE pass (`-mattn-recognize`) looks for the five
   loop nests of a C implementation of multi-head attention. It proves
   they compute exactly what `attn` computes and replaces them with one
   instruction behind a runtime guard. `docs/recognizer.md` explains how
   the proof works.
