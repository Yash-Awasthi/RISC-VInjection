#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pins attn_model.fma; math.fma only exists from Python 3.13.

The frozen table below holds the exact a*b+c bits measured with math.fma on
Python 3.15 and re-derived with exact rationals, so the fallback is still
checked on a Python that has no math.fma at all.
"""

import importlib.util
import math
import random
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import attn_model as am

MAX = float.fromhex("0x1.fffffffffffffp+1023")
MIN_SUB = float.fromhex("0x0.0000000000001p-1022")
MIN_NORMAL = float.fromhex("0x1.0000000000000p-1022")

# a, b, c and the bits of the correctly rounded a*b + c (None: OverflowError).
# Each case is fused-vs-separate sensitive, all four hard groups are present:
# inexact products, cancelling sums, subnormals, and the overflow edge.
CASES = [
    (1 + 2**-27, 1 - 2**-27, -1.0, 0xBC90000000000000),
    (1 + 2**-12, 1 - 2**-12, -1.0, 0xBE70000000000000),
    (1 + 2**-52, 1 - 2**-52, -1.0, 0xB970000000000000),
    (1 + 2**-52, 1.0, 2.0**-53, 0x3FF0000000000002),
    (1 + 2**-52, 1 + 2**-52, -(1 + 2**-51), 0x3970000000000000),
    (1 + 2**-52, 1 + 2**-52, 2.0**-53, 0x3FF0000000000003),
    (MAX, 1.5, -MAX, 0x7FDFFFFFFFFFFFFF),
    (MAX, 2.0, -MAX, 0x7FEFFFFFFFFFFFFF),
    (MAX, 1.0, 2.0**970, None),
    (MAX, 2.0, 0.0, None),
    (MAX, 1.0, -MIN_SUB, 0x7FEFFFFFFFFFFFFF),
    (MIN_SUB, 1.0, MIN_SUB, 0x0000000000000002),
    (-MIN_SUB, 1.0, -MIN_SUB, 0x8000000000000002),
    (2.0**-537, 2.0**-537, 0.0, 0x0000000000000001),
    (2.0**-537, 2.0**-538, 0.0, 0x0000000000000000),
    (2.0**-537, 2.0**-538, MIN_SUB, 0x0000000000000002),
    (2.0**-500, 2.0**-500, -2.0**-1000, 0x0000000000000000),
    (MIN_NORMAL, 2.0**-1022, 0.0, 0x0000000000000000),
    (1.5, 1.5, -2.25, 0x0000000000000000),
    (2.0**500, 2.0**-500, -1.0, 0x0000000000000000),
    (2.0**1000, 2.0**-1000, -1.0, 0x0000000000000000),
    (1.0000000000000002, 1.0000000000000002, -1.0000000000000004,
     0x3970000000000000),
    (-1.0, 0.0, -0.0, 0x8000000000000000),
    (0.0, -0.0, 0.0, 0x0000000000000000),
    (-0.0, -0.0, -0.0, 0x0000000000000000),
    (1e-308, 1e-308, 0.0, 0x0000000000000000),
    (1e308, 1e-308, -1.0, 0xBC96F866F9236600),
    (123456789.0, 987654321.0, -1.2193263111263526e17, 0x4014000000000000),
    (2.0**1023, 2.0, -MAX, 0x7CA0000000000000),
]


def bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def outcome(fn, a, b, c):
    try:
        return bits(fn(a, b, c))
    except OverflowError:
        return None


@pytest.mark.parametrize("a,b,c,want", CASES)
def test_frozen_table_matches_fallback(a, b, c, want):
    assert outcome(am._fma_fallback, a, b, c) == want


@pytest.mark.parametrize("a,b,c,want", CASES)
def test_frozen_table_matches_native_math_fma(a, b, c, want):
    if getattr(math, "fma", None) is None:
        pytest.skip("math.fma needs Python 3.13; see the fallback test above")
    assert outcome(math.fma, a, b, c) == want


def test_fallback_matches_native_on_random_bits():
    native = getattr(math, "fma", None)
    if native is None:
        pytest.skip("math.fma needs Python 3.13; the frozen table covers this")
    rng = random.Random(20261126)
    checked = 0
    while checked < 500:
        a, b, c = (struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0]
                   for _ in range(3))
        if not all(math.isfinite(v) for v in (a, b, c)):
            continue
        assert outcome(am._fma_fallback, a, b, c) == outcome(native, a, b, c), (a, b, c)
        checked += 1


def _study_module():
    path = Path(__file__).with_name("test_study_answers.py")
    spec = importlib.util.spec_from_file_location("study_answers_no_fma", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_study_stage2_holds_with_math_fma_hidden(monkeypatch):
    monkeypatch.delattr(math, "fma", raising=False)
    assert not hasattr(math, "fma")
    _study_module().test_stage2_separate_add_loses_fused_keeps()


def test_forced_fallback_keeps_the_separation(monkeypatch):
    monkeypatch.delattr(math, "fma", raising=False)
    f = np.float32
    a = f(-(1 + 2**-12))
    b = f(1 + 2**-12)
    c = f(1 + 2**-11)
    sep = f(f(a * b) + c)
    fused = f(am.fma(float(a), float(b), float(c)))
    assert sep == f(0.0)
    assert fused == f(-2.0**-24)
    assert fused.tobytes()[::-1].hex() == "b3800000"
