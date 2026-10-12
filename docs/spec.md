# The Xattn extension, version 1.0

This is the normative definition of the `attn` instruction. The executable
form of the same definition is `include/attn_core.h`. Spike, QEMU and the
host tests all run that file, and the tests compare it with an independent
float64 model (`tools/attn_model.py`).

## 1. Encoding

```
attn rd, rs1, rs2, rs3

 31   27 26 25 24  20 19  15 14  12 11   7 6      0
+-------+-----+------+------+------+------+--------+
|  rs3  | 11  | rs2  | rs1  | 001  |  rd  | 1111011|
+-------+-----+------+------+------+------+--------+
                                            custom-3

MATCH = 0x0600107b   MASK = 0x0600707f
```

Example: `attn a3, a0, a1, a2` encodes as `0x66b516fb`.

The instruction exists only when the Xattn extension is implemented and
enabled. Otherwise its encoding raises an illegal-instruction exception.
It is valid in every privilege mode, on RV32 and RV64.

## 2. Operands

All four registers hold addresses. On RV32 they are 32-bit and
zero-extended.

| Register | Points to | Access |
|----------|-----------|--------|
| `rd`  | `Y`, `[n x e]` in `out_dtype` | written |
| `rs1` | `X`, `[n x e]` in `in_dtype` | read |
| `rs2` | `struct attn_weights` (64 bytes) | read |
| `rs3` | `struct attn_cfg` (40 bytes) | read |

The descriptors are little-endian with natural alignment:

```c
struct attn_weights {          /* rs2 */
  uint64_t wq, wk, wv, wo;     /* weight matrices, in_dtype, row-major [in][out] */
  uint64_t bq, bk, bv, bo;     /* bias vectors, binary32; 0 = no bias */
};

struct attn_cfg {              /* rs3 */
  uint32_t n;                  /* sequence length */
  uint32_t e;                  /* model width, e = h * d */
  uint32_t h;                  /* query heads */
  uint32_t h_kv;               /* key/value heads; 0 means h */
  uint32_t flags;              /* bit 0 CAUSAL, bit 1 SCALE */
  uint16_t in_dtype;           /* 0 binary32, 1 bfloat16: X and W* */
  uint16_t out_dtype;          /* 0 binary32, 1 bfloat16: Y */
  uint32_t scale_bits;         /* binary32 bits, used with SCALE */
  uint32_t reserved;           /* must be 0 */
  uint64_t mask;               /* [n x n] binary32 additive mask; 0 = none */
};
```

The C declarations live in `include/attn_abi.h`. Shapes, with
`d = e / h` and `kv = h_kv * d`:

| Matrix | Shape | Element |
|--------|-------|---------|
| `Wq`, `Wo` | `[e x e]` | `in_dtype` |
| `Wk`, `Wv` | `[e x kv]` | `in_dtype` |
| `bq`, `bo` | `[e]` | binary32 |
| `bk`, `bv` | `[kv]` | binary32 |
| `M` | `[n x n]` | binary32 |

## 3. Semantics

All arithmetic is IEEE 754 binary32 with round to nearest, ties to even.
Every product and every sum is rounded separately (no fused multiply-add).
Sums accumulate from `0.0` in increasing index order. bf16 inputs widen to
binary32 exactly.

```
d     = e / h;  kv = h_kv * d;  g = h / h_kv        (h_kv = h if 0)
scale = SCALE ? float(scale_bits) : 1.0f / sqrtf(float(d))

Q[i][c] = (sum_k X[i][k] * Wq[k][c]) + bq[c]         c < e     (bias term only if bq != 0)
K[i][c] = (sum_k X[i][k] * Wk[k][c]) + bk[c]         c < kv
V[i][c] = (sum_k X[i][k] * Wv[k][c]) + bv[c]         c < kv

for each head j < h, row i < n:
    t   = j / g                                      key/value head
    L   = CAUSAL ? i + 1 : n                          keys 0 .. L-1
    for key r < L:
        s[r] = (sum_u Q[i][j*d+u] * K[r][t*d+u]) * scale
        if mask: s[r] = s[r] + M[i][r]
    m   = -inf;  for r < L: if (s[r] > m) m = s[r]
    for r < L: p[r] = expf(s[r] - m)
    l   = sum_r p[r]
    for u < d: C[i][j*d+u] = (sum_r p[r] * V[r][t*d+u]) / l

Y[i][c] = (sum_k C[i][k] * Wo[k][c]) + bo[c]         stored as out_dtype
```

`expf` must be accurate to within 1 ulp. The three implementations in
this repository use the host C library, so they agree bit for bit with
each other but not necessarily with another `expf`.

A row in which every `s[r]` is `-inf` produces NaN, exactly like the
equivalent C code. NaN inputs propagate.

## 4. Reserved configurations

The instruction raises an illegal-instruction exception, and writes
nothing, when any of these holds:

- `n == 0`, `e == 0`, `h == 0`, or `e % h != 0`
- `h % h_kv != 0` (with `h_kv != 0`)
- a flag bit other than CAUSAL or SCALE is set, or `reserved != 0`
- `in_dtype > 1` or `out_dtype > 1`
- `wq`, `wk`, `wv` or `wo` is 0
- on RV32: any pointer in the descriptors has a non-zero upper half
- `n > ATTN_MAX_N` (4096) or `e > ATTN_MAX_E` (2048), the limits of this
  implementation

## 5. Memory and exceptions

- Every load happens before the first store. A load fault (page fault,
  access fault, misaligned access where the platform requires alignment)
  leaves `Y` unchanged, and re-executing the instruction after the handler
  returns completes it. `mtval`/`stval` report the faulting address.
- A store fault may leave `Y` partly written; re-execution overwrites all
  of it.
- `Y` must not overlap any input. If it does, the result is unspecified.
- The instruction writes no integer or floating-point register and does
  not change `fflags`.
- Element addresses must be aligned to the element size where the
  platform requires naturally aligned accesses.

## 6. Software interface

- `-march=..._xattn` enables the extension in GCC and binutils and
  defines `__riscv_xattn` (value 1000000, for version 1.0).
- `void __builtin_riscv_attn(void *y, const void *x, const void *w, const void *cfg)`
  emits one `attn`.
- `include/attn.h` wraps it as `attn_mha()`. Without Xattn the same call
  runs `attn_core.h` in software, with identical results.
- `-mattn-recognize` lets GCC replace C code that computes this
  definition with the instruction (see `docs/recognizer.md`).
- Spike: `--isa=rv64gc_xattn`. QEMU: `-cpu rv64,xattn=on`.
