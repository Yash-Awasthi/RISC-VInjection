# SPDX-License-Identifier: GPL-3.0-or-later
"""attn_core.h (the code Spike and QEMU run) against tools/attn_model.py."""

import ctypes
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402
import tolerances  # noqa: E402


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


run = attn_host.run


def test_layout_matches_c(lib):
    layout = (ctypes.c_uint32 * 20).in_dll(lib, "attn_host_layout")
    sizes = [struct.calcsize(am.WEIGHTS_FMT), struct.calcsize(am.CFG_FMT)]
    offs = [8 * i for i in range(8)] + [0, 4, 8, 12, 16, 20, 22, 24, 28, 32]
    assert list(layout) == sizes + offs


CASES = {
    "f32_1head": dict(n=5, e=8, h=1),
    "f32_4head_bias": dict(n=16, e=32, h=4),
    "f32_nobias": dict(n=7, e=12, h=3, bias=False),
    "f32_causal": dict(n=9, e=16, h=2, flags=am.F_CAUSAL),
    "f32_mask": dict(n=11, e=16, h=4, mask=True),
    "f32_causal_mask": dict(n=11, e=16, h=4, mask=True, flags=am.F_CAUSAL),
    "f32_gqa": dict(n=10, e=32, h=8, h_kv=2),
    "f32_mqa": dict(n=10, e=32, h=4, h_kv=1),
    "f32_scale": dict(n=6, e=8, h=2, scale=0.3),
    "bf16_in_f32_out": dict(n=16, e=32, h=4, in_dt=am.DT_BF16),
    "bf16_in_bf16_out": dict(n=16, e=32, h=4, in_dt=am.DT_BF16,
                             out_dt=am.DT_BF16, flags=am.F_CAUSAL),
    "f32_in_bf16_out": dict(n=8, e=16, h=2, out_dt=am.DT_BF16),
    "gpt2_small_head": dict(n=32, e=64, h=1, flags=am.F_CAUSAL),
}


@pytest.mark.parametrize("name", CASES)
def test_matches_reference(lib, name):
    case = am.Case(np.random.default_rng(len(name)), **CASES[name])
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    exp = am.round_dtype(case.expected(), case.out_dt)
    np.testing.assert_allclose(y, exp, rtol=0, atol=case.tolerance())


def test_fully_masked_row_is_nan(lib):
    case = am.Case(np.random.default_rng(1), n=4, e=8, h=2, bias=False,
                   mask=True)
    case.mask[2, :] = -np.inf
    mp = struct.unpack_from("<Q", case.image.buf,
                            case.c_addr - case.image.base + 32)[0]
    o = mp - case.image.base
    case.image.buf[o:o + case.mask.nbytes] = case.mask.tobytes()
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    assert np.all(np.isnan(y[2]))
    keep = [0, 1, 3]
    np.testing.assert_allclose(y[keep], case.expected()[keep],
                               atol=tolerances.ATOL_F32)


def bad_cfg(**kw):
    case = am.Case(np.random.default_rng(0), n=4, e=8, h=2)
    vals = dict(zip(am.CFG_FIELDS, struct.unpack_from(
        am.CFG_FMT, case.image.buf, case.c_addr - case.image.base)))
    vals.update(kw)
    struct.pack_into(am.CFG_FMT, case.image.buf, case.c_addr - case.image.base,
                     *[vals[f] for f in am.CFG_FIELDS])
    return case


@pytest.mark.parametrize("kw", [dict(n=0), dict(e=0), dict(h=0), dict(e=9),
                                dict(h_kv=3), dict(flags=4), dict(reserved=1),
                                dict(in_dtype=2), dict(out_dtype=7),
                                dict(n=4097), dict(e=4096, h=1)])
def test_reserved_config_is_illegal(lib, kw):
    rc, _ = run(lib, bad_cfg(**kw))
    assert rc == 1


def test_rv32_rejects_high_pointer_bits(lib):
    assert run(lib, bad_cfg(mask=1 << 40), xlen=32)[0] == 1
    assert run(lib, bad_cfg(), xlen=32)[0] == 0


def test_bit_exact_and_deterministic(lib):
    case = am.Case(np.random.default_rng(9), n=12, e=24, h=3, mask=True)
    assert run(lib, case)[1] == run(lib, case)[1]


def test_encoding():
    w = am.encode(13, 10, 11, 12)
    assert w == 0x66B516FB
    assert am.decode(w) == dict(rd=13, rs1=10, rs2=11, rs3=12)


@pytest.mark.parametrize("copy", ["spike/riscv", "qemu/target/riscv",
                                  "gcc/libgcc"])
def test_simulator_cores_match_include(copy):
    for name in ("attn_abi.h", "attn_core.h"):
        assert (REPO / copy / name).read_bytes() == \
            (REPO / "include" / name).read_bytes(), \
            "%s/%s differs from include/; copy it over" % (copy, name)


def weight_ptr(case, name):
    """Address of one matrix inside the case's attn_weights descriptor."""
    k = am.WEIGHTS_FIELDS.index(name)
    return struct.unpack_from("<Q", case.image.buf,
                              case.w_addr - case.image.base + 8 * k)[0]


def set_matrix(case, name, mat):
    """Overwrite one weight matrix in place and keep the Case in step."""
    mat = np.ascontiguousarray(mat, np.float32)
    off = weight_ptr(case, name) - case.image.base
    case.image.buf[off:off + mat.nbytes] = mat.tobytes()
    setattr(case, name, mat)


def test_tied_scores_split_the_softmax_mass_evenly(lib):
    """Wk = 0 ties every score, so each key gets 1/n and Y is the row mean."""
    case = am.Case(np.random.default_rng(11), n=4, e=4, h=1, bias=False)
    d = case.e // case.h
    set_matrix(case, "wk", np.zeros((case.e, d), np.float32))
    set_matrix(case, "wv", np.eye(case.e, dtype=np.float32))
    set_matrix(case, "wo", np.eye(case.e, dtype=np.float32))
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    want = case.x.astype(np.float64).mean(axis=0)
    np.testing.assert_allclose(y, np.tile(want, (case.n, 1)),
                               rtol=0, atol=tolerances.ATOL_F32)
    np.testing.assert_array_equal(y, np.tile(y[0], (case.n, 1)))
    np.testing.assert_allclose(y, case.expected(), rtol=0,
                               atol=case.tolerance())


def test_tied_scores_under_causal_average_the_prefix(lib):
    """A tie over the causal key range 0..i averages rows 0..i of V."""
    case = am.Case(np.random.default_rng(13), n=5, e=4, h=1, bias=False,
                   flags=am.F_CAUSAL)
    d = case.e // case.h
    set_matrix(case, "wk", np.zeros((case.e, d), np.float32))
    set_matrix(case, "wv", np.eye(case.e, dtype=np.float32))
    set_matrix(case, "wo", np.eye(case.e, dtype=np.float32))
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    for i in range(case.n):
        want = case.x[:i + 1].astype(np.float64).mean(axis=0)
        np.testing.assert_allclose(y[i], want, rtol=0,
                                   atol=tolerances.ATOL_F32)
    np.testing.assert_allclose(y, case.expected(), rtol=0,
                               atol=case.tolerance())


def test_fully_masked_row_under_causal_is_nan(lib):
    """Causal truncates the key range; a row that is -inf over it is NaN."""
    case = am.Case(np.random.default_rng(12), n=5, e=8, h=2, bias=False,
                   mask=True, flags=am.F_CAUSAL)
    case.mask[3, :] = -np.inf
    mp = struct.unpack_from("<Q", case.image.buf,
                            case.c_addr - case.image.base + 32)[0]
    off = mp - case.image.base
    case.image.buf[off:off + case.mask.nbytes] = case.mask.tobytes()
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    exp = case.expected()
    assert np.all(np.isnan(y[3]))
    assert np.all(np.isnan(exp[3]))
    keep = [0, 1, 2, 4]
    np.testing.assert_allclose(y[keep], exp[keep], rtol=0,
                               atol=case.tolerance())


DTYPE_PAIRS = [(am.DT_F32, am.DT_F32), (am.DT_F32, am.DT_BF16),
               (am.DT_BF16, am.DT_F32), (am.DT_BF16, am.DT_BF16)]


@pytest.mark.parametrize("in_dt,out_dt", DTYPE_PAIRS)
def test_every_dtype_combination_is_legal(lib, in_dt, out_dt):
    """in_dtype and out_dtype are each 0 or 1; all four pairs compute."""
    case = am.Case(np.random.default_rng(5), n=6, e=8, h=2,
                   in_dt=in_dt, out_dt=out_dt)
    rc, mem = run(lib, case)
    assert rc == 0
    np.testing.assert_allclose(case.read_y(mem),
                               am.round_dtype(case.expected(), out_dt),
                               rtol=0, atol=case.tolerance())


def set_x(case, x):
    """Overwrite X in guest memory, f32 only (the non-finite cases)."""
    case.x = np.ascontiguousarray(x, np.float32)
    off = case.x_addr - case.image.base
    case.image.buf[off:off + case.x.nbytes] = case.x.tobytes()


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_operand_propagates_without_a_trap(lib, value):
    """Section 3: NaN propagates; an infinite operand behaves as IEEE 754 says."""
    case = am.Case(np.random.default_rng(6), n=3, e=8, h=2, bias=False)
    x = case.x.copy()
    x[0, 0] = value
    set_x(case, x)
    rc, mem = run(lib, case)
    assert rc == 0, "a non-finite operand must not trap"
    y = case.read_y(mem)
    exp = case.expected()
    assert np.isnan(y).any(), "the non-finite operand vanished from Y"
    np.testing.assert_array_equal(np.isnan(y), np.isnan(exp))
    fin = np.isfinite(exp)
    np.testing.assert_allclose(y[fin], exp[fin], rtol=0,
                               atol=case.tolerance())


def test_subnormal_operand_reaches_the_output_unflushed(lib):
    """2**-149 with identity weights is a pass-through: no flush to zero."""
    tiny = np.float32(2.0 ** -149)
    case = am.Case(np.random.default_rng(0), n=1, e=2, h=1, bias=False)
    x = np.zeros((1, 2), np.float32)
    x[0, 0] = tiny
    set_x(case, x)
    eye = np.eye(2, dtype=np.float32)
    for name in ("wq", "wk", "wv", "wo"):
        set_matrix(case, name, eye)
    rc, mem = run(lib, case)
    assert rc == 0
    y = case.read_y(mem)
    assert struct.unpack("<I", y[0, 0].tobytes())[0] == 0x00000001, y
    assert y[0, 1] == 0.0


def bad_weights(**kw):
    """A valid case with fields of the attn_weights descriptor replaced."""
    case = am.Case(np.random.default_rng(0), n=4, e=8, h=2)
    off = case.w_addr - case.image.base
    vals = dict(zip(am.WEIGHTS_FIELDS,
                    struct.unpack_from(am.WEIGHTS_FMT, case.image.buf, off)))
    vals.update(kw)
    struct.pack_into(am.WEIGHTS_FMT, case.image.buf, off,
                     *[vals[f] for f in am.WEIGHTS_FIELDS])
    return case


@pytest.mark.parametrize("field", ["wq", "wk", "wv", "wo"])
def test_zero_weight_pointer_is_illegal(lib, field):
    """Section 4: a weight matrix pointer of 0 is a reserved configuration."""
    rc, _ = run(lib, bad_weights(**{field: 0}))
    assert rc == 1


@pytest.mark.parametrize("field", ["wq", "wk", "wv", "wo",
                                   "bq", "bk", "bv", "bo"])
def test_rv32_rejects_a_wide_weight_pointer(lib, field):
    """Section 4: on RV32 every 64-bit pointer in rs2 must fit in 32 bits."""
    assert run(lib, bad_weights(**{field: 1 << 32}), xlen=32)[0] == 1
