/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Executes attn on Spike or QEMU and checks every byte of Y against the
   host-computed reference, then checks the trap behaviour.  Exit code 0 means
   every check passed.  */

#include <stddef.h>
#include <stdint.h>
#include "bm.h"
#include "attn_abi.h"

#if defined(__riscv_xattn)
#include "attn.h"
#define ATTN(y, x, w, c) attn_mha ((y), (x), (w), (c))
#else
/* Toolchains without Xattn reach the same encoding through .insn.  */
#define ATTN(y, x, w, c)						\
  __asm__ volatile (".insn r4 CUSTOM_3, 1, 3, %0, %1, %2, %3"		\
		    : : "r" (y), "r" (x), "r" (w), "r" (c) : "memory")
#endif

struct attn_case
{
  const char *name;
  uint8_t *y;
  const void *x;
  const struct attn_weights *w;
  const struct attn_cfg *c;
  const uint8_t *expect;
  size_t bytes;
};

#include "cases.h"

static int failures;

static void
check (int ok, const char *what)
{
  bm_puts (ok ? "PASS " : "FAIL ");
  bm_puts (what);
  if (!ok)
    {
      bm_puts (" mcause=");
      bm_puthex (bm_trap_cause);
      bm_puts (" mtval=");
      bm_puthex (bm_trap_tval);
    }
  bm_puts ("\n");
  failures += !ok;
}

static int
filled (const uint8_t *p, size_t n, uint8_t v)
{
  for (size_t i = 0; i < n; i++)
    if (p[i] != v)
      return 0;
  return 1;
}

/* Largest |Y - reference| over the elements, as a float, printed as its IEEE
   bits because there is no printf here.  A zero bit pattern is exact
   equality, which is what the three executions are expected to show.  */
static uint32_t
max_abs_diff (const uint8_t *y, const uint8_t *expect, size_t bytes, int is_f32,
	      int is_bf16)
{
  float worst = 0.0f;
  size_t n = is_f32 ? bytes / 4 : bytes / 2;

  for (size_t i = 0; i < n; i++)
    {
      float a, b;
      if (is_f32)
	{
	  uint32_t ua, ub;
	  __builtin_memcpy (&ua, y + 4 * i, 4);
	  __builtin_memcpy (&ub, expect + 4 * i, 4);
	  __builtin_memcpy (&a, &ua, 4);
	  __builtin_memcpy (&b, &ub, 4);
	}
      else if (is_bf16)
	{
	  uint32_t ua = 0, ub = 0;
	  __builtin_memcpy (&ua, y + 2 * i, 2);
	  __builtin_memcpy (&ub, expect + 2 * i, 2);
	  ua <<= 16;
	  ub <<= 16;
	  __builtin_memcpy (&a, &ua, 4);
	  __builtin_memcpy (&b, &ub, 4);
	}
      else
	return 0xffffffffu;
      float d = a - b;
      if (d < 0.0f)
	d = -d;
      if (d > worst)
	worst = d;
    }
  uint32_t bits;
  __builtin_memcpy (&bits, &worst, 4);
  return bits;
}

int
main (void)
{
  for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++)
    {
      const struct attn_case *t = &cases[i];
      size_t bad = t->bytes;

      for (size_t j = 0; j < t->bytes; j++)
	t->y[j] = 0xa5;
      bm_trap_cause = ~0ull;
      ATTN (t->y, t->x, t->w, t->c);
      for (size_t j = 0; j < t->bytes; j++)
	if (t->y[j] != t->expect[j])
	  {
	    bad = j;
	    break;
	  }
      int ok = bm_trap_cause == ~0ull && bad == t->bytes;
      bm_puts (ok ? "PASS " : "FAIL ");
      bm_puts (t->name);
      bm_puts (" maxdiff=");
      bm_puthex (max_abs_diff (t->y, t->expect, t->bytes,
			       t->c->out_dtype == ATTN_DT_F32,
			       t->c->out_dtype == ATTN_DT_BF16));
      if (!ok)
	{
	  bm_puts (" mcause=");
	  bm_puthex (bm_trap_cause);
	  bm_puts (" mtval=");
	  bm_puthex (bm_trap_tval);
	}
      bm_puts ("\n");
      failures += !ok;
    }

#ifndef BM_LINUX
  /* Traps are checked bare-metal; under Linux they would be signals.  */
  /* A reserved configuration traps as illegal and leaves Y alone.  */
  {
    const struct attn_case *t = &cases[0];
    struct attn_cfg c = *t->c;
    c.h = 3;	/* e = 8 is not a multiple of 3 */
    for (size_t j = 0; j < t->bytes; j++)
      t->y[j] = 0x5a;
    bm_trap_cause = ~0ull;
    ATTN (t->y, t->x, t->w, &c);
    check (bm_trap_cause == 2 && filled (t->y, t->bytes, 0x5a),
	   "illegal_config_traps");
  }

  /* A load fault on X reports the bad address and leaves Y alone.  */
  {
    const struct attn_case *t = &cases[0];
    const uintptr_t bad = 0x200000000ull;
    bm_trap_cause = ~0ull;
    ATTN (t->y, (const void *) bad, t->w, t->c);
    check (bm_trap_cause == 5 && bm_trap_tval == bad
	   && filled (t->y, t->bytes, 0x5a), "load_fault_precise");
  }

  /* After a fault the instruction simply re-executes to completion.  */
  {
    const struct attn_case *t = &cases[0];
    size_t ok = 1;
    bm_trap_cause = ~0ull;
    ATTN (t->y, t->x, t->w, t->c);
    for (size_t j = 0; j < t->bytes; j++)
      ok &= t->y[j] == t->expect[j];
    check (bm_trap_cause == ~0ull && ok, "reexecute_after_fault");
  }
#endif

  bm_puts (failures ? "attn_test: FAILED\n" : "attn_test: all passed\n");
  return failures;
}
