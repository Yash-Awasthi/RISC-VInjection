/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Per-shape measurement: one attn instruction against the C loops it replaces.

   tests/perf/Makefile compiles demo/mha_plain.c twice, once with the
   recognizer (mha_attn: one attn plus the runtime guard) and once with
   -fno-tree-loop-attn (mha_loops: the loops as written).  Both are called on
   identical inputs; one CSV line per (case, build) carries the counter values
   read around the call.

   Cases whose name starts with g_ fail the runtime guard (n < 1, e % h != 0,
   h < 1).  On those the attn build evaluates the guard and then runs the same
   loops as the loops build, so the difference between the two lines for one
   case is what the guard costs.  */

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include "bm.h"

typedef void mha_fn (float *, const float *, const float *, const float *,
		     const float *, const float *, const float *, const float *,
		     const float *, const float *, int, int, int);
mha_fn mha_attn, mha_loops;

struct shape
{
  const char *name;
  int n, e, h;
};

/* Valid sizes span the descriptor's range; the g_ cases exercise the guard
   without doing the work of a large invalid n.  */
static const struct shape cases[] = {
  {"tiny", 4, 8, 2},
  {"small", 8, 16, 4},
  {"medium", 16, 32, 4},
  {"wide", 16, 64, 8},
  {"tall", 32, 64, 8},
  {"large", 64, 128, 8},
  {"g_n0", 0, 32, 4},
  {"g_erem", 8, 33, 8},
  {"g_h0", 8, 32, 0},
};

static uint32_t seed = 12345;

static float *
filled (int count, float scale)
{
  float *p = malloc (sizeof (float) * (count > 0 ? count : 1));
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

static uint64_t
cycles (void)
{
  uint64_t v;
  __asm__ volatile ("csrr %0, mcycle" : "=r" (v));
  return v;
}

/* One row: case,n,e,h,build,instret,cycles,maxdiff.  */
static void
row (const struct shape *s, const char *build, uint64_t ins, uint64_t cyc,
     uint32_t diff)
{
  bm_puts (s->name);
  bm_puts (",");
  putdec (s->n);
  bm_puts (",");
  putdec (s->e);
  bm_puts (",");
  putdec (s->h);
  bm_puts (",");
  bm_puts (build);
  bm_puts (",");
  putdec (ins);
  bm_puts (",");
  putdec (cyc);
  bm_puts (",");
  bm_puthex (diff);
  bm_puts ("\n");
}

int
main (void)
{
  bm_puts ("case,n,e,h,build,instret,cycles,maxdiff\n");
  for (unsigned k = 0; k < sizeof cases / sizeof cases[0]; k++)
    {
      const struct shape *s = &cases[k];
      int n = s->n, e = s->e, h = s->h;
      float w = 1.0f / sqrtf ((float) e);
      float *x = filled (n * e, 1.0f);
      float *wq = filled (e * e, w), *wk = filled (e * e, w);
      float *wv = filled (e * e, w), *wo = filled (e * e, w);
      float *bq = filled (e, 0.1f), *bk = filled (e, 0.1f);
      float *bv = filled (e, 0.1f), *bo = filled (e, 0.1f);
      float *y1 = malloc (sizeof (float) * (n * e > 0 ? n * e : 1));
      float *y2 = malloc (sizeof (float) * (n * e > 0 ? n * e : 1));

      /* Warm the heap and the instruction cache path once, unmeasured: the
	 first call grows the heap, which would price allocation, not attn.  */
      mha_attn (y1, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      mha_loops (y2, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);

      uint64_t i0 = instret (), c0 = cycles ();
      mha_attn (y1, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      uint64_t i1 = instret (), c1 = cycles ();
      mha_loops (y2, x, wq, wk, wv, wo, bq, bk, bv, bo, n, e, h);
      uint64_t i2 = instret (), c2 = cycles ();

      uint32_t diff = 0;
      if (s->name[0] != 'g')
	for (int i = 0; i < n * e; i++)
	  {
	    float d = fabsf (y1[i] - y2[i]);
	    if (!(d <= 1e-5f))
	      diff = 0xffffffffu;
	  }
      else
	diff = 0;
      row (s, "attn", i1 - i0, c1 - c0, diff);
      row (s, "loops", i2 - i1, c2 - c1, 0);
    }
  bm_puts ("perf: done\n");
  return 0;
}

