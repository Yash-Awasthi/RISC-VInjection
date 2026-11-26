# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/sanitize.sh: ASan and UBSan builds over the frozen vectors."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_model as am  # noqa: E402
import vectors  # noqa: E402

SCRIPT = REPO / "scripts" / "sanitize.sh"
CLANG = shutil.which("clang")
SANITIZERS = ("asan", "ubsan")
TIMEOUT = 1800
# The frozen sha256 for this vector was recorded on a C library whose expf
# rounds differently from glibc's: Ubuntu gcc 13.3 and clang 18.1 both match
# each other and not the frozen b00e0586 hash (Windows ucrt does match it).
# Every other vector must still match the frozen value exactly.
KNOWN_LIBC = {"f32_gqa_scale"}


def reference(v):
    """float64 model of the same inputs, for the maxdiff columns."""
    d = v.data
    cfg = v.cfg
    return am.reference(
        d["x"], d["wq"], d["wk"], d["wv"], d["wo"],
        d.get("bq"), d.get("bk"), d.get("bv"), d.get("bo"),
        h=cfg["h"], h_kv=cfg["h_kv"],
        causal=bool(cfg["flags"] & am.F_CAUSAL),
        mask=d.get("mask"), scale=cfg["scale"])


def read_y(path, v):
    raw = path.read_bytes()
    n, e = v.cfg["n"], v.cfg["e"]
    if v.cfg["out_dtype"] == am.DT_BF16:
        y = am.from_bf16_bits(np.frombuffer(raw, "<u2"))
    else:
        y = np.frombuffer(raw, "<f4")
    assert y.size == n * e, (path, y.size, n * e)
    return y.reshape(n, e).astype(np.float64)


def test_sanitizers_hold_on_every_vector(tmp_path):
    if CLANG is None:
        pytest.skip("clang is not on PATH")
    names = vectors.read_manifest()["vectors"]
    stems = {Path(name).stem for name in names}
    out = tmp_path / "y"
    env = dict(os.environ, CLANG=CLANG, PYTHON=sys.executable,
               SANITIZE_OUT_DIR=str(out))
    cp = subprocess.run(["bash", str(SCRIPT)], capture_output=True,
                        text=True, errors="replace", env=env,
                        timeout=TIMEOUT)
    print(cp.stdout)
    if cp.stderr:
        print(cp.stderr, file=sys.stderr)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "0 mismatch" in cp.stdout
    assert "0 sanitizer reports" in cp.stdout

    rows = {}
    for line in cp.stdout.splitlines():
        m = re.match(r"^(asan|ubsan)\s+(\S+)\s+(\S+)$", line)
        if m and m.group(2) in stems:
            rows[(m.group(1), m.group(2))] = m.group(3)
    assert len(rows) == len(SANITIZERS) * len(names), rows
    assert {s for s, v in rows.items() if v == "LIBC"} <= \
        {(san, stem) for san in SANITIZERS for stem in KNOWN_LIBC}
    for (san, stem), verdict in rows.items():
        assert verdict in ("OK", "LIBC"), (san, stem, verdict)

    version = subprocess.run([CLANG, "--version"], capture_output=True,
                             text=True, errors="replace")
    first = version.stdout.splitlines()[0] if version.stdout else "unknown"
    print("clang:", first)
    print("vectors:", len(names))

    for name in names:
        stem = Path(name).stem
        v = vectors.load_vector(vectors.VECTORS / name)
        ref = reference(v)
        for san in SANITIZERS:
            y = read_y(out / ("%s-%s.y" % (san, stem)), v)
            diff = float(np.max(np.abs(y - ref)))
            assert np.isfinite(diff), (san, stem, diff)
            print("maxdiff %-5s %-28s %-4s %.3e"
                  % (san, name, rows[(san, stem)], diff))
