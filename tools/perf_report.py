#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn build/perf/<sim>.csv into the tables in docs/results.md.

tests/perf/Makefile runs bench.c on QEMU and Spike; each line is
case,n,e,h,build,instret,cycles,maxdiff.  This module reads those lines,
prints the per-shape table (row 12), the guard table (row 9) and the
descriptor cost model with its error (row 13), and is what tests/test_perf.py
checks the committed copies against.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

Row = dict[str, object]
Key = tuple[str, str]


def load(path: Path) -> dict[Key, dict[str, float]]:
    """Read one simulator CSV; keys are (case, build)."""
    out: dict[Key, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            if rec.get("case") is None or rec["case"].startswith("perf:"):
                continue
            out[(rec["case"], rec["build"])] = {
                "n": float(rec["n"]),
                "e": float(rec["e"]),
                "h": float(rec["h"]),
                "instret": float(rec["instret"]),
                "cycles": float(rec["cycles"]),
            }
    return out


def cases(rows: dict[Key, dict[str, float]]) -> list[str]:
    seen: list[str] = []
    for case, _build in rows:
        if case not in seen:
            seen.append(case)
    return seen


def valid_cases(rows: dict[Key, dict[str, float]]) -> list[str]:
    return [c for c in cases(rows) if not c.startswith("g_")]


def guard_cases(rows: dict[Key, dict[str, float]]) -> list[str]:
    return [c for c in cases(rows) if c.startswith("g_")]


def per_shape_table(sims: dict[str, dict[Key, dict[str, float]]]) -> str:
    """One row per shape: retired instructions and cycles, loops vs attn."""
    first = next(iter(sims.values()))
    lines = [
        "| Shape `(n, e, h)` | Retired instructions, loops | "
        "Retired instructions, `attn` | Ratio | Cycles, loops | "
        "Cycles, `attn` |",
        "|---|---|---|---|---|---|",
    ]
    for case in valid_cases(first):
        a = first[(case, "attn")]
        b = first[(case, "loops")]
        shape = f"`({int(a['n'])}, {int(a['e'])}, {int(a['h'])})`"
        ratio = b["instret"] / a["instret"] if a["instret"] else 0.0
        lines.append(
            f"| {shape} | {int(b['instret'])} | {int(a['instret'])} | "
            f"{ratio:.1f} | {int(b['cycles'])} | {int(a['cycles'])} |"
        )
    return "\n".join(lines)


def guard_table(rows: dict[Key, dict[str, float]]) -> str:
    """Delta between the attn build and the loops build when the guard fails.

    Both builds run the same loops on these sizes; the delta is what the
    guard and its branch cost when the instruction cannot be used.
    """
    lines = [
        "| Case `(n, e, h)` | Why the guard fails | Instructions, attn build "
        "| Instructions, loops build | Delta |",
        "|---|---|---|---|---|",
    ]
    why = {"g_n0": "`n < 1`", "g_erem": "`e % h != 0`", "g_h0": "`h < 1`"}
    for case in guard_cases(rows):
        a = rows[(case, "attn")]
        b = rows[(case, "loops")]
        shape = f"`({int(a['n'])}, {int(a['e'])}, {int(a['h'])})`"
        delta = int(a["instret"]) - int(b["instret"])
        lines.append(
            f"| {shape} | {why.get(case, '?')} | {int(a['instret'])} | "
            f"{int(b['instret'])} | {delta:+d} |"
        )
    return "\n".join(lines)


def fit_attn(rows: dict[Key, dict[str, float]]) -> tuple[np.ndarray, list[tuple[str, int, float, float]]]:
    """Least squares for the attn-build instruction count from (n, e, heads).

    Basis: 1 (the guard, the descriptor and the calls around the region) and
    n*e (the buffers whose pointers the descriptor describes).  Returns the
    coefficients and per-case (case, measured, predicted, relative error).
    """
    names = valid_cases(rows)
    x = np.array(
        [[1.0, r["n"] * r["e"]]
         for r in (rows[(c, "attn")] for c in names)],
        dtype=float,
    )
    y = np.array([rows[(c, "attn")]["instret"] for c in names], dtype=float)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    table: list[tuple[str, int, float, float]] = []
    for i, case in enumerate(names):
        pred = float(x[i] @ coef)
        err = (pred - y[i]) / y[i]
        table.append((case, int(y[i]), pred, err))
    return coef, table


def cost_table(rows: dict[Key, dict[str, float]]) -> str:
    coef, table = fit_attn(rows)
    lines = [
        "Coefficients: `I = "
        f"{coef[0]:.1f} + {coef[1]:.4f}*n*e`",
        "",
        "| Shape `(n, e, h)` | Measured | Predicted | Error |",
        "|---|---|---|---|",
    ]
    for case, measured, pred, err in table:
        r = rows[(case, "attn")]
        shape = f"`({int(r['n'])}, {int(r['e'])}, {int(r['h'])})`"
        lines.append(f"| {shape} | {measured} | {pred:.0f} | {err:+.1%} |")
    worst = max(abs(err) for _c, _m, _p, err in table)
    lines += ["", f"Largest relative error: {worst:.1%}."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    base = Path(argv[1] if len(argv) > 1 else "build/perf")
    spike = load(base / "spike.csv")
    qemu = load(base / "qemu.csv")
    print("## Row 12: attn against the loops (Spike)\n")
    print(per_shape_table({"spike": spike}))
    print("\n## Row 9: guard cost when the instruction is absent (Spike)\n")
    print(guard_table(spike))
    print("\n## Row 13: cost model from the descriptor (Spike)\n")
    print(cost_table(spike))
    same = all(
        spike[k]["instret"] == qemu[k]["instret"] for k in spike if k in qemu
    )
    print(f"\nSpike and QEMU retired-instruction counts agree exactly: {same}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

