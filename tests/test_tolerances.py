# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared tolerances in tools/tolerances.py, checked against the vectors.

Every bound below is measured on the 14 frozen vectors, never assumed: the
magnitudes bound the bf16 half-ulp argument, and the error of the host core
against the float64 model must sit well inside the stated tolerance.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402
import tolerances  # noqa: E402
import vectors  # noqa: E402

# The derivation in docs/theory.md covers |Y| < 8; half an ulp is at most
# 2**-6 in that binade and 2**-7 below 4.
Y_MAX = 8.0
RAW_LITERALS = ("atol=1e-", "rtol=1e-", "2.0 ** -7")
ALLOWED = {REPO / "tools" / "tolerances.py", Path(__file__).resolve()}


def model_expected(v):
    """The float64 model's Y for a frozen vector, rounded to out_dtype."""
    cfg, a = v.cfg, v.data
    y = am.reference(a["x"], a["wq"], a["wk"], a["wv"], a["wo"],
                     a.get("bq"), a.get("bk"), a.get("bv"), a.get("bo"),
                     h=cfg["h"], h_kv=cfg["h_kv"],
                     causal=bool(cfg["flags"] & am.F_CAUSAL),
                     mask=a.get("mask"), scale=cfg["scale"])
    return am.round_dtype(y, cfg["out_dtype"])


def test_constants():
    assert tolerances.ATOL_F32 == 1e-4
    assert tolerances.ATOL_BF16 == 2.0 ** -7
    assert tolerances.U32 == 2.0 ** -24


def test_for_dtype():
    assert tolerances.for_dtype(am.DT_F32) == tolerances.ATOL_F32
    assert tolerances.for_dtype(am.DT_BF16) == tolerances.ATOL_BF16


@pytest.mark.parametrize("out_dt,want", [(am.DT_F32, tolerances.ATOL_F32),
                                         (am.DT_BF16, tolerances.ATOL_BF16)])
def test_case_tolerance_uses_the_shared_constant(out_dt, want):
    case = am.Case(np.random.default_rng(0), n=2, e=4, h=1, out_dt=out_dt)
    assert case.tolerance() == want


@pytest.fixture(scope="session")
def frozen():
    return [(f, vectors.load_vector(vectors.VECTORS / f))
            for f in vectors.read_manifest()["vectors"]]


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


def test_frozen_magnitudes_stay_in_the_derived_binade(frozen):
    for f, v in frozen:
        mag = float(np.max(np.abs(model_expected(v))))
        assert mag < Y_MAX, "%s: max |Y| = %r" % (f, mag)


def test_frozen_errors_are_inside_the_shared_bounds(lib, frozen):
    worst = {am.DT_F32: 0.0, am.DT_BF16: 0.0}
    for f, v in frozen:
        rc, mem = attn_host.run(lib, v.build_image())
        assert rc == 0, f
        err = float(np.max(np.abs(v.read_y(mem) - model_expected(v))))
        dt = v.cfg["out_dtype"]
        worst[dt] = max(worst[dt], err)
    assert worst[am.DT_F32] < tolerances.ATOL_F32 / 10
    assert worst[am.DT_BF16] < tolerances.ATOL_BF16


def test_no_repeated_tolerance_literals():
    hits = []
    files = sorted((REPO / "tests").glob("*.py")) + \
        sorted((REPO / "tools").glob("*.py"))
    for f in files:
        if f.resolve() in ALLOWED:
            continue
        for num, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1):
            for lit in RAW_LITERALS:
                if lit in line:
                    hits.append("%s:%d: %s" % (f.name, num, line.strip()))
    assert not hits, "tolerance literals belong in tools/tolerances.py:\n" \
        + "\n".join(hits)
