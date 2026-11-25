# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/artifacts.html is the committed output of scripts/artifacts_html.py.

The test regenerates the page and compares bytes, so a vector change or a
README edit that is not published fails here.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "artifacts_html.py"
PAGE = REPO / "docs" / "artifacts.html"
MANIFEST = REPO / "tests" / "vectors" / "MANIFEST.json"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("artifacts-html") / "artifacts.html"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return out.read_bytes()


def test_committed_page_matches_generator(generated):
    assert generated == PAGE.read_bytes()


def test_page_is_self_contained(generated):
    page = generated.decode("ascii")
    assert page.startswith("<!doctype html>")
    for forbidden in ("<script", "http://", "https://", "src="):
        assert forbidden not in page


def test_every_vector_is_listed(generated):
    page = generated.decode("ascii")
    for fname in json.loads(MANIFEST.read_text(encoding="utf-8"))["vectors"]:
        name = json.loads((MANIFEST.parent / fname).read_text())["name"]
        assert "<code>%s</code>" % name in page


def test_page_is_ascii(generated):
    generated.decode("ascii")


def test_doctored_copy_fails_byte_comparison(generated):
    committed = PAGE.read_bytes()
    doctored = committed.replace(b"<td><code>f32_baseline</code></td>",
                                 b"<td><code>f32_baselinX</code></td>", 1)
    assert doctored != committed
    assert doctored != generated
