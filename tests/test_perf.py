# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-shape numbers in docs/results.md, checked against the raw CSV.

tests/perf/expected/ holds the two CSVs that `make -C tests/perf check`
produced on Spike and QEMU; this test reads them, never a simulator. It
re-derives every figure the page publishes: the two simulators agree, the
attn build retires fewer instructions on every valid shape, the guard costs
a bounded number of instructions, and the least-squares model prints the
coefficients and the 2.5% bound the page states.
"""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import perf_report  # noqa: E402

EXPECTED = REPO / "tests" / "perf" / "expected"
RESULTS = REPO / "docs" / "results.md"


@pytest.fixture(scope="module")
def spike():
    return perf_report.load(EXPECTED / "spike.csv")


@pytest.fixture(scope="module")
def qemu():
    return perf_report.load(EXPECTED / "qemu.csv")


def test_both_simulators_agree_exactly(spike, qemu):
    assert set(spike) == set(qemu)
    for key, row in spike.items():
        assert row["instret"] == qemu[key]["instret"], key
        assert row["cycles"] == qemu[key]["cycles"], key


def test_attn_beats_the_loops_on_every_valid_shape(spike):
    for case in perf_report.valid_cases(spike):
        attn = spike[(case, "attn")]["instret"]
        loops = spike[(case, "loops")]["instret"]
        assert attn < loops / 10, case


def test_guard_costs_a_bounded_number_of_instructions(spike):
    for case in perf_report.guard_cases(spike):
        delta = spike[(case, "attn")]["instret"] - spike[(case, "loops")]["instret"]
        assert -10 <= delta <= 100, (case, delta)


def test_model_coefficients_are_published(spike):
    coef, _table = perf_report.fit_attn(spike)
    text = RESULTS.read_text(encoding="utf-8")
    line = f"I(n, e, h) = {coef[0]:.1f} + {coef[1]:.4f} * n * e"
    assert line in text, line


def test_model_error_is_within_the_published_bound(spike):
    _coef, table = perf_report.fit_attn(spike)
    worst = max(abs(err) for _case, _m, _p, err in table)
    assert worst <= 0.026, worst


def test_results_page_publishes_every_measured_row(spike):
    text = RESULTS.read_text(encoding="utf-8")
    for case in perf_report.valid_cases(spike):
        row = spike[(case, "attn")]
        shape = f"`({int(row['n'])}, {int(row['e'])}, {int(row['h'])})`"
        assert shape in text, shape
        assert str(int(spike[(case, "loops")]["instret"])) in text, case
    assert re.search(r"not a speedup", text), "the page must not call the ratio a speedup"

