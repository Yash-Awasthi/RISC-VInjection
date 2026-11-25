/* SPDX-License-Identifier: GPL-3.0-or-later */
/* libFuzzer harness for the host model of attn.

   One input is the raw bytes of struct attn_weights (64), struct attn_cfg
   (40) and then the X matrix in in_dtype.  The descriptors are placed in a
   zeroed guest image and read back through the attn_mem callbacks, exactly
   as the simulators do.  n, e are clamped to small values so an input runs
   fast; oversized reserved values pass through, because the header, not this
   harness, owns rejection.  Non-zero pointers in the input select the
   matching image region; zero stays zero, which keeps the "no bias" path.

   Invariants checked after a successful call: no sanitizer report (build
   flags), no signalling NaN in Y, and Y is identical when the same call is
   executed a second time.  */

#include <stdint.h>
#include <string.h>
#include "attn_core.h"

#define IMG_SIZE 0x2400u

#define A_X 0x0000u
#define A_WQ 0x0400u
#define A_WK 0x0800u
#define A_WV 0x0c00u
#define A_WO 0x1000u
#define A_BQ 0x1400u
#define A_BK 0x1440u
#define A_BV 0x1480u
#define A_BO 0x14c0u
#define A_M 0x1500u
#define A_Y 0x1600u
#define A_WD 0x2000u
#define A_CD 0x2040u

struct fuzz_mem
{
  unsigned char *mem;
  int fault;
};

static int
oob (struct fuzz_mem *f, uint64_t a, unsigned len)
{
  if (a > IMG_SIZE || IMG_SIZE - a < len)
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
      memcpy (&v, ((struct fuzz_mem *) ctx)->mem + a, bits / 8);	\
    return v;								\
  }
LD (16) LD (32) LD (64)

static void
st16 (void *ctx, uint64_t a, uint16_t v)
{
  if (!oob (ctx, a, 2))
    memcpy (((struct fuzz_mem *) ctx)->mem + a, &v, 2);
}

static void
st32 (void *ctx, uint64_t a, uint32_t v)
{
  if (!oob (ctx, a, 4))
    memcpy (((struct fuzz_mem *) ctx)->mem + a, &v, 4);
}

/* Repeat the X payload over every matrix region so NaN, Inf, denormal and
   large-magnitude patterns reach the arithmetic and not only X.  */
static void
spread (unsigned char *mem, uint64_t at, uint64_t len,
	const unsigned char *src, uint64_t srclen)
{
  if (!srclen)
    return;
  for (uint64_t i = 0; i < len; i++)
    mem[at + i] = src[i % srclen];
}

static uint64_t
copy_in (const uint8_t *data, size_t size, uint64_t off, void *dst,
	 uint64_t len)
{
  uint64_t avail = off < size ? size - off : 0;
  uint64_t take = avail < len ? avail : len;
  if (take)
    memcpy (dst, data + off, (size_t) take);
  return take;
}

/* Signal an invariant violation as a fuzzer-visible crash.  */
static void
fail (void)
{
  __builtin_trap ();
}

static int
is_snan32 (uint32_t u)
{
  return (u & 0x7f800000u) == 0x7f800000u && (u & 0x007fffffu) != 0
	 && (u & 0x00400000u) == 0;
}

static int
is_snan16 (uint16_t u)
{
  return (u & 0x7f80u) == 0x7f80u && (u & 0x007fu) != 0
	 && (u & 0x0040u) == 0;
}

int
LLVMFuzzerTestOneInput (const uint8_t *data, size_t size)
{
  static unsigned char mem[IMG_SIZE];
  static float scratch[65536];
  struct fuzz_mem f = { mem, 0 };
  struct attn_mem m = { &f, ld16, ld32, ld64, st16, st32 };
  struct attn_weights w;
  struct attn_cfg c;
  unsigned char ycopy[0x400];
  uint64_t floats, xbytes, wbytes, ybytes, xlen;

  memset (mem, 0, sizeof mem);
  memset (&w, 0, sizeof w);
  memset (&c, 0, sizeof c);
  copy_in (data, size, 0, &w, sizeof w);
  copy_in (data, size, sizeof w, &c, sizeof c);

  /* Clamp only values the header would accept; reserved magnitudes stay so
     attn_scratch_floats can reject them.  */
  if (c.n <= ATTN_MAX_N)
    c.n %= 8;
  if (c.e <= ATTN_MAX_E)
    c.e %= 16;

  w.wq = w.wq ? A_WQ : 0;
  w.wk = w.wk ? A_WK : 0;
  w.wv = w.wv ? A_WV : 0;
  w.wo = w.wo ? A_WO : 0;
  w.bq = w.bq ? A_BQ : 0;
  w.bk = w.bk ? A_BK : 0;
  w.bv = w.bv ? A_BV : 0;
  w.bo = w.bo ? A_BO : 0;
  c.mask = c.mask ? A_M : 0;

  memcpy (mem + A_WD, &w, sizeof w);
  memcpy (mem + A_CD, &c, sizeof c);

  attn_read_desc (&m, A_WD, A_CD, &w, &c);
  if (f.fault)
    return 0;
  floats = attn_scratch_floats (&c, &w, 64);
  if (!floats)
    return 0;
  if (floats > sizeof scratch / sizeof scratch[0])
    return 0;

  xbytes = (uint64_t) c.n * c.e * (c.in_dtype == ATTN_DT_BF16 ? 2u : 4u);
  wbytes = (uint64_t) c.e * c.e * (c.in_dtype == ATTN_DT_BF16 ? 2u : 4u);
  ybytes = (uint64_t) c.n * c.e * (c.out_dtype == ATTN_DT_BF16 ? 2u : 4u);
  if (xbytes > 0x400u || wbytes > 0x400u || ybytes > 0x400u)
    return 0;

  xlen = copy_in (data, size, sizeof w + sizeof c, mem + A_X,
		  xbytes < 0x400u ? xbytes : 0x400u);
  spread (mem, A_WQ, 0x400u, mem + A_X, xlen);
  spread (mem, A_WK, 0x400u, mem + A_X, xlen);
  spread (mem, A_WV, 0x400u, mem + A_X, xlen);
  spread (mem, A_WO, 0x400u, mem + A_X, xlen);
  spread (mem, A_BQ, 0x40u, mem + A_X, xlen);
  spread (mem, A_BK, 0x40u, mem + A_X, xlen);
  spread (mem, A_BV, 0x40u, mem + A_X, xlen);
  spread (mem, A_BO, 0x40u, mem + A_X, xlen);
  spread (mem, A_M, 0x100u, mem + A_X, xlen);

  memset (mem + A_Y, 0, ybytes);

  attn_execute (&m, A_Y, A_X, &w, &c, scratch);
  if (f.fault)
    return 0;

  if (c.out_dtype == ATTN_DT_BF16)
    {
      for (uint64_t i = 0; i < c.n * c.e; i++)
	if (is_snan16 ((uint16_t) ld16 (&f, A_Y + 2 * i)))
	  fail ();
    }
  else
    {
      for (uint64_t i = 0; i < c.n * c.e; i++)
	if (is_snan32 (ld32 (&f, A_Y + 4 * i)))
	  fail ();
    }

  memcpy (ycopy, mem + A_Y, (size_t) ybytes);
  memset (mem + A_Y, 0, ybytes);
  {
    struct attn_weights w2;
    struct attn_cfg c2;
    attn_read_desc (&m, A_WD, A_CD, &w2, &c2);
    if (f.fault)
      return 0;
    attn_execute (&m, A_Y, A_X, &w2, &c2, scratch);
  }
  if (f.fault)
    return 0;
  if (memcmp (ycopy, mem + A_Y, (size_t) ybytes))
    fail ();

  return 0;
}
