/* Run on a hart without Xattn: attn must raise illegal-instruction.  */

#include "bm.h"

int
main (void)
{
  bm_trap_cause = ~0ull;
  __asm__ volatile (".insn r4 CUSTOM_3, 1, 3, a0, a0, a0, a0" ::: "memory");
  bm_puts (bm_trap_cause == 2 ? "PASS attn_without_xattn_is_illegal\n"
			      : "FAIL attn_without_xattn_is_illegal\n");
  return bm_trap_cause != 2;
}
