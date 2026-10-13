/* Driver for scripts/attncc.sh --run: calls FN (one attn) and FN_loops
   (recognizer off) on the same inputs, prints the instructions each call
   retired and the largest output difference.  */

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include "bm.h"

#define CAT2(a, b) a##b
#define CAT(a, b) CAT2 (a, b)
#define FN_LOOPS CAT (FN, _loops)

typedef void mha_fn (float *, const float *, const float *, const float *,
		     const float *, const float *, const float *,
		     const float *, const float *, const float *, int, int,
		     int);
mha_fn FN, FN_LOOPS;

static uint32_t seed = 12345;

static float *
filled (int count, float scale)
{
  float *p = malloc (sizeof (float) * count);
  for (int i = 0; i < count; i++)
    {
      seed = seed * 1664525u + 1013904223u;
      p[i] = ((int32_t) (seed >> 8) / 8388608.0f - 1.0f) * scale;
    }
  return p;
}

static void
putdec (uint64_t v)
{
  char b[21];
  int i = 20;
  b[i] = 0;
  do
    b[--i] = '0' + v % 10;
  while (v /= 10);
  bm_puts (b + i);
}

static uint64_t
instret (void)
{
  uint64_t v;
  __asm__ volatile ("csrr %0, minstret" : "=r" (v));
  return v;
}

int
main (void)
{
  int n = ATTN_N, e = ATTN_E, h = ATTN_H;
  float w = 1.0f / sqrtf ((float) e);
  float *x = filled (n * e, 1.0f);
  float *wq = filled (e * e, w), *wk = filled (e * e, w);
  float *wv = filled (e * e, w), *wo = filled (e * e, w);
  float *bq = filled (e, 0.1f), *bk = filled (e, 0.1f);
  float *bv = filled (e, 0.1f), *bo = filled (e, 0.1f);
  float *y1 = malloc (sizeof (float) * n * e);
  float *y2 = malloc (sizeof (float) * n * e);

  uint64_t t0 = instret ();
  FN (y1, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
  uint64_t t1 = instret ();
  FN_LOOPS (y2, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
  uint64_t t2 = instret ();

  float worst = 0.0f;
  for (int i = 0; i < n * e; i++)
    {
      float d = fabsf (y1[i] - y2[i]);
      if (!(d <= worst))
	worst = d;
    }
  bm_puts ("instructions executed, attn build:  ");
  putdec (t1 - t0);
  bm_puts ("\ninstructions executed, loops build: ");
  putdec (t2 - t1);
  bm_puts ("\nlargest output difference (ulp-scale expf only): ");
  bm_puts (worst <= 1e-5f ? "<= 1e-5, PASS\n" : "too large, FAIL\n");
  return worst <= 1e-5f ? 0 : 1;
}
