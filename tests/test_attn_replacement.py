# SPDX-License-Identifier: GPL-3.0-or-later
"""The demo's five loop nests become one `.ATTN`, and one `attn`.

`demo/mha_plain.c` is the plain C attention the README talks about.  With the
recognizer on (the default at `-O2`), the pass replaces the loops with one
`.ATTN` internal call and the backend expands it to one `attn`; with
`-fno-tree-loop-attn` the same file keeps its loops and floats.  Both counts
are printed so the claim is a measurement, not a sentence.
"""

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GCC = REPO / "out" / "toolchain" / "bin" / "riscv64-unknown-elf-gcc"

pytestmark = pytest.mark.skipif(
    not GCC.exists(), reason="needs a built toolchain (scripts/build.sh)"
)

# attncc.sh and artifacts.sh both complete the excerpt this way: standard
# headers, original line numbers.
COMPLETION = '#include <math.h>\n#include <stdlib.h>\n#line 1 "mha_plain.c"\n'


def build(tmp_path, extra):
    """Compile the demo; return (assembly, GIMPLE after the recognizer)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "excerpt.c"
    src.write_text(
        COMPLETION
        + (REPO / "demo" / "mha_plain.c").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out = tmp_path / ("with" if not extra else "without")
    out.mkdir()

    r = subprocess.run(
        [
            str(GCC), "-O2", *extra, "-S", "-fdump-tree-attn_recog",
            "-I", str(REPO / "include"), str(src), "-o", str(out / "x.s"),
        ],
        cwd=str(out), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    # With the pass disabled GCC never runs it, so it writes no dump: that is
    # the "before" case, and no `.ATTN` in it follows by construction.
    dumps = list(out.glob("*.attn_recog"))
    return (
        (out / "x.s").read_text(encoding="utf-8"),
        dumps[0].read_text(encoding="utf-8") if dumps else "",
    )


def counts(texts):
    asm, gimple = texts
    return {
        ".ATTN": len(re.findall(r"\.ATTN \(", gimple)),
        "attn": len(re.findall(r"^\s*attn\s", asm, flags=re.M)),
        "fadd.s+fmul.s": len(re.findall(r"^\s*f(?:add|mul)\.s", asm, flags=re.M)),
        "instructions": len(re.findall(r"^\t[a-z]", asm, flags=re.M)),
    }


def show(before, after):
    keys = ["instructions", "fadd.s+fmul.s", ".ATTN", "attn"]
    print(f"\n{'':<16} {'loops (-fno-tree-loop-attn)':>28} {'recognized (-O2)':>18}")
    for k in keys:
        print(f"{k:<16} {before[k]:>28} {after[k]:>18}")


def test_one_attn_replaces_the_loop_nests(tmp_path):
    before = counts(build(tmp_path / "a", ["-fno-tree-loop-attn"]))
    after = counts(build(tmp_path / "b", []))
    show(before, after)

    assert before[".ATTN"] == 0 and before["attn"] == 0, "the loops should stay"
    assert after[".ATTN"] == 1, "the pass should leave exactly one .ATTN"
    assert after["attn"] == 1, "exactly one attn instruction expected"

    # The recognized build keeps a copy of the loops: the runtime guard runs
    # it when the sizes are ones the instruction would reject (see
    # artifacts/README.md).  So the float arithmetic is expected to still be
    # there, in the fallback, and the straight-line code is expected to grow
    # by the descriptors and the guard.
    assert after["fadd.s+fmul.s"] == before["fadd.s+fmul.s"], (
        "the fallback should be the same loops, so the same float ops"
    )
    assert after["instructions"] > before["instructions"], (
        "descriptors and the guard cost instructions; the saving is at run "
        "time (artifacts/README.md: 991 vs 508421 executed)"
    )
