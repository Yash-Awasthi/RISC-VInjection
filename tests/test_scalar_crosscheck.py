# SPDX-License-Identifier: GPL-3.0-or-later
"""tests/host/attn_scalar.c, an independent scalar attn, against the host core.

Three implementations meet here: include/attn_core.h compiled for the host
(tools/attn_host.py), the scalar C reference in tests/host/attn_scalar.c
(double accumulation, its own exp/sqrt, attn_abi.h only) and the float64 model
in tools/attn_model.py.  The Spike and QEMU binaries are not built on this
machine, so the simulator rows of tests/test_three_way.py stay unrun; that file
covers them under XATTN_SIM=1.

Each configuration prints its measured max |Y - Yref| in the terminal summary
and must stay inside the tolerance tools/tolerances.py gives for out_dtype.
"""

import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402
import tolerances  # noqa: E402

SCALAR = REPO / "tests" / "host" / "attn_scalar.c"
HDR = struct.Struct("<12I")
YHDR = struct.Struct("<4I")
MAGIC = 0x58544153
MAGIC_Y = 0x58415459
HDR_BYTES = HDR.size
ROWS = []


class _Table:
    """Print the measured differences even under pytest -q."""

    def pytest_terminal_summary(self, terminalreporter):
        if not ROWS:
            return
        tr = terminalreporter
        tr.write_line("")
        tr.write_line("scalar C vs attn_core.h host build, max |diff|")
        tr.write_line("%-24s %12s %13s %11s %10s"
                      % ("case", "scalar-host", "scalar-model",
                         "host-model", "tolerance"))
        for name, sh, sm, hm, tol in ROWS:
            tr.write_line("%-24s %12.3g %13.3g %11.3g %10.2g"
                          % (name, sh, sm, hm, tol))


@pytest.fixture(scope="session", autouse=True)
def scalar_table(request):
    request.config.pluginmanager.register(_Table(), "scalar-table")


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


@pytest.fixture(scope="session")
def scalar(tmp_path_factory):
    name = "attn_scalar.exe" if sys.platform == "win32" else "attn_scalar"
    exe = tmp_path_factory.mktemp("scalar") / name
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Werror",
                    "-I", str(REPO / "include"), str(SCALAR),
                    "-o", str(exe)], check=True)
    return exe


def write_input(path, case):
    """Lay a Case out in the scalar's binary format (same arrays as the image)."""
    bias = [b for b in case.b if b is not None]
    bias_mask = sum(1 << i for i, b in enumerate(case.b) if b is not None)
    head = HDR.pack(MAGIC, case.n, case.e, case.h, case.h_kv, case.flags,
                    case.in_dt, case.out_dt,
                    am.scale_bits(case.scale) if case.scale is not None else 0,
                    bias_mask, 0 if case.mask is None else 1, 0)
    arrays = [case.x, case.wq, case.wk, case.wv, case.wo] + bias
    if case.mask is not None:
        arrays.append(case.mask)
    with path.open("wb") as f:
        f.write(head)
        for a in arrays:
            f.write(np.ascontiguousarray(a, np.float32).tobytes())


def read_y(path, n, e, out_dt):
    raw = path.read_bytes()
    magic, m, me, dt = YHDR.unpack_from(raw)
    assert (magic, m, me, dt) == (MAGIC_Y, n, e, out_dt)
    if out_dt == am.DT_BF16:
        y = am.from_bf16_bits(
            np.frombuffer(raw[16:16 + 2 * n * e], np.uint16))
    else:
        y = np.frombuffer(raw[16:16 + 4 * n * e], np.float32)
    return y.reshape(n, e)


def read_input(path):
    """Parse a scalar input file back into named float32 arrays."""
    raw = path.read_bytes()
    (magic, n, e, h, h_kv, flags, in_dt, out_dt, sb, bias,
     has_mask, _) = HDR.unpack_from(raw)
    assert magic == MAGIC
    kv = (h_kv or h) * (e // h)
    off = HDR_BYTES

    def take(count):
        nonlocal off
        a = np.frombuffer(raw, np.float32, count, off).copy()
        off += 4 * count
        return a

    out = {"x": take(n * e).reshape(n, e),
           "wq": take(e * e).reshape(e, e),
           "wk": take(e * kv).reshape(e, kv),
           "wv": take(e * kv).reshape(e, kv),
           "wo": take(e * e).reshape(e, e),
           "n": n, "e": e, "h": h, "h_kv": h_kv, "flags": flags,
           "in_dt": in_dt, "out_dt": out_dt,
           "scale_bits": sb, "mask": None}
    for bit, key, count in ((1, "bq", e), (2, "bk", kv),
                            (4, "bv", kv), (8, "bo", e)):
        if bias & bit:
            out[key] = take(count)
    if has_mask:
        out["mask"] = take(n * n).reshape(n, n)
    return out


CASES = {
    "f32_bias": dict(n=5, e=8, h=1),
    "f32_4head": dict(n=8, e=16, h=4),
    "bf16_in": dict(n=6, e=12, h=3, in_dt=am.DT_BF16),
    "bf16_out": dict(n=6, e=12, h=3, out_dt=am.DT_BF16),
    "causal": dict(n=7, e=16, h=2, flags=am.F_CAUSAL),
    "mask": dict(n=6, e=8, h=2, mask=True),
    "gqa": dict(n=6, e=16, h=4, h_kv=2),
    "mqa": dict(n=6, e=8, h=4, h_kv=1),
    "explicit_scale": dict(n=5, e=8, h=2, scale=0.37),
    "nobias_causal_mask": dict(n=5, e=8, h=2, bias=False, mask=True,
                               flags=am.F_CAUSAL),
}


@pytest.mark.parametrize("name", CASES)
def test_scalar_agrees_with_the_host_core(scalar, lib, tmp_path, name):
    case = am.Case(np.random.default_rng(len(name)), **CASES[name])
    inp = tmp_path / "in.bin"
    out = tmp_path / "y.bin"
    write_input(inp, case)
    r = subprocess.run([str(scalar), "run", str(inp), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    y_scalar = read_y(out, case.n, case.e, case.out_dt)
    rc, mem = attn_host.run(lib, case)
    assert rc == 0
    y_host = case.read_y(mem)
    exp = am.round_dtype(case.expected(), case.out_dt)
    tol = tolerances.for_dtype(case.out_dt)
    d_sh = float(np.max(np.abs(y_scalar - y_host)))
    d_sm = float(np.max(np.abs(y_scalar - exp)))
    d_hm = float(np.max(np.abs(y_host - exp)))
    ROWS.append((name, d_sh, d_sm, d_hm, tol))
    assert d_sh <= tol, "%s: scalar vs host %.3g > %.3g" % (name, d_sh, tol)
    assert d_sm <= tol, "%s: scalar vs model %.3g > %.3g" % (name, d_sm, tol)
    assert d_hm <= tol, "%s: host vs model %.3g > %.3g" % (name, d_hm, tol)


def test_generated_problem_matches_the_float64_model(scalar, tmp_path):
    """The --seed generator is independent data, checked against the model."""
    inp = tmp_path / "gen.bin"
    out = tmp_path / "gen.y"
    scale = 0.5
    r = subprocess.run([str(scalar), "gen", str(inp),
                        "--n", "6", "--e", "12", "--h", "3", "--hkv", "1",
                        "--flags", str(am.F_CAUSAL | am.F_SCALE),
                        "--scale", str(am.scale_bits(scale)),
                        "--seed", "1234"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    a = read_input(inp)
    r = subprocess.run([str(scalar), "run", str(inp), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    y = read_y(out, a["n"], a["e"], a["out_dt"])
    exp = am.reference(a["x"], a["wq"], a["wk"], a["wv"], a["wo"],
                       a.get("bq"), a.get("bk"), a.get("bv"), a.get("bo"),
                       h=a["h"], h_kv=a["h_kv"],
                       causal=bool(a["flags"] & am.F_CAUSAL),
                       scale=struct.unpack("<f",
                                           struct.pack("<I",
                                                       a["scale_bits"]))[0])
    diff = float(np.max(np.abs(y - exp)))
    assert diff <= tolerances.ATOL_F32, "gen: %.3g" % diff


RESERVED = [dict(e=9, h=2), dict(e=8, h=2, h_kv=3), dict(n=0),
            dict(e=8, h=0), dict(in_dt=2), dict(flags=4)]


@pytest.mark.parametrize("over", RESERVED)
def test_reserved_configuration_exits_1(scalar, tmp_path, over):
    cfg = dict(n=4, e=8, h=2, h_kv=0, flags=0, in_dt=am.DT_F32,
               out_dt=am.DT_F32, bias=15, mask=0)
    cfg.update(over)
    inp = tmp_path / "bad.bin"
    inp.write_bytes(HDR.pack(MAGIC, cfg["n"], cfg["e"], cfg["h"],
                             cfg["h_kv"], cfg["flags"], cfg["in_dt"],
                             cfg["out_dt"], 0, cfg["bias"], cfg["mask"], 0))
    out = tmp_path / "bad.y"
    r = subprocess.run([str(scalar), "run", str(inp), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stderr
    assert not out.exists()
