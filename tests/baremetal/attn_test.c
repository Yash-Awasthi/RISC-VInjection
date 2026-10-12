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
      check (bm_trap_cause == ~0ull && bad == t->bytes, t->name);
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
