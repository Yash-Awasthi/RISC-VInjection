#include "bm.h"

volatile uint64_t bm_trap_cause = ~0ull, bm_trap_tval;
#ifndef BM_LINUX
extern volatile uint64_t tohost;
#endif

#define UART ((volatile uint8_t *) 0x10000000)

#ifdef BM_LINUX
static long
bm_syscall (long n, long a, long b, long c)
{
  register long a0 __asm__ ("a0") = a, a1 __asm__ ("a1") = b;
  register long a2 __asm__ ("a2") = c, a7 __asm__ ("a7") = n;
  __asm__ volatile ("ecall" : "+r" (a0) : "r" (a1), "r" (a2), "r" (a7)
		    : "memory");
  return a0;
}
#endif

void
bm_putc (char c)
{
#if defined (BM_LINUX)
  bm_syscall (64, 1, (long) &c, 1);	/* write */
#elif defined (BM_SPIKE)
  /* HTIF console: device 1, command 1.  */
  /* The host clears tohost once it has consumed the character.  */
  while (tohost)
    ;
  tohost = (1ull << 56) | (1ull << 48) | (uint8_t) c;
#else
  while (!(UART[5] & 0x20))
    ;
  UART[0] = c;
#endif
}

void
bm_puts (const char *s)
{
  while (*s)
    bm_putc (*s++);
}

void
bm_puthex (uint64_t v)
{
  for (int i = 60; i >= 0; i -= 4)
    bm_putc ("0123456789abcdef"[(v >> i) & 15]);
}

void
bm_exit (int code)
{
#if defined (BM_LINUX)
  bm_syscall (94, code, 0, 0);		/* exit_group */
#elif defined (BM_SPIKE)
  while (tohost)
    ;
  tohost = ((uint64_t) code << 1) | 1;
#else
  /* sifive_test finisher on the virt board.  */
  *(volatile uint32_t *) 0x100000 = code ? ((uint32_t) code << 16) | 0x3333
					 : 0x5555;
#endif
  for (;;)
    ;
}

/* The compiler may turn byte loops into calls to these.  */
void *
memset (void *d, int c, unsigned long n)
{
  volatile unsigned char *p = d;
  while (n--)
    *p++ = (unsigned char) c;
  return d;
}

void *
memcpy (void *d, const void *s, unsigned long n)
{
  volatile unsigned char *p = d;
  const unsigned char *q = s;
  while (n--)
    *p++ = *q++;
  return d;
}

#ifndef BM_LINUX
/* Heap for newlib's malloc: from the end of the image up to 64 MiB into
   RAM, which both the QEMU virt board and Spike provide.  */
void *
_sbrk (long incr)
{
  extern char __heap_start[];
  static char *brk = __heap_start;
  char *old = brk;
  if (brk + incr > (char *) 0x84000000)
    return (void *) -1;
  brk += incr;
  return old;
}
#endif
