# SPDX-License-Identifier: GPL-3.0-or-later
"""Shape boundaries of the attn descriptor, checked against attn_model.

Every case runs include/attn_core.h through the host build and compares Y
with tools/attn_model.Case.expected() at rtol=0.  Version 1.0 of the ABI has
no K/V cache field, so the plan's "n>cache" shape cannot be expressed and
that item is vacuous here.  The two descriptor maxima are read from
include/attn_abi.h, never hard-coded.
"""

import re
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402

ABI_H = (REPO / "include" / "attn_abi.h").read_text(encoding="utf-8")


def abi_macro(name):
    """Value of a numeric #define in include/attn_abi.h."""
    m = re.search(r"^#define\s+%s\s+(\d+)u?\b" % name, ABI_H, re.M)
    assert m, "include/attn_abi.h does not define %s" % name
    return int(m.group(1))


ATTN_MAX_N = abi_macro("ATTN_MAX_N")
ATTN_MAX_E = abi_macro("ATTN_MAX_E")


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


run = attn_host.run


def check(lib, case):
    """Run one case on the core and compare Y with the float64 model."""
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    exp = am.round_dtype(case.expected(), case.out_dt)
    np.testing.assert_allclose(y, exp, rtol=0, atol=case.tolerance())
    return mem


def y_bytes(case, mem):
    """Raw Y bytes, independent of where the rest of the image sits."""
    off = case.y_addr - case.image.base
    nbytes = case.n * case.e * (2 if case.out_dt == am.DT_BF16 else 4)
    return bytes(mem[off:off + nbytes])


def zero_mask_case(seed, n, e, h, flags):
    """A Case with a mask allocation whose bytes are all zero."""
    case = am.Case(np.random.default_rng(seed), n=n, e=e, h=h, mask=True,
                   flags=flags)
    mp = struct.unpack_from("<Q", case.image.buf,
                            case.c_addr - case.image.base + 32)[0]
    assert mp, "mask-allocated Case has a null mask pointer"
    o = mp - case.image.base
    case.image.buf[o:o + case.mask.nbytes] = bytes(case.mask.nbytes)
    return case


def bad_cfg(**kw):
    """A small Case whose cfg fields are overwritten with kw."""
    case = am.Case(np.random.default_rng(0), n=4, e=8, h=2)
    off = case.c_addr - case.image.base
    vals = dict(zip(am.CFG_FIELDS,
                    struct.unpack_from(am.CFG_FMT, case.image.buf, off)))
    vals.update(kw)
    struct.pack_into(am.CFG_FMT, case.image.buf, off,
                     *[vals[f] for f in am.CFG_FIELDS])
    return case


def test_smallest_shape(lib):
    """n=1, e=1, h=1: one query, one key, one head of width one."""
    check(lib, am.Case(np.random.default_rng(1), n=1, e=1, h=1, bias=False))


def test_smallest_shape_bias_bf16(lib):
    """The same shape with biases and bf16 in and out."""
    check(lib, am.Case(np.random.default_rng(2), n=1, e=1, h=1,
                       in_dt=am.DT_BF16, out_dt=am.DT_BF16))


def test_heads_equal_width(lib):
    """n=1, e=8, h=8: as many heads as the width, so head_dim is one."""
    check(lib, am.Case(np.random.default_rng(3), n=1, e=8, h=8))


@pytest.mark.parametrize("h_kv", [1, 4], ids=["mqa", "mha"])
def test_head_dim_one(lib, h_kv):
    """e=4, h=4, head_dim=1, with group 4 (MQA) and no grouping (MHA)."""
    check(lib, am.Case(np.random.default_rng(10 + h_kv), n=5, e=4, h=4,
                       h_kv=h_kv, flags=am.F_CAUSAL))


@pytest.mark.parametrize("flags", [0, am.F_CAUSAL], ids=["plain", "causal"])
def test_all_zero_mask_matches_no_mask(lib, flags):
    """An allocated all-zero mask must give the bytes of a null mask."""
    shape = dict(n=6, e=8, h=2, flags=flags)
    zeroed = zero_mask_case(7, **shape)
    plain = am.Case(np.random.default_rng(7), **shape)
    assert plain.mask is None

    rc, mem_zero = run(lib, zeroed)
    assert rc == 0
    rc, mem_plain = run(lib, plain)
    assert rc == 0
    assert y_bytes(zeroed, mem_zero) == y_bytes(plain, mem_plain)

    # Byte equality could hold for two identically wrong outputs; check the
    # model too.
    exp = am.round_dtype(plain.expected(), plain.out_dt)
    np.testing.assert_allclose(zeroed.read_y(mem_zero), exp, rtol=0,
                               atol=zeroed.tolerance())


def test_no_cache_field_in_abi():
    """n>cache is vacuous: no cfg field and no limit names a cache."""
    assert not [f for f in am.CFG_FIELDS if "cache" in f.lower()]
    # The header declares exactly two limits: ATTN_MAX_N bounds the sequence
    # length, ATTN_MAX_E the model width.  Neither is a K/V cache size.
    limits = set(re.findall(r"^#define\s+(ATTN_MAX_\w+)", ABI_H, re.M))
    assert limits == {"ATTN_MAX_N", "ATTN_MAX_E"}
    assert all("cache" not in m.lower() and "kv" not in m.lower()
               for m in limits)


@pytest.mark.parametrize("kw", [dict(n=ATTN_MAX_N + 1),
                                dict(e=ATTN_MAX_E + 1, h=1)],
                         ids=["n", "e"])
def test_one_past_maximum_is_illegal(lib, kw):
    """One past either descriptor maximum is refused before any access."""
    rc, _ = run(lib, bad_cfg(**kw))
    assert rc == 1


def test_max_e(lib):
    """e=ATTN_MAX_E with n=1, h=1: the width boundary."""
    check(lib, am.Case(np.random.default_rng(22), n=1, e=ATTN_MAX_E, h=1))


def test_max_n(lib):
    """n=ATTN_MAX_N with e=1, h=1: the sequence-length boundary.

    The core keeps a single n-float score row, but the float64 model
    materialises the n x n score matrix (~0.4 GB transient at this size), so
    this stays the heaviest case in the file.
    """
    check(lib, am.Case(np.random.default_rng(21), n=ATTN_MAX_N, e=1, h=1))
