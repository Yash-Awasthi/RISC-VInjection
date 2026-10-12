/* Host build of attn_core.h over a flat byte array, loaded by the Python
   tests through ctypes.  Guest address A maps to mem[A].  */

#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include "attn_core.h"

struct flat { unsigned char *mem; uint64_t size; int fault; };

static int
oob (struct flat *f, uint64_t a, unsigned len)
{
  if (a > f->size || f->size - a < len)
    {
      f->fault = 1;
      return 1;
    }
  return 0;
}

#define LD(bits)							\
  static uint##bits##_t ld##bits (void *ctx, uint64_t a)		\
  {									\
    uint##bits##_t v = 0;						\
    if (!oob (ctx, a, bits / 8))					\
      memcpy (&v, ((struct flat *) ctx)->mem + a, bits / 8);		\
    return v;								\
  }
LD (16) LD (32) LD (64)

static void
st16 (void *ctx, uint64_t a, uint16_t v)
{
  if (!oob (ctx, a, 2))
    memcpy (((struct flat *) ctx)->mem + a, &v, 2);
}

static void
st32 (void *ctx, uint64_t a, uint32_t v)
{
  if (!oob (ctx, a, 4))
    memcpy (((struct flat *) ctx)->mem + a, &v, 4);
}

/* Returns 0 on success, 1 for an illegal configuration, 2 for an access
   outside mem.  */
int
attn_host_run (unsigned char *mem, uint64_t size, uint64_t y, uint64_t x,
	       uint64_t wa, uint64_t ca, unsigned xlen)
{
  struct flat f = { mem, size, 0 };
  struct attn_mem m = { &f, ld16, ld32, ld64, st16, st32 };
  struct attn_weights w;
  struct attn_cfg c;
  uint64_t floats;
  float *s;

  attn_read_desc (&m, wa, ca, &w, &c);
  if (f.fault)
    return 2;
  floats = attn_scratch_floats (&c, &w, xlen);
  if (!floats)
    return 1;
  s = malloc (floats * sizeof (float));
  if (!s)
    return 3;
  attn_execute (&m, y, x, &w, &c, s);
  free (s);
  return f.fault ? 2 : 0;
}

const uint32_t attn_host_layout[] = {
  sizeof (struct attn_weights), sizeof (struct attn_cfg),
  offsetof (struct attn_weights, wq), offsetof (struct attn_weights, wk),
  offsetof (struct attn_weights, wv), offsetof (struct attn_weights, wo),
  offsetof (struct attn_weights, bq), offsetof (struct attn_weights, bk),
  offsetof (struct attn_weights, bv), offsetof (struct attn_weights, bo),
  offsetof (struct attn_cfg, n), offsetof (struct attn_cfg, e),
  offsetof (struct attn_cfg, h), offsetof (struct attn_cfg, h_kv),
  offsetof (struct attn_cfg, flags), offsetof (struct attn_cfg, in_dtype),
  offsetof (struct attn_cfg, out_dtype), offsetof (struct attn_cfg, scale_bits),
  offsetof (struct attn_cfg, reserved), offsetof (struct attn_cfg, mask),
};
