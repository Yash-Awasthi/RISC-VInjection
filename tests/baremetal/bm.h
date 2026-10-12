/* Minimal bare-metal runtime for Spike (HTIF) and QEMU virt.  */

#ifndef BM_H
#define BM_H

#include <stdint.h>

extern volatile uint64_t bm_trap_cause, bm_trap_tval;
void bm_puts (const char *s);
void bm_puthex (uint64_t v);
void bm_exit (int code) __attribute__ ((noreturn));

#endif
