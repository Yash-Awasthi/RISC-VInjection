#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen attn vectors: rebuild the guest image, run it, hash the output.

A vector file holds the exact input bytes as base64 plus the SHA-256 of the
output the host core produced when the vector was frozen, so a test can detect
any drift in attn_core.h without recomputing an oracle from a seed.

Format 2 stores the active feature tags in "features". Format 1 is legacy: it
has no "features" key and the tags are derived from cfg and the array keys at
load time, so an old vector stays readable.
"""

import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))
import attn_model as am  # noqa: E402

FORMAT = 2
FEATURE_TAGS = ("causal", "gqa", "mask", "scale")
VECTORS = REPO / "tests" / "vectors"
MAIN_ARRAYS = ("x", "wq", "wk", "wv", "wo")
BIAS_ARRAYS = ("bq", "bk", "bv", "bo")


def header_sha256(path=None):
    p = Path(path) if path is not None else REPO / "include" / "attn_core.h"
    return hashlib.sha256(p.read_bytes()).hexdigest()


class HeaderMismatch(Exception):
    """include/attn_core.h no longer matches the hash recorded in the manifest."""


def verify_header(manifest=None, header_path=None):
    """Return the current header hash; raise if the manifest records another."""
    if manifest is None:
        manifest = read_manifest()
    recorded = manifest.get("header_sha256")
    current = header_sha256(header_path)
    if recorded != current:
        raise HeaderMismatch(
            "header_sha256 mismatch: manifest %s, current %s; re-record with "
            'tools/freeze_vectors.py --refreeze --reason "<text>"'
            % (recorded, current))
    return current


def read_manifest(repo_root=REPO):
    p = Path(repo_root) / "tests" / "vectors" / "MANIFEST.json"
    return json.loads(p.read_text(encoding="utf-8"))


def array_entry(a, dt):
    """Encode a float32 array the way am.Case lays it out in the image."""
    fmt = dt if isinstance(dt, str) else ("<u2" if dt == am.DT_BF16 else "<f4")
    a = np.asarray(a, np.float32)
    if fmt == "<u2":
        raw = am.bf16_bits(a).tobytes()
    else:
        raw = np.ascontiguousarray(a, "<f4").tobytes()
    return {"dtype": fmt, "shape": list(a.shape),
            "data": base64.b64encode(raw).decode("ascii")}


def decode_array(entry):
    raw = base64.b64decode(entry["data"])
    shape = tuple(entry["shape"])
    if entry["dtype"] == "<u2":
        return am.from_bf16_bits(np.frombuffer(raw, "<u2")).reshape(shape)
    return np.frombuffer(raw, "<f4").reshape(shape).copy()


def canonical_bytes(y, out_dt):
    y = np.asarray(y, np.float32)
    if out_dt == am.DT_BF16:
        return np.ascontiguousarray(am.bf16_bits(y), "<u2").tobytes()
    return np.ascontiguousarray(y, "<f4").tobytes()


def canonical_sha256(y, out_dt):
    return hashlib.sha256(canonical_bytes(y, out_dt)).hexdigest()


def derive_features(v):
    """Tags present in a vector: accepts a Vector or a (cfg, arrays) pair."""
    if hasattr(v, "cfg"):
        cfg, arrays = v.cfg, v.arrays
    else:
        cfg, arrays = v
    out = []
    if cfg["flags"] & am.F_CAUSAL:
        out.append("causal")
    if "mask" in arrays:
        out.append("mask")
    if cfg["h_kv"] not in (0, cfg["h"]):
        out.append("gqa")
    if (cfg["flags"] & am.F_SCALE) and cfg["scale"] is not None:
        out.append("scale")
    return sorted(out)


class FrozenImage:
    """What attn_host.run needs: a case-shaped image plus Y bookkeeping."""

    def __init__(self, image, x_addr, w_addr, c_addr, y_addr, n, e, out_dt):
        self.image, self.x_addr = image, x_addr
        self.w_addr, self.c_addr, self.y_addr = w_addr, c_addr, y_addr
        self.n, self.e, self.out_dt = n, e, out_dt

    def read_y(self, mem):
        off = self.y_addr - self.image.base
        cnt = self.n * self.e
        if self.out_dt == am.DT_BF16:
            raw = np.frombuffer(bytes(mem[off:off + 2 * cnt]), np.uint16)
            y = am.from_bf16_bits(raw)
        else:
            y = np.frombuffer(bytes(mem[off:off + 4 * cnt]), np.float32)
        return y.reshape(self.n, self.e)


class Vector:
    def __init__(self, path):
        self.path = Path(path)
        self.document = json.loads(self.path.read_text(encoding="utf-8"))
        doc = self.document
        fmt = doc.get("format")
        if fmt not in (1, 2):
            raise ValueError("unsupported vector format %s in %s"
                             % (fmt, self.path.name))
        self.format = fmt
        self.name, self.cfg = doc["name"], doc["cfg"]
        self.arrays, self.expected = doc["arrays"], doc["expected"]
        self.data = {k: decode_array(e) for k, e in self.arrays.items()}
        self.raw = {k: base64.b64decode(e["data"]) for k, e in self.arrays.items()}
        if fmt == 1:
            self.features = derive_features((self.cfg, self.arrays))
        else:
            self.features = self._read_features(doc)
        self._image = None

    def _read_features(self, doc):
        feats = doc.get("features")
        if not isinstance(feats, list) or \
                not all(isinstance(f, str) for f in feats):
            raise ValueError("%s: features must be a list of strings"
                             % self.path.name)
        bad = [f for f in feats if f not in FEATURE_TAGS]
        if bad:
            raise ValueError("%s: unknown feature tag(s) %s; allowed %s"
                             % (self.path.name, bad, list(FEATURE_TAGS)))
        want = derive_features((self.cfg, self.arrays))
        if sorted(feats) != want:
            raise ValueError("%s: features %s do not match derived %s"
                             % (self.path.name, sorted(feats), want))
        return list(feats)

    def build_image(self, base=0x1000):
        cfg = self.cfg
        n, e, h, h_kv = cfg["n"], cfg["e"], cfg["h"], cfg["h_kv"]
        in_dt, out_dt = cfg["in_dtype"], cfg["out_dtype"]
        im = am.Image(base)
        x_addr = im.put(self.raw["x"])
        wp = [im.put(self.raw[k]) for k in MAIN_ARRAYS[1:]]
        bp = [im.put(self.raw[k]) if k in self.raw else 0 for k in BIAS_ARRAYS]
        mp = im.put(self.raw["mask"]) if "mask" in self.raw else 0
        w_addr = im.put(struct.pack(am.WEIGHTS_FMT, *wp, *bp))
        scale = cfg["scale"]
        c_addr = im.put(struct.pack(
            am.CFG_FMT, n, e, h, h_kv, cfg["flags"], in_dt, out_dt,
            am.scale_bits(scale) if scale is not None else 0, 0, mp))
        y_addr = im.reserve(n * e * (2 if out_dt == am.DT_BF16 else 4))
        self._image = FrozenImage(im, x_addr, w_addr, c_addr, y_addr, n, e,
                                  out_dt)
        return self._image

    def read_y(self, mem):
        if self._image is None:
            raise RuntimeError("build_image() first for %s" % self.name)
        return self._image.read_y(mem)


def load_vector(path):
    return Vector(path)
