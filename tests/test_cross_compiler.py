# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen vectors under GCC and Clang at -O0, -O2 and -O3.

Every build gets -ffp-contract=off so the compiler and its optimisation level
are the only variables. All builds must agree with each other byte for byte on
every vector; that is the cross-compiler claim. Each build's Y is also hashed
with the rule tests/test_vectors.py uses and its mismatch set must equal
FROZEN_MISMATCHES. That set is non-empty on glibc: one frozen Y was recorded on
a host whose libm expf rounds differently, and tests/test_vectors.py fails the
same vector there. Any other mismatch, or any vector that starts matching, is a
failure, so the constant cannot hide a regression and must be emptied once a
vector starts reproducing.
"""

import ctypes
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import vectors  # noqa: E402

SOURCE = REPO / "tests" / "host" / "attn_host.c"
OPTS = ("-O0", "-O2", "-O3")
MANIFEST = vectors.read_manifest()
VECTOR_FILES = MANIFEST["vectors"]
ROWS = []
VERSIONS = []

# Measured on ubuntu:24.04, glibc 2.39: the six builds are byte-identical and
# 2 of 320 Y elements differ from the frozen Y.  Empty this once the vector
# reproduces everywhere; the test fails if the measured set changes either way.
FROZEN_MISMATCHES = {
    "f32_gqa_scale.json": (
        "2 of 320 Y elements differ from the frozen Y; max |dY| = 5.96e-08 "
        "with the build larger at element 144 and smaller at element 159; "
        "glibc 2.39 libm expf vs the freeze host; "
        "tests/test_vectors.py fails the same vector"),
}


class _Table:
    """Print the compiler versions and one row per build under pytest -q."""

    def pytest_terminal_summary(self, terminalreporter):
        if not ROWS:
            return
        tr = terminalreporter
        tr.write_line("")
        tr.write_line("cross-compiler builds: " + ", ".join(VERSIONS))
        tr.write_line("%-6s %5s %7s %6s"
                      % ("build", "opt", "frozen", "cross"))
        for tag, opt, frozen, cross in ROWS:
            tr.write_line("%-6s %5s %7d %6d" % (tag, opt, frozen, cross))
        if FROZEN_MISMATCHES:
            tr.write_line("frozen misses are pre-existing and independent of "
                          "the compiler matrix:")
            for name, why in sorted(FROZEN_MISMATCHES.items()):
                tr.write_line("  %s: %s" % (name, why))


@pytest.fixture(scope="session", autouse=True)
def cross_table(request):
    request.config.pluginmanager.register(_Table(), "cross-table")


def _version(exe):
    out = subprocess.run([exe, "--version"], capture_output=True,
                         text=True, check=True)
    return out.stdout.splitlines()[0].strip()


def _compilers():
    cc = shutil.which("cc")
    clang = shutil.which("clang")
    if cc is None or clang is None:
        pytest.skip("cc and clang are both required for the matrix")
    found = [("cc", cc)]
    gcc = shutil.which("gcc")
    if gcc is not None and Path(gcc).resolve() != Path(cc).resolve():
        found.append(("gcc", gcc))
    found.append(("clang", clang))
    return found


def _load(exe, opt, so):
    subprocess.run([exe, "-std=c11", opt, "-ffp-contract=off", "-fPIC",
                    "-shared", "-I", str(REPO / "include"), str(SOURCE),
                    "-o", str(so), "-lm"], check=True)
    lib = ctypes.CDLL(str(so))
    lib.attn_host_run.argtypes = [ctypes.POINTER(ctypes.c_char),
                                  ctypes.c_uint64] + [ctypes.c_uint64] * 4 \
        + [ctypes.c_uint]
    return lib


def _run(lib, case, xlen=64):
    base = case.image.base
    mem = ctypes.create_string_buffer(base + len(case.image.buf))
    mem[base:base + len(case.image.buf)] = bytes(case.image.buf)
    rc = lib.attn_host_run(mem, len(mem), case.y_addr, case.x_addr,
                           case.w_addr, case.c_addr, xlen)
    return rc, mem.raw[base:]


@pytest.fixture(scope="session")
def matrix(tmp_path_factory):
    cases = {f: vectors.load_vector(vectors.VECTORS / f)
             for f in VECTOR_FILES}
    images = {f: v.build_image() for f, v in cases.items()}
    tmp = tmp_path_factory.mktemp("cross")
    builds = []
    for tag, exe in _compilers():
        VERSIONS.append("%s %s" % (tag, _version(exe)))
        for opt in OPTS:
            so = tmp / ("attn_%s_%s.so" % (tag, opt[1:]))
            lib = _load(exe, opt, so)
            outs = {}
            for fname, v in cases.items():
                rc, mem = _run(lib, images[fname])
                assert rc == 0, (tag, opt, fname, rc)
                y = v.read_y(mem)
                outs[fname] = vectors.canonical_bytes(y,
                                                      v.cfg["out_dtype"])
            builds.append({"tag": tag, "opt": opt, "out": outs})

    ref = builds[0]["out"]
    for b in builds:
        b["frozen_bad"] = [
            f for f in VECTOR_FILES
            if hashlib.sha256(b["out"][f]).hexdigest()
            != cases[f].expected["sha256"]]
        b["cross_bad"] = [f for f in VECTOR_FILES if b["out"][f] != ref[f]]
        ROWS.append((b["tag"], b["opt"], len(b["frozen_bad"]),
                     len(b["cross_bad"])))
    return builds


def test_builds_agree_bit_for_bit(matrix):
    for b in matrix:
        assert not b["cross_bad"], (b["tag"], b["opt"], b["cross_bad"])


def test_frozen_mismatches_are_the_known_pre_existing_set(matrix):
    known = set(FROZEN_MISMATCHES)
    why = " | ".join("%s: %s" % kv for kv in sorted(FROZEN_MISMATCHES.items()))
    for b in matrix:
        got = set(b["frozen_bad"])
        assert got == known, (
            "%s %s: frozen mismatches %s, expected %s (%s)"
            % (b["tag"], b["opt"], sorted(got), sorted(known), why))
