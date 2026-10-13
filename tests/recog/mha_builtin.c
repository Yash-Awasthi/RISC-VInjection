/* The causal, biased block of demo/mha_plain.c through __builtin_attn.
   Built without Xattn, so GCC calls __attn in libgcc.  */

#include <stdint.h>
#include "attn_abi.h"

void
mha_builtin (float *y, const float *x, const float *wq, const float *wk,
	     const float *wv, const float *wo, const float *bq,
	     const float *bk, const float *bv, const float *bo, int n, int e,
	     int h)
{
  struct attn_weights w = {
    (uintptr_t) wq, (uintptr_t) wk, (uintptr_t) wv, (uintptr_t) wo,
    (uintptr_t) bq, (uintptr_t) bk, (uintptr_t) bv, (uintptr_t) bo };
  struct attn_cfg c = { n, e, h, 0, ATTN_F_CAUSAL, ATTN_DT_F32, ATTN_DT_F32,
			0, 0, 0 };
  __builtin_attn (y, x, &w, &c);
}
