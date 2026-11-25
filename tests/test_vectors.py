# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen vectors in tests/vectors/ against the host core in include/."""

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
import vectors  # noqa: E402

MANIFEST = vectors.read_manifest()
VECTOR_FILES = MANIFEST["vectors"]


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


@pytest.fixture(scope="session")
def all_vectors():
    return [vectors.load_vector(vectors.VECTORS / f) for f in VECTOR_FILES]


@pytest.mark.parametrize("fname", VECTOR_FILES)
def test_vector_matches_frozen_hash(lib, fname):
    v = vectors.load_vector(vectors.VECTORS / fname)
    assert v.name + ".json" == fname
    assert set(v.document) == {"format", "name", "cfg", "arrays", "expected"}
    assert v.document["format"] == vectors.FORMAT

    # Arrays come from the file bytes, not from re-running a seed generator.
    for key, entry in v.arrays.items():
        a = v.data[key]
        assert list(a.shape) == entry["shape"], key
        assert a.dtype == np.float32, key
        assert vectors.array_entry(a, entry["dtype"])["data"] == entry["data"]

    cfg = v.cfg
    assert set(cfg) == {"n", "e", "h", "h_kv", "flags", "in_dtype",
                        "out_dtype", "scale"}
    img = v.build_image()
    raw = bytes(img.image.buf)
    got = struct.unpack_from(am.CFG_FMT, raw, img.c_addr - img.image.base)
    assert got[:7] == (cfg["n"], cfg["e"], cfg["h"], cfg["h_kv"],
                       cfg["flags"], cfg["in_dtype"], cfg["out_dtype"])
    want_scale = am.scale_bits(cfg["scale"]) if cfg["scale"] is not None else 0
    assert got[7] == want_scale and got[8] == 0
    assert (got[9] != 0) == ("mask" in v.arrays)

    rc, mem = attn_host.run(lib, img)
    assert rc == 0
    y = v.read_y(mem)
    assert y.shape == (cfg["n"], cfg["e"])
    assert v.expected["dtype"] == ("<u2" if cfg["out_dtype"] == am.DT_BF16
                                   else "<f4")
    assert v.expected["shape"] == [cfg["n"], cfg["e"]]
    assert vectors.canonical_sha256(y, cfg["out_dtype"]) == \
        v.expected["sha256"]


def test_feature_coverage(all_vectors):
    seen = set()
    for v in all_vectors:
        seen.update(vectors.derive_features(v))
    assert {"causal", "mask", "gqa", "scale"} <= seen


def test_dtype_combos(all_vectors):
    combos = {(v.cfg["in_dtype"], v.cfg["out_dtype"]) for v in all_vectors}
    assert {(0, 0), (1, 1), (1, 0), (0, 1)} <= combos


def test_manifest():
    assert MANIFEST["format"] == 1
    assert MANIFEST["header_sha256"] == vectors.header_sha256()
    assert VECTOR_FILES == sorted(VECTOR_FILES)
    assert len(set(VECTOR_FILES)) == len(VECTOR_FILES)
    for fname in VECTOR_FILES:
        assert (vectors.VECTORS / fname).is_file()


def test_verify_header_matches():
    assert vectors.verify_header() == MANIFEST["header_sha256"]
    assert MANIFEST["header_sha256"] == vectors.header_sha256()


def test_header_mismatch_names_refreeze(tmp_path):
    copy = tmp_path / "attn_core.h"
    copy.write_bytes((REPO / "include" / "attn_core.h").read_bytes()
                     + b"\n/* drift */\n")
    with pytest.raises(vectors.HeaderMismatch,
                       match="freeze_vectors.py --refreeze"):
        vectors.verify_header(header_path=copy)


def test_refreeze_requires_reason():
    for tail in (["--refreeze"], ["--refreeze", "--reason", "   "]):
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "freeze_vectors.py"),
             *tail], capture_output=True, text=True)
        assert result.returncode != 0, tail
        assert result.stderr.strip() != "", tail
