#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Randomised differential test of the attn core against tools/attn_model.py.

Generates random cases (shape, dtypes, head counts, mask type, scale), runs each
one on the host core built by tools/attn_host.py, and counts failures per
category so a regression names the family it broke.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import attn_host  # noqa: E402
import attn_model as am  # noqa: E402

GROUPS = ("shape", "dtype", "mask", "scale")
MAX_REPORTED = 10


def dtype_name(dt):
    return "bf16" if dt == am.DT_BF16 else "f32"


def make_case(rng):
    """One random case; derives n, e, h, h_kv, flags, dtypes, bias, mask, scale."""
    h = int(rng.integers(1, 9))
    d = int(rng.integers(1, min(32, 64 // h) + 1))
    n = int(rng.integers(1, 33))
    e = h * d
    kvs = sorted({c for c in (h, h // 2, h // 4, 1) if c >= 1 and h % c == 0})
    h_kv = int(kvs[int(rng.integers(len(kvs)))])
    in_dt = am.DT_F32 if rng.random() < 0.5 else am.DT_BF16
    out_dt = am.DT_F32 if rng.random() < 0.5 else am.DT_BF16
    bias = bool(rng.random() < 0.5)
    causal = bool(rng.random() < 0.5)
    additive = bool(rng.random() < 0.5)
    flags = am.F_CAUSAL if causal else 0
    scale = None if rng.random() < 0.5 else float(rng.uniform(0.05, 0.5))
    return am.Case(rng, n=n, e=e, h=h, h_kv=h_kv, flags=flags, in_dt=in_dt,
                   out_dt=out_dt, bias=bias, mask=additive, scale=scale)


def make_cases(count, seed=20261126):
    rng = np.random.default_rng(seed)
    return [make_case(rng) for _ in range(count)]


def mask_kind(case):
    causal = bool(case.flags & am.F_CAUSAL)
    additive = case.mask is not None
    if causal and additive:
        return "causal+additive"
    if causal:
        return "causal"
    if additive:
        return "additive"
    return "none"


def case_categories(case):
    return {
        "shape": "%d,%d,%d,%d" % (case.n, case.e, case.h, case.h_kv or case.h),
        "dtype": "%s->%s" % (dtype_name(case.in_dt), dtype_name(case.out_dt)),
        "mask": mask_kind(case),
        "scale": "explicit" if case.scale is not None else "default",
    }


def compare(lib, case, shift=0.0):
    """Run one case; returns (ok, rc, max_abs_diff, categories)."""
    rc, mem = attn_host.run(lib, case)
    got = case.read_y(mem).astype(np.float64) + shift
    want = am.round_dtype(case.expected(), case.out_dt)
    diff = np.abs(got - want)
    worst = float(diff.max()) if diff.size else 0.0
    ok = rc == 0 and bool(np.all(diff <= case.tolerance()))
    return ok, rc, worst, case_categories(case)


def summarise(cases, lib, shift=0.0):
    counts = {g: {} for g in GROUPS}
    failures = {g: {} for g in GROUPS}
    mismatches = []
    total = 0
    total_fail = 0
    for i, case in enumerate(cases):
        ok, rc, worst, cats = compare(lib, case, shift=shift)
        total += 1
        for g, key in cats.items():
            counts[g][key] = counts[g].get(key, 0) + 1
            if not ok:
                failures[g][key] = failures[g].get(key, 0) + 1
        if not ok:
            total_fail += 1
            if len(mismatches) < MAX_REPORTED:
                mismatches.append({
                    "index": i, "n": case.n, "e": case.e, "h": case.h,
                    "h_kv": case.h_kv, "flags": case.flags,
                    "in_dt": dtype_name(case.in_dt),
                    "out_dt": dtype_name(case.out_dt),
                    "mask": cats["mask"], "scale": case.scale,
                    "rc": rc, "max_abs_diff": worst,
                })
    categories = {}
    for g in GROUPS:
        categories[g] = {
            key: {"cases": counts[g][key],
                  "failures": failures[g].get(key, 0)}
            for key in sorted(counts[g])
        }
    return {"total": total, "failures": total_fail,
            "categories": categories, "mismatches": mismatches}


def print_summary(summary):
    print("%-8s %-28s %6s %9s" % ("category", "bucket", "cases", "failures"))
    for g in GROUPS:
        for key, b in summary["categories"][g].items():
            print("%-8s %-28s %6d %9d"
                  % (g, key, b["cases"], b["failures"]))
    print("%-8s %-28s %6d %9d"
          % ("total", "", summary["total"], summary["failures"]))
    for m in summary["mismatches"]:
        print("mismatch #%d n=%d e=%d h=%d h_kv=%d flags=%d %s->%s mask=%s "
              "scale=%s rc=%d max_abs_diff=%.6g"
              % (m["index"], m["n"], m["e"], m["h"], m["h_kv"], m["flags"],
                 m["in_dt"], m["out_dt"], m["mask"], m["scale"], m["rc"],
                 m["max_abs_diff"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261126)
    ap.add_argument("--json", type=Path, default=None,
                    help="dump the summary as JSON")
    args = ap.parse_args(argv)

    lib = attn_host.build(tempfile.mkdtemp(prefix="random_diff_"))
    summary = summarise(make_cases(args.cases, args.seed), lib)
    print_summary(summary)
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
