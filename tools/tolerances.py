#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Absolute tolerances for comparing attn output with the float64 model.

Binary32 unit roundoff is u = 2**-24; every dot product sums at most e = 64
terms in index order, so gamma_e = e*u/(1 - e*u) ~ 3.9e-6 bounds the relative
error.  The 14 frozen vectors of tests/vectors/ measure max |Y - Yref| =
1.43e-6, so ATOL_F32 = 1e-4 is a stated margin for expf/libm differences.
A bf16 output rounds that binary32 result to nearest even, at most half an
ulp: 2**-7 for |Y| < 4.  The bf16 vectors reach |Y| = 4.53 (half an ulp
2**-6 there) yet differ by 0, as both sides round the same binary32 value.
"""

import attn_model

ATOL_F32 = 1e-4
ATOL_BF16 = 2.0 ** -7
U32 = 2.0 ** -24


def for_dtype(out_dt):
    """Absolute tolerance for output dtype out_dt (attn_model.DT_*)."""
    return ATOL_BF16 if out_dt == attn_model.DT_BF16 else ATOL_F32
