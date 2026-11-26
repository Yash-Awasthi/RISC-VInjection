# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/results.md: there is no silicon number, and no page invents one.

The plan allows a hardware measurement only when a board exists. This machine
has none, so the document says so, and these tests keep it saying so: the
no-silicon statement stays, no numeric speedup claim creeps in, and the index
lists the page. No toolchain is needed.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "docs" / "results.md"
INDEX = REPO / "docs" / "INDEX.md"

# A number followed by "x faster" / "speedup", or "speedup of 3.2": any of
# these would be a silicon claim this repository cannot support.
NUMERIC_CLAIM = (
    re.compile(r"\b\d+(?:\.\d+)?\s*[x\xd7]\s*(?:faster|speedup|quicker)", re.I),
    re.compile(r"(?:speedup|faster)\s+(?:of|by)\s+\d", re.I),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:times|percent|%)\s+(?:faster|speedup)", re.I),
)


def test_results_page_exists():
    assert RESULTS.is_file(), "docs/results.md is missing"


def test_no_silicon_statement_is_explicit():
    text = RESULTS.read_text(encoding="utf-8")
    assert re.search(r"no silicon", text, re.I), "no silicon statement missing"
    assert re.search(r"no (?:RISC-V )?board", text, re.I), "no board fact missing"


def test_no_numeric_speedup_claim():
    text = RESULTS.read_text(encoding="utf-8")
    for pattern in NUMERIC_CLAIM:
        match = pattern.search(text)
        assert match is None, f"numeric speedup claim: {match.group(0)!r}"


def test_no_board_date_is_recorded():
    text = RESULTS.read_text(encoding="utf-8")
    assert re.search(r"\d{4}-\d{2}-\d{2}", text), "the measurement date is missing"


def test_index_lists_results_page():
    text = INDEX.read_text(encoding="utf-8")
    assert "docs/results.md" in text, "docs/INDEX.md does not list docs/results.md"
    assert "tests/test_results.py" in text, "the index does not name this test file"
