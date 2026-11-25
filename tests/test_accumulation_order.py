# SPDX-License-Identifier: GPL-3.0-or-later
"""Assert the accumulation order include/attn_core.h states.

The simulator halves of that plan row are not exercised here: this tree has no
riscv64-unknown-elf-gcc in out/toolchain/bin and no out/spike or build/qemu.
attn_core.h is the single definition both simulators include unchanged, so
pinning its order from the host build pins them too.
"""

import ctypes
import re
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
HEADER = REPO / "include" / "attn_core.h"


def bits(x):
    return struct.unpack("<I", struct.pack("<f", float(x)))[0]


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    out = tmp_path_factory.mktemp("order")
    so = out / "attn_order.so"
    subprocess.run(["cc", "-std=c11", "-O2", "-march=native", "-Wall",
                    "-shared", "-fPIC", "-I", str(REPO / "include"),
                    str(REPO / "tests/host/attn_order.c"), "-o", str(so),
                    "-lm"], check=True)
    lib = ctypes.CDLL(str(so))
    fp = ctypes.POINTER(ctypes.c_float)
    lib.order_matmul.argtypes = [fp, fp, fp, fp,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.order_matmul.restype = None
    lib.order_score_row.argtypes = [fp, fp, ctypes.c_int]
    lib.order_score_row.restype = ctypes.c_float
    return lib


def asc_dot(a, b):
    acc = np.float32(0.0)
    for k in range(len(a)):
        acc = np.float32(acc + np.float32(a[k] * b[k]))
    return acc


def desc_dot(a, b):
    acc = np.float32(0.0)
    for k in range(len(a) - 1, -1, -1):
        acc = np.float32(acc + np.float32(a[k] * b[k]))
    return acc


def c_matmul(lib, a, w, b, rows, inner, cols):
    fp = ctypes.POINTER(ctypes.c_float)
    a = np.ascontiguousarray(a, dtype=np.float32)
    w = np.ascontiguousarray(w, dtype=np.float32)
    out = np.zeros(rows * cols, dtype=np.float32)
    ap = a.ctypes.data_as(fp)
    wp = w.ctypes.data_as(fp)
    op = out.ctypes.data_as(fp)
    bp = None
    if b is not None:
        b = np.ascontiguousarray(b, dtype=np.float32)
        bp = b.ctypes.data_as(fp)
    lib.order_matmul(ap, wp, bp, op, rows, inner, cols)
    return out


def c_score_row(lib, q, k):
    fp = ctypes.POINTER(ctypes.c_float)
    q = np.ascontiguousarray(q, dtype=np.float32)
    k = np.ascontiguousarray(k, dtype=np.float32)
    return lib.order_score_row(q.ctypes.data_as(fp), k.ctypes.data_as(fp),
                               len(q))


MATMUL_SHAPES = [(1, 1, 1), (5, 1, 5), (3, 7, 4), (5, 64, 5), (2, 64, 3)]


def test_header_states_the_order():
    text = HEADER.read_text(encoding="utf-8")
    assert "#pragma clang fp contract(off)" in text
    assert "fp-contract=off" in text
    assert "accumulated in k order" in text
    assert "fma(" not in text and "fmaf(" not in text
    assert re.search(r"^\s*acc = acc \+ .+ \* .+;$", text, re.MULTILINE)


@pytest.mark.parametrize("shape", MATMUL_SHAPES)
@pytest.mark.parametrize("bias", [False, True])
def test_matmul_matches_documented_order(lib, shape, bias):
    rows, inner, cols = shape
    rng = np.random.default_rng(rows * 100 + inner * 10 + cols + bias)
    a = rng.standard_normal((rows, inner), dtype=np.float32)
    w = rng.standard_normal((inner, cols), dtype=np.float32)
    b = rng.standard_normal(cols, dtype=np.float32) if bias else None
    got = c_matmul(lib, a, w, b, rows, inner, cols)
    for r in range(rows):
        for c in range(cols):
            acc = asc_dot(a[r], w[:, c])
            exp = np.float32(acc + b[c]) if bias else acc
            assert bits(got[r * cols + c]) == bits(exp), (shape, bias, r, c)


@pytest.mark.parametrize("d", [1, 33])
def test_score_row_matches_documented_order(lib, d):
    rng = np.random.default_rng(7000 + d)
    for trial in range(4):
        q = rng.standard_normal(d, dtype=np.float32)
        k = rng.standard_normal(d, dtype=np.float32)
        got = c_score_row(lib, q, k)
        exp = asc_dot(q, k)
        assert bits(got) == bits(exp), (d, trial, hex(bits(got)), hex(bits(exp)))


def test_a_reordered_sum_is_detected(lib):
    rng = np.random.default_rng(424242)
    differs = 0
    for trial in range(8):
        a = rng.standard_normal(64, dtype=np.float32)
        w = rng.standard_normal((64, 1), dtype=np.float32)
        got = c_matmul(lib, a, w, None, 1, 64, 1)
        exp = desc_dot(a, w[:, 0])
        if bits(got[0]) != bits(exp):
            differs += 1
    assert differs > 0
