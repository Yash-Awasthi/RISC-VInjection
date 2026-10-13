# The attention recognizer

GCC replaces plain C multi-head attention with one `attn` instruction at
`-O2` and above, with no extra flags or headers. The recognizer is a
target-independent middle-end pass, `gcc/gcc/tree-ssa-loop-attn.cc` (dump
name `attn_recog`, flag `-ftree-loop-attn`), listed in `passes.def` right
after `pass_tree_loop_init`, before loop distribution, interchange,
unrolling and vectorization can reshape the loops.

The pass replaces the loops with the internal function `.ATTN (y, x, &w,
&cfg)` in GIMPLE. `expand_ATTN` in `internal-fn.cc` lowers it through the
`attn` optab, which RISC-V provides as `attn<mode>` in `xattn.md` when Xattn
is enabled. The pass runs only on targets where that optab exists. The
toolchain is configured with `--with-arch=rv64gc_xattn`, so Xattn is on by
default.

The pass does not guess from surface features. It replaces code only after
proving that the code computes exactly what the instruction computes, with
the same operations in the same order. If any step of the proof fails, the
code is left alone. With `-fopt-info-loop-missed`, GCC says which step
failed.

## 1. What it accepts

The shape is the textbook one: five loop nests over `float` arrays, with
dimensions that may be runtime values.

```c
#include <math.h>
#include <stdlib.h>

void
mha (float *restrict y, const float *restrict x,
     const float *restrict wq, const float *restrict wk,
     const float *restrict wv, const float *restrict wo,
     const float *restrict bq, const float *restrict bk,
     const float *restrict bv, const float *restrict bo,
     int n, int e, int h)
{
  int d = e / h;
  float scale = 1.0f / sqrtf ((float) d);
  float *q = malloc (sizeof (float) * n * e);   /* likewise k, v, c */
  float *p = malloc (sizeof (float) * n);

  for (int i = 0; i < n; i++)                   /* Q = X Wq + bq; same for K, V */
    for (int j = 0; j < e; j++)
      {
	float acc = 0.0f;
	for (int t = 0; t < e; t++)
	  acc += x[i * e + t] * wq[t * e + j];
	q[i * e + j] = acc + bq[j];
      }
  /* ... k and v ... */

  for (int hd = 0; hd < h; hd++)
    for (int i = 0; i < n; i++)
      {
	float mx = -INFINITY;
	for (int j = 0; j <= i; j++)            /* j < n without causality */
	  {
	    float s = 0.0f;
	    for (int t = 0; t < d; t++)
	      s += q[i * e + hd * d + t] * k[j * e + hd * d + t];
	    s = s * scale;                      /* optional: s = s + m[i * n + j]; */
	    p[j] = s;
	    if (s > mx)
	      mx = s;
	  }
	float l = 0.0f;
	for (int j = 0; j <= i; j++)
	  {
	    p[j] = expf (p[j] - mx);
	    l += p[j];
	  }
	for (int t = 0; t < d; t++)
	  {
	    float acc = 0.0f;
	    for (int j = 0; j <= i; j++)
	      acc += p[j] * v[j * e + hd * d + t];
	    c[i * e + hd * d + t] = acc / l;
	  }
      }

  /* y = c Wo + bo, same shape as the projections */
  free (q); /* ... */
}
```

`demo/mha_plain.c` is this function in full. Accepted variations:

- causal (`j <= i`) or full (`j < n`) rows;
- with or without each bias vector;
- with or without an additive mask `m[i * n + j]`;
- any scale value computed before the loops, or a constant;
- the head loop inside or outside the row loop;
- the three projections in any order;
- `i`/`j` order of the outer two loops of each matrix product;
- RV32 and RV64; any integer types for indices.

Not handled (the code stays as loops): grouped-query attention, bf16
data, scores divided by `sqrtf(d)` instead of multiplied by a scale,
a maximum written with `>=`, buffers that are not local allocations,
and loops that GCC has already unrolled or restructured.

Requirements on the compilation:

- Xattn enabled (the default) and `-O2` or `-O3`. `-fno-tree-loop-attn`
  turns the pass off;
- not an explicit `-fmath-errno`. The library `expf` may set `errno` and
  the instruction does not; by default the pass drops that side effect,
  as `-fno-math-errno` would;
- not `-frounding-math`;
- the output must be provably distinct from every input. `restrict` on
  the parameters is the usual way.

## 2. How the proof works

### 2.1 Addresses are polynomials

Every load and store is reduced to `base + offset`. The offset is
evaluated as a polynomial with integer coefficients over *atoms*. An atom
is a loop counter or a value defined outside the loops, such as `n`, `e`
or `d`. GCC's index arithmetic is messy by the time the pass runs.
`q[i * e + hd * d + t]` arrives as

```
_306 = (unsigned) d * (unsigned) hd;   _80 = (int) ((unsigned) i * (unsigned) e + _306);
_81  = _80 + t;   _83 = (long unsigned) _81 * 4;   _84 = q + _83;
```

The evaluator walks this chain to `4*e*i + 4*d*hd + 4*t`. It treats
integer conversions as exact. That is only valid if no intermediate value
wraps, so every operation also carries an upper bound, computed with every
atom at most 4096. The pass rejects the code if any bound can exceed the
range of the type the operation is computed in. The bound holds because
the runtime guard (2.4) checks the dimensions before `attn` is used.

A loop counter must be a header PHI that starts at 0 and steps by 1. Its
trip count comes from the exit test: `t + 1 < d` gives `d` iterations,
`j + 1 <= i` gives `i + 1`.

### 2.2 Every operation is matched

Each nest is matched from its stores backwards, statement by statement.
For a matrix product:

```
store OUT[r][c] = acc_final (+ bias[c])
acc_final = last value of  acc = 0.0;  acc = acc + A[r][k] * B[k][c]
```

The address polynomials decide which loop is `r`, `c` and `k`. The
trip counts give the shape. The initial value must be exactly `+0.0`.
Addition and multiplication may have their operands in either order,
because IEEE addition and multiplication are commutative bit for bit.
Their nesting may not change, because they are not associative. That is
why the instruction's definition fixes the summation order.

The attention nest is matched the same way:
- the dot product and its scale (and mask);
- the store to `p[j]`;
- the running maximum. This must be `if (s > mx) mx = s`, which GCC turns
  into `mx = s > mx ? s : mx`, starting at `-inf`. `fmaxf` behaves
  differently for NaN and signed zero, so it is accepted only under
  `-ffinite-math-only -fno-signed-zeros`.
- `expf (p[j] - mx)`, stored back to `p[j]`, summed into `l`, all in
  that order;
- the weighted sum of `V`, divided by `l`.

Then every statement in all five nests must be accounted for. Each
floating-point operation, load, store or call must be one of the matched
ones. Everything else must be side-effect-free integer arithmetic or loop
control. An extra store, an extra call, or a float computation the
instruction does not do makes the match fail.

### 2.3 Control flow is decided

After loop header copying, every loop is guarded by a test such as
`if (n > 0)`, and inner loops by tests such as `if (d > 0)`. The pass
evaluates each branch that is not a loop exit with interval arithmetic:
dimensions are in `[1, 4096]` and counters in `[0, 4096]`. The branch
must come out the same way for every allowed value. The edge that is
never taken is marked dead, and PHI nodes are read only along live edges.
GCC's partial redundancy elimination produces values such as
`PHI <s * 0.125 (live), 0.0 (dead)>`, and those are seen through
correctly. Any branch that depends on data makes the match fail.

The pass then walks each loop body along live edges, from header to exit
test. Every matched statement must lie on that path, so it runs exactly
once per iteration. It also walks the whole region from its entry. That
walk must pass through the three projections (in any order), then the
attention nest, then the output product, and reach a single exit.

### 2.4 The region and the guard

The region starts after the last statement with a side effect before the
first nest (here the last `malloc`) and ends where every path meets again
(here the first `free`). Nothing computed inside may be used after it.
Nothing may enter or leave it elsewhere. It may not contain other loops.

The scratch buffers `q`, `k`, `v`, `c` and `p` must come from `malloc`,
`calloc` or `alloca`. Apart from pointer arithmetic, their only uses may
be the matched accesses, `free` and null tests. The instruction does not
fill them, so nobody may read them afterwards. The output and every
scratch buffer must not alias any input, according to GCC's points-to
analysis.

The pass then inserts, on the region's entry edge:

```
if (1 <= n <= 4096 && 1 <= e <= 2048 && 1 <= h <= 2048)
  if (d * h == e)                 /* d computed here, h already non-zero */
    { fill attn_w, attn_cfg; attn y, x, &attn_w, &attn_cfg; goto exit; }
original loops ...
exit:
```

Values the instruction needs that the code computes between the nests
(`d = e / h`, `scale = 1 / sqrtf(d)`) are recomputed in the guard blocks.
This is allowed only for pure operations. An integer division may be
copied only after the guard has shown its divisor is non-zero. When the
guard fails, for example because `n` exceeds the instruction's limit, the
original loops run unchanged.

## 3. What "equivalent" means here

On the instruction path, the results are those of the definition in
`docs/spec.md`. On the loop path, they are those of the C code. These are
the same for every input, with one exception: `expf` itself. The C code
calls the C library's `expf`, the instruction uses its own implementation
(within 1 ulp) and never sets `errno`. That is the same freedom
`-fno-math-errno` gives the compiler to substitute an inline `expf`. Floating-point contraction
(`-ffp-contract=fast`, GCC's default) lets the C code fuse a multiply and
an add. The instruction never does, which is also an allowed execution of
the C code.

## 4. Testing

- `gcc/gcc/testsuite/gcc.target/riscv/xattn-recog-*.c`: compile tests.
  Four forms must become exactly one `attn`. Six must not, and each must
  report the right reason (aliasing, `errno`, division, `>=`, a scratch
  buffer read afterwards, and the flag off). Run them with
  `make check-gcc`.
- `tests/recog`: builds `demo/mha_plain.c` and two test forms twice, once
  recognized and once as loops, and runs both on QEMU and Spike with the
  same random inputs. The results must agree within the `expf`
  difference. Cases that fail the guard (`n = 4097`, `n = 0`) must give
  bit-identical results. Run with `make check-recog`.
