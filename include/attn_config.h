/* SPDX-License-Identifier: GPL-3.0-or-later */
/* attn_config.h -- configuration macros for the attn reference model.

   The numeric kernels are in attn_kernels.h, which includes this header; the
   umbrella attn_core.h includes both.  Only switches and portability macros
   live here, so they can be read without the code and the kernels stay
   free of preprocessor conditions.

   Header-only, and plain C89 apart from <stdint.h>: the kernels are compiled
   by the Spike and QEMU execution models and by the host reference.  */

#ifndef ATTN_CONFIG_H
#define ATTN_CONFIG_H

#include <stdint.h>
#include "attn_abi.h"

/* C89 has no inline keyword.  GCC and Clang accept __inline__ in that mode;
   every other supported compiler is C99 or C++.  */
#if defined(__cplusplus)
#define ATTN_INLINE static inline
#elif defined(__STDC_VERSION__) && __STDC_VERSION__ >= 199901L
#define ATTN_INLINE static inline
#elif defined(__GNUC__) || defined(__clang__)
#define ATTN_INLINE static __inline__
#else
#define ATTN_INLINE static
#endif

/* libgcc has no libc headers; the calls still bind to libm.  C89 <math.h> has
   neither the float functions nor INFINITY, so it uses the same builtins.  */
#if defined(ATTN_FREESTANDING)
#define ATTN_EXPF(x) __builtin_expf (x)
#define ATTN_SQRTF(x) __builtin_sqrtf (x)
#define ATTN_INF (__builtin_inff ())
#elif defined(__cplusplus) \
  || (defined(__STDC_VERSION__) && __STDC_VERSION__ >= 199901L)
#include <math.h>
#define ATTN_EXPF(x) expf (x)
#define ATTN_SQRTF(x) sqrtf (x)
#define ATTN_INF INFINITY
#else
#define ATTN_EXPF(x) __builtin_expf (x)
#define ATTN_SQRTF(x) __builtin_sqrtf (x)
#define ATTN_INF (__builtin_inff ())
#endif

#endif /* ATTN_CONFIG_H */
