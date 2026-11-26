# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/corpus.md is the committed scan, row for row.

tools/corpus_scan.py writes tests/corpus/scan.json from a run over the
gitignored corpus; the page's table is generated from that file and this
test regenerates it, so a new run cannot leave the page behind.  It also
pins the two facts the page draws from the rows: the control is recognised,
and every corpus file that builds is unchanged by the recognizer.
"""

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import corpus_scan  # noqa: E402

SCAN = REPO / "tests" / "corpus" / "scan.json"
PAGE = REPO / "docs" / "corpus.md"
CONTROL = "demo/mha_plain.c"


def rows():
    return json.loads(SCAN.read_text(encoding="utf-8"))["rows"]


def test_the_page_shows_the_committed_table():
    text = PAGE.read_text(encoding="utf-8")
    assert corpus_scan.table(rows()) in text


def test_the_control_is_recognised():
    control = [r for r in rows() if r["file"] == CONTROL]
    assert len(control) == 1
    assert control[0]["status"] == "built"
    assert control[0]["attn"] == 1


def test_every_built_corpus_file_is_unchanged():
    for r in rows():
        if r["file"] == CONTROL or r["status"] != "built":
            continue
        assert r["attn"] == 0, r["file"]
        assert r["same"] is True, r["file"]
        assert r["insns_on"] == r["insns_off"], r["file"]


def test_every_file_that_did_not_build_says_why():
    for r in rows():
        if r["status"] != "built":
            assert r["why"], r["file"]


def test_the_page_names_the_two_environmental_limits():
    text = PAGE.read_text(encoding="utf-8")
    assert "language c++ not recognized" in text
    assert "etsoc/common/utils.h" in text