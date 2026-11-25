# SPDX-License-Identifier: GPL-3.0-or-later
"""The randomised differential harness in scripts/random_diff.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import random_diff as rd  # noqa: E402
import attn_host  # noqa: E402


@pytest.fixture(scope="session")
def lib(tmp_path_factory):
    return attn_host.build(tmp_path_factory.mktemp("host"))


def test_25_cases_pass_and_cover_every_bucket(lib):
    summary = rd.summarise(rd.make_cases(25, seed=7), lib)
    assert summary["failures"] == 0
    for group in rd.GROUPS:
        buckets = summary["categories"][group]
        assert sum(b["cases"] for b in buckets.values()) == 25
        assert sum(b["failures"] for b in buckets.values()) == 0


def test_shifted_host_output_is_reported(lib):
    cases = rd.make_cases(5, seed=7)
    summary = rd.summarise(cases, lib, shift=1.0)
    assert summary["failures"] == 5
    cats = rd.case_categories(cases[0])
    for group, bucket in cats.items():
        assert summary["categories"][group][bucket]["failures"] >= 1


def test_cli_json_summary(tmp_path):
    out = tmp_path / "summary.json"
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/random_diff.py"),
         "--cases", "5", "--seed", "7", "--json", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(out.read_text())
    assert summary["total"] == 5
    assert summary["failures"] == 0
    assert set(summary["categories"]) == set(rd.GROUPS)
    for group in rd.GROUPS:
        assert sum(b["cases"] for b in summary["categories"][group].values()) == 5
