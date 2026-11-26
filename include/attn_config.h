/* SPDX-License-Identifier: GPL-3.0-or-later */
/* attn_config.h -- portability and configuration for attn_core.h.

   Not a standalone header: attn_core.h includes it first and pops the GCC
   option stack at its end, so a translation unit reaches this file only
   through attn_core.h.  */

#ifndef ATTN_CONFIG_H
#define ATTN_CONFIG_H

#ifdef ATTN_FREESTANDING
/* libgcc has no libc headers; the calls still bind to libm.  */
#define expf __builtin_expf
#define sqrtf __builtin_sqrtf
#define INFINITY __builtin_inff ()
#else
#include <math.h>
#endif
/* C89 <math.h> has no INFINITY; the kernel needs it.  */
#ifndef INFINITY
#define INFINITY (__builtin_inff ())
#endif
#include <stdint.h>
#include "attn_abi.h"

/* C89 has no inline keyword; __inline__ keeps inline semantics and internal
   linkage in the C++ simulator builds.  */
#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 199901L
#define ATTN_INLINE static inline
#else
#define ATTN_INLINE static __inline__
#endif

/* Separate rounding of every product and sum is part of the definition.  */
#if defined(__clang__)
#pragma clang fp contract(off)
#elif defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize("fp-contract=off")
#endif

#endif /* ATTN_CONFIG_H */
