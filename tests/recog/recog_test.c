/* demo/mha_plain.c built twice: mha() at plain -O2 (one attn
   instruction plus the guarded loop fallback) and mha_loops() with
   -fno-tree-loop-attn.  mha_builtin() calls __builtin_attn without Xattn.
   All run on the same inputs; results must agree to within the expf
   difference between newlib and the simulator's host libm.  */

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include "bm.h"

typedef void mha_fn (float *, const float *, const float *, const float *,
		     const float *, const float *, const float *,
		     const float *, const float *, const float *, int, int,
		     int);
mha_fn mha, mha_loops, mha_builtin;

/* gcc.target/riscv/xattn-recog-2.c: full, masked, scale 0.125, no biases.  */
typedef void masked_fn (float *, const float *, const float *, const float *,
			const float *, const float *, const float *, int, int,
			int);
masked_fn mha2, mha2_loops;

/* gcc.target/riscv/xattn-recog-3.c: row loop outside the head loop.  */
typedef void plain_fn (float *, const float *, const float *, const float *,
		       const float *, const float *, int, int, int);
plain_fn mha3, mha3_loops;

static uint32_t seed = 12345;

static float
rnd (void)
{
  seed = seed * 1664525u + 1013904223u;
  return (int32_t) (seed >> 8) / 8388608.0f - 1.0f;
}

static float *
filled (int count, float scale)
{
  float *p = malloc (sizeof (float) * count);
  for (int i = 0; i < count; i++)
    p[i] = rnd () * scale;
  return p;
}

static int failures;

static void
run (const char *name, int variant, int n, int e, int h, int exact)
{
  float w = 1.0f / sqrtf ((float) e);
  float *x = filled (n * e, 1.0f);
  float *wq = filled (e * e, w), *wk = filled (e * e, w);
  float *wv = filled (e * e, w), *wo = filled (e * e, w);
  float *bq = filled (e, 0.1f), *bk = filled (e, 0.1f);
  float *bv = filled (e, 0.1f), *bo = filled (e, 0.1f);
  float *y1 = malloc (sizeof (float) * n * e + 1);
  float *y2 = malloc (sizeof (float) * n * e + 1);

  float *m = filled (n * n, 1.0f);
  for (int i = 0; i < n * n; i++)
    if (m[i] < -0.8f && i % n)
      m[i] = -INFINITY;
  switch (variant)
    {
    case 0:
      mha (y1, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      mha_loops (y2, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      break;
    case 3:
      mha_builtin (y1, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      mha_loops (y2, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      break;
    case 1:
      mha2 (y1, x, wq, wk, wv, wo, m, n, e, h);
      mha2_loops (y2, x, wq, wk, wv, wo, m, n, e, h);
      break;
    default:
      mha3 (y1, x, wq, wk, wv, wo, n, e, h);
      mha3_loops (y2, x, wq, wk, wv, wo, n, e, h);
      break;
    }

  float worst = 0.0f;
  int same = 1;
  for (int i = 0; i < n * e; i++)
    {
      float d = fabsf (y1[i] - y2[i]);
      if (!(d <= worst))
	worst = d;
      same &= *(uint32_t *) &y1[i] == *(uint32_t *) &y2[i];
    }
  int ok = exact ? same : worst <= 1e-5f;
  if (!ok)
    {
      bm_puts ("  y1[0]=");
      bm_puthex (*(uint32_t *) &y1[0]);
      bm_puts (" y2[0]=");
      bm_puthex (*(uint32_t *) &y2[0]);
      bm_puts (" y1[last]=");
      bm_puthex (*(uint32_t *) &y1[n * e - 1]);
      bm_puts (" y2[last]=");
      bm_puthex (*(uint32_t *) &y2[n * e - 1]);
      bm_puts (" worst=");
      bm_puthex (*(uint32_t *) &worst);
      bm_puts ("\n");
    }
  bm_puts (ok ? "PASS " : "FAIL ");
  bm_puts (name);
  bm_puts ("\n");
  failures += !ok;
}

int
main (void)
{
  run ("causal_biased_n16_e32_h4", 0, 16, 32, 4, 0);
  run ("causal_biased_n40_e64_h8", 0, 40, 64, 8, 0);
  run ("full_masked_n24_e48_h6", 1, 24, 48, 6, 0);
  run ("row_outer_n20_e32_h2", 2, 20, 32, 2, 0);
  /* libgcc's __attn, the fallback of __builtin_attn without Xattn.  */
  run ("libgcc_causal_biased_n16_e32_h4", 3, 16, 32, 4, 0);
  /* n above the instruction's limit fails the guard: the original loops
     run in both builds, bit for bit.  */
#ifndef BM_SPIKE
  /* Minutes on Spike, seconds on QEMU.  */
  run ("fallback_n4097", 0, 4097, 1, 1, 1);
#endif
  /* n = 0 also fails the guard; nothing may be written.  */
  {
    float y = 7.0f, z = 0.0f;
    mha (&y, &z, &z, &z, &z, &z, &z, &z, &z, &z, 0, 1, 1);
    bm_puts (y == 7.0f ? "PASS fallback_n0\n" : "FAIL fallback_n0\n");
    failures += y != 7.0f;
  }
  bm_puts (failures ? "recog_test: FAILED\n" : "recog_test: all passed\n");
  return failures;
}
