/* attn.h -- C interface to the Xattn multi-head self-attention instruction.

   Compile with -march=..._xattn and attn_mha() becomes the single
   instruction `attn rd, rs1, rs2, rs3`.  Without Xattn (or on the host) the
   same call runs attn_core.h, the definition the simulators execute, so
   both builds produce bit-identical results.  */

#ifndef ATTN_H
#define ATTN_H

#include "attn_abi.h"

#if defined(__riscv_xattn)

static inline void
attn_mha (void *y, const void *x, const struct attn_weights *w,
	  const struct attn_cfg *c)
{
  __builtin_riscv_attn (y, x, w, c);
}

#else

#include <stdlib.h>
#include <string.h>
#include "attn_core.h"

static uint16_t attn_h_ld16 (void *c, uint64_t a)
{ uint16_t v; (void) c; memcpy (&v, (void *) (uintptr_t) a, 2); return v; }
static uint32_t attn_h_ld32 (void *c, uint64_t a)
{ uint32_t v; (void) c; memcpy (&v, (void *) (uintptr_t) a, 4); return v; }
static uint64_t attn_h_ld64 (void *c, uint64_t a)
{ uint64_t v; (void) c; memcpy (&v, (void *) (uintptr_t) a, 8); return v; }
static void attn_h_st16 (void *c, uint64_t a, uint16_t v)
{ (void) c; memcpy ((void *) (uintptr_t) a, &v, 2); }
static void attn_h_st32 (void *c, uint64_t a, uint32_t v)
{ (void) c; memcpy ((void *) (uintptr_t) a, &v, 4); }

/* Software fallback.  A configuration the instruction would reject with an
   illegal-instruction trap aborts here instead.  */
static inline void
attn_mha (void *y, const void *x, const struct attn_weights *w,
	  const struct attn_cfg *c)
{
  static const struct attn_mem m = { 0, attn_h_ld16, attn_h_ld32,
				     attn_h_ld64, attn_h_st16, attn_h_st32 };
  uint64_t floats = attn_scratch_floats (c, w, sizeof (void *) * 8);
  float *s;

  if (!floats || !(s = (float *) malloc (floats * sizeof (float))))
    abort ();
  attn_execute (&m, (uintptr_t) y, (uintptr_t) x, w, c, s);
  free (s);
}

#endif /* __riscv_xattn */

#endif /* ATTN_H */
