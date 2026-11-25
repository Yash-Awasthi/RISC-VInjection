#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze or verify tests/vectors/*.json.

--write regenerates every vector from tools/attn_model.Case, reloads the file,
runs the host core on the frozen bytes and stores the output SHA-256.
Without --write it checks the manifest, the header hash and every vector.
"""

import argparse
import datetime
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402
import vectors  # noqa: E402

VECTOR_SPECS = {
    "f32_baseline": dict(n=5, e=8, h=1),
    "f32_causal": dict(n=9, e=16, h=2, flags=am.F_CAUSAL),
    "f32_mask": dict(n=11, e=16, h=4, mask=True),
    "f32_causal_mask": dict(n=11, e=16, h=4, mask=True, flags=am.F_CAUSAL),
    "f32_gqa": dict(n=10, e=32, h=8, h_kv=4),
    "f32_mqa": dict(n=10, e=32, h=4, h_kv=1),
    "f32_scale": dict(n=6, e=8, h=2, scale=0.3),
    "f32_gqa_scale": dict(n=10, e=32, h=8, h_kv=4, scale=0.3),
    "bf16_bf16": dict(n=16, e=32, h=4, in_dt=am.DT_BF16, out_dt=am.DT_BF16),
    "bf16_f32": dict(n=16, e=32, h=4, in_dt=am.DT_BF16),
    "f32_bf16_out": dict(n=8, e=16, h=2, out_dt=am.DT_BF16),
    "f32_nobias": dict(n=7, e=12, h=3, bias=False),
    "bf16_bf16_causal": dict(n=16, e=32, h=4, in_dt=am.DT_BF16,
                             out_dt=am.DT_BF16, flags=am.F_CAUSAL),
    "f32_gpt2_head": dict(n=32, e=64, h=1, flags=am.F_CAUSAL),
}

PLACEHOLDER = "0" * 64


def seed(name):
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little")


def write_json(path, obj):
    path.write_bytes((json.dumps(obj, indent=2, sort_keys=True) + "\n")
                     .encode("utf-8"))


def document_for(name, case):
    cfg = dict(n=case.n, e=case.e, h=case.h, h_kv=case.h_kv,
               flags=case.flags, in_dtype=case.in_dt, out_dtype=case.out_dt,
               scale=case.scale)
    arrays = {k: vectors.array_entry(getattr(case, k), case.in_dt)
              for k in vectors.MAIN_ARRAYS}
    for k, b in zip(vectors.BIAS_ARRAYS, case.b):
        if b is not None:
            arrays[k] = vectors.array_entry(b, am.DT_F32)
    if case.mask is not None:
        arrays["mask"] = vectors.array_entry(case.mask, am.DT_F32)
    expected = {"dtype": "<u2" if case.out_dt == am.DT_BF16 else "<f4",
                "shape": [case.n, case.e], "sha256": PLACEHOLDER}
    return {"format": vectors.FORMAT, "name": name, "cfg": cfg,
            "arrays": arrays,
            "features": vectors.derive_features((cfg, arrays)),
            "expected": expected}


def freeze():
    lib = attn_host.build(tempfile.mkdtemp())
    vectors.VECTORS.mkdir(parents=True, exist_ok=True)
    names = []
    for name, kw in sorted(VECTOR_SPECS.items()):
        case = am.Case(np.random.default_rng(seed(name)), **kw)
        doc = document_for(name, case)
        path = vectors.VECTORS / (name + ".json")
        write_json(path, doc)
        v = vectors.load_vector(path)
        rc, mem = attn_host.run(lib, v.build_image())
        if rc != 0:
            print("FAIL %s: host rc=%d" % (name, rc))
            return 1
        doc["expected"]["sha256"] = vectors.canonical_sha256(
            v.read_y(mem), v.cfg["out_dtype"])
        write_json(path, doc)
        names.append(path.name)
        print("wrote %s" % path.name)
    write_json(vectors.VECTORS / "MANIFEST.json",
               {"format": vectors.FORMAT,
                "header_sha256": vectors.header_sha256(),
                "refreeze": prior_refreeze(),
                "vectors": sorted(names)})
    print("wrote MANIFEST.json (%d vectors)" % len(names))
    return 0


def prior_refreeze():
    """Existing refreeze records, so a regeneration never drops history."""
    try:
        records = vectors.read_manifest().get("refreeze", [])
    except (OSError, ValueError):
        return []
    return records if isinstance(records, list) else []


def refreeze(reason):
    if reason is None or not reason.strip():
        print("error: --refreeze needs a non-empty --reason TEXT",
              file=sys.stderr)
        return 2
    reason = reason.strip()
    manifest = vectors.read_manifest()
    old = manifest.get("header_sha256")
    new = vectors.header_sha256()
    lib = attn_host.build(tempfile.mkdtemp())
    for fname in sorted(manifest.get("vectors") or []):
        path = vectors.VECTORS / fname
        v = vectors.load_vector(path)
        rc, mem = attn_host.run(lib, v.build_image())
        if rc != 0:
            print("FAIL %s: host rc=%d" % (fname, rc), file=sys.stderr)
            return 1
        doc = v.document
        doc["expected"]["sha256"] = vectors.canonical_sha256(
            v.read_y(mem), v.cfg["out_dtype"])
        write_json(path, doc)
        print("refroze %s" % fname)
    manifest["header_sha256"] = new
    manifest.setdefault("refreeze", []).append(
        {"date": datetime.date.today().isoformat(), "old_sha256": old,
         "new_sha256": new, "reason": reason})
    write_json(vectors.VECTORS / "MANIFEST.json", manifest)
    n = len(manifest.get("vectors") or [])
    print("wrote MANIFEST.json (%d vectors)" % n)
    return 0


def verify():
    problems = []
    try:
        manifest = vectors.read_manifest()
    except OSError as exc:
        print("FAIL %s" % exc)
        return 1
    if manifest.get("format") != vectors.FORMAT:
        print("FAIL manifest format %r" % manifest.get("format"))
        problems.append("manifest")
    try:
        vectors.verify_header(manifest)
    except vectors.HeaderMismatch as exc:
        print("FAIL %s" % exc)
        problems.append("header")
    lib = attn_host.build(tempfile.mkdtemp())
    listed = set(manifest.get("vectors") or [])
    present = {p.name for p in vectors.VECTORS.glob("*.json")} - {"MANIFEST.json"}
    for extra in sorted(present - listed):
        print("FAIL %s: not in manifest" % extra)
        problems.append(extra)
    for fname in sorted(listed):
        v = vectors.load_vector(vectors.VECTORS / fname)
        rc, mem = attn_host.run(lib, v.build_image())
        got = vectors.canonical_sha256(v.read_y(mem), v.cfg["out_dtype"])
        if rc == 0 and got == v.expected["sha256"]:
            print("ok   %s" % fname)
        else:
            print("FAIL %s: rc=%d sha=%s" % (fname, rc, got))
            problems.append(fname)
    print("%d vectors, %d problem(s)" % (len(listed), len(problems)))
    return 0 if not problems else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="regenerate the vectors and the manifest")
    ap.add_argument("--refreeze", action="store_true",
                    help="re-record the header hash and vector outputs")
    ap.add_argument("--reason", default=None, metavar="TEXT",
                    help="why the vectors are being refrozen")
    args = ap.parse_args(argv)
    if args.refreeze:
        return refreeze(args.reason)
    return freeze() if args.write else verify()


if __name__ == "__main__":
    sys.exit(main())
