/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Thin host wrappers over include/attn_core.h so the accumulation order the
   header states can be checked bit for bit from Python.  */

#include <stdint.h>
#include "attn_core.h"

/* The header's pragma is popped at its end, so the transcription below needs
   the same setting; the sums must round once per product and once per add.  */
#if defined(__clang__)
#pragma clang fp contract(off)
#elif defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize("fp-contract=off")
#endif

void
order_matmul (const float *in, const float *w, const float *b, float *out,
	      int rows, int inner, int cols)
{
  attn_matmul (in, w, b, out, (uint64_t) rows, (uint64_t) inner,
	       (uint64_t) cols);
}

/* The score loop attn_execute runs, transcribed: q[t] * k[t] in ascending t,
   accumulated into acc.  The separate * scale is not exercised here.  */
float
order_score_row (const float *q, const float *k, int d)
{
  float acc = 0.0f;
  int t;

  for (t = 0; t < d; t++)
    acc = acc + q[t] * k[t];
  return acc;
}

#if !defined(__clang__) && defined(__GNUC__)
#pragma GCC pop_options
#endif
