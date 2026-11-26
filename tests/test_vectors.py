# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen vectors in tests/vectors/ against the host core in include/."""

import json
import platform
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

# A frozen hash may differ on exactly one libc, by the amount measured here.
# The entry is keyed by libc: it only applies when platform.libc_ver() is the
# glibc it names, so ucrt, musl or a newer glibc fail instead of skipping.
LIBM_ALLOWED = {
    "f32_gqa_scale.json": {
        "libc": "glibc",
        "libc_version": "2.39",
        "frozen_hash":
            "b00e05866cc8f2cda79a364a649796c02788474a237d3632b288c21e26464ef1",
        "host_hash":
            "e3e9a25ad8b1b2504c9ddc6e08d6a81fac5c068dcb3862af232c8b82960e01f6",
        # element index -> direction of the measured difference
        "elements": {144: "larger", 159: "smaller"},
        "delta": 5.96e-08,
        "why": "glibc 2.39 libm expf rounds differently from the ucrt "
               "host where the vector was frozen: 2 of 320 Y elements "
               "differ, max |dY| 5.96e-08, element 144 larger and element "
               "159 smaller; six glibc 2.39 builds and the frozen host were "
               "measured independently.",
    },
}


def libc_key():
    """(libc, version) on Linux; (sys.platform, '') everywhere else."""
    if sys.platform.startswith("linux"):
        name, version = platform.libc_ver()
        return name, version
    return sys.platform, ""


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


@pytest.fixture(scope="session")
def all_vectors():
    return [vectors.load_vector(vectors.VECTORS / f) for f in VECTOR_FILES]


@pytest.mark.parametrize("fname", VECTOR_FILES)
def test_vector_matches_frozen_hash(lib, fname, capsys):
    v = vectors.load_vector(vectors.VECTORS / fname)
    assert v.name + ".json" == fname
    assert set(v.document) == {"format", "name", "cfg", "arrays", "expected",
                               "features"}
    assert v.format == vectors.FORMAT == 2
    assert v.features == vectors.derive_features(v)

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
    got = vectors.canonical_sha256(y, cfg["out_dtype"])
    frozen = v.expected["sha256"]
    if got == frozen:
        return

    entry = LIBM_ALLOWED.get(fname)
    assert entry is not None, (
        "%s: %s does not match frozen %s and has no allowlist entry"
        % (fname, got, frozen))
    assert frozen == entry["frozen_hash"], (
        "%s: allowlist records frozen hash %s, the vector file says %s"
        % (fname, entry["frozen_hash"], frozen))
    name, version = libc_key()
    assert (name, version) == (entry["libc"], entry["libc_version"]), (
        "%s: differs on %s %s, but the allowlist covers %s %s only, so this "
        "is real drift" % (fname, name, version or "(no version)",
                           entry["libc"], entry["libc_version"]))
    assert got == entry["host_hash"], (
        "%s: %s differs from frozen %s on the allowed libc but is not the "
        "measured %s, so this is real drift"
        % (fname, got, frozen, entry["host_hash"]))

    diffs = ", ".join("%d %s" % (i, d)
                      for i, d in sorted(entry["elements"].items()))
    row = ("%s: libc %s %s vs ucrt freeze host; got %s; frozen %s; "
           "%d/%d Y elements differ (%s); max |dY| %.2e"
           % (fname, name, version, got, frozen, len(entry["elements"]),
              y.size, diffs, entry["delta"]))
    with capsys.disabled():
        print(row)
    pytest.skip(row + "; " + entry["why"])


def test_feature_coverage(all_vectors):
    seen = set()
    for v in all_vectors:
        seen.update(v.features)
    assert {"causal", "mask", "gqa", "scale"} <= seen


def test_v2_features_are_derived(all_vectors):
    for v in all_vectors:
        assert v.features == vectors.derive_features(v), v.name
        for tag in v.features:
            assert tag in vectors.FEATURE_TAGS, (v.name, tag)
        assert set(v.features) <= set(vectors.FEATURE_TAGS), v.name


def test_v1_fixture_loads(lib):
    path = vectors.VECTORS / "v1" / "f32_causal.json"
    a = vectors.load_vector(path)
    assert a.document["format"] == 1
    assert a.features == ["causal"] == vectors.derive_features(a)
    rc, mem = attn_host.run(lib, a.build_image())
    assert rc == 0
    out_dt = a.cfg["out_dtype"]
    assert vectors.canonical_sha256(a.read_y(mem), out_dt) == \
        a.expected["sha256"]
    b = vectors.load_vector(vectors.VECTORS / "f32_causal.json")
    assert a.expected["sha256"] == b.expected["sha256"]


def test_unknown_format_rejected(tmp_path):
    doc = json.loads((vectors.VECTORS / "f32_causal.json")
                     .read_text(encoding="utf-8"))
    doc["format"] = 99
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="99"):
        vectors.load_vector(path)


def test_dtype_combos(all_vectors):
    combos = {(v.cfg["in_dtype"], v.cfg["out_dtype"]) for v in all_vectors}
    assert {(0, 0), (1, 1), (1, 0), (0, 1)} <= combos


def test_manifest():
    assert MANIFEST["format"] == vectors.FORMAT
    assert MANIFEST["format"] == 2
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
