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
    np.testing.assert_allclose(y[keep], case.expected()[keep], atol=1e-4)


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


@pytest.mark.parametrize("copy", ["spike/riscv", "qemu/target/riscv"])
def test_simulator_cores_match_include(copy):
    for name in ("attn_abi.h", "attn_core.h"):
        assert (REPO / copy / name).read_bytes() == \
            (REPO / "include" / name).read_bytes(), \
            "%s/%s differs from include/; copy it over" % (copy, name)
