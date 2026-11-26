# SPDX-License-Identifier: GPL-3.0-or-later
"""The grammar in docs/recognizer.md and the compiled cases agree.

The section "The pattern as a grammar" binds every clause to one source
file and to the verdict that source must get.  This test reads the table,
compiles each case with the built cross compiler, and checks the verdict
and the text of a rejection.  It also refuses a clause with no case, a
case the table does not name, and a table that skips a clause number.
"""

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GCC = REPO / "out" / "toolchain" / "bin" / "riscv64-unknown-elf-gcc"
DOC = REPO / "docs" / "recognizer.md"

pytestmark = pytest.mark.skipif(
    not GCC.exists(), reason="needs a built toolchain (scripts/build.sh)"
)

TABLE_ROW = re.compile(r"^\| (G\d+) \| (.+?) \| `([^`]+)` \| (.+?) \|$")


def clauses():
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### The pattern as a grammar")
    end = text.index("\n## 2. How the proof works")
    section = text[start:end]
    rows = [m for m in map(TABLE_ROW.match, section.splitlines()) if m]
    assert rows, "the grammar table is missing"
    return section, [(m[1], m[3], m[4]) for m in rows]


def options(source):
    """The case's own dg-options, or the flags every other case uses."""
    m = re.search(r'dg-options "([^"]+)"', source.read_text(encoding="utf-8"))
    if not m:
        return ["-march=rv64gc_xattn", "-mabi=lp64d", "-O2"]
    return [o for o in m[1].split() if not o.startswith("-fdump")]


def compile_one(tmp_path, path):
    asm = tmp_path / (path.stem + ".s")
    r = subprocess.run(
        [str(GCC), *options(path), "-fopt-info-loop-missed",
         "-I", str(REPO / "include"), "-S", str(path), "-o", str(asm)],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert r.returncode == 0, (path, r.stderr[-1500:])
    text = asm.read_text(encoding="utf-8")
    return len(re.findall(r"^\s*attn\s", text, flags=re.M)), r.stderr


def test_every_clause_has_a_case_and_the_numerals_are_dense():
    section, rows = clauses()
    ids = [r[0] for r in rows]
    assert ids == [f"G{n}" for n in range(1, len(ids) + 1)], ids
    for _cid, rel, _verdict in rows:
        assert (REPO / rel).is_file(), rel
    assert "region     ::=" in section and "span       ::=" in section


@pytest.mark.parametrize(
    "row", clauses()[1], ids=[r[0] for r in clauses()[1]]
)
def test_the_compiler_agrees_with_the_clause(tmp_path, row):
    cid, rel, verdict = row
    want = 1 if verdict.startswith("one") else 0
    n, err = compile_one(tmp_path, REPO / rel)
    assert n == want, (cid, rel, n, err[-800:])
    if ": " in verdict:
        reason = verdict.split(": ", 1)[1]
        assert "attention loops not replaced: " + reason in err, (cid, err[-800:])
