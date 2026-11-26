/* SPDX-License-Identifier: GPL-3.0-or-later */
/* attn_core.h -- the one executable definition of the attn instruction.

   Umbrella for the two halves: attn_config.h holds the ATTN_* configuration
   macros and portability switches, attn_kernels.h holds the numeric kernels.
   Existing callers keep including this header; every simulator and the host
   reference get the same definition.  Header-only, and C89-clean so the
   simulators can include it from strict C and from C++.

   Guest memory is reached only through struct attn_mem; a load or store
   callback may trap (C++ throw or longjmp), so this code owns no resources:
   the caller supplies the scratch buffer.  */

#ifndef ATTN_CORE_H
#define ATTN_CORE_H

#include "attn_config.h"
#include "attn_kernels.h"

#endif /* ATTN_CORE_H */
