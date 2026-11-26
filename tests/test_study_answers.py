#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the measured claims written in docs/study.md.

Every number asserted here was measured from this repository, so the
study guide cannot drift away from the code it describes.
"""

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import attn_model as am


def test_stage1_weight_change_moves_every_output():
    case = am.Case(np.random.default_rng(20261126), n=5, e=8, h=1)
    base = am.round_dtype(case.expected(), case.out_dt)
    assert base.size == 40
    case.wq[0, 0] += np.float32(1.0)
    pert = am.round_dtype(case.expected(), case.out_dt)
    assert np.count_nonzero(base != pert) == 40
    assert base.dtype == np.float32
    assert pert.dtype == np.float32


def test_stage2_separate_add_loses_fused_keeps():
    f = np.float32
    a = f(-(1 + 2**-12))
    b = f(1 + 2**-12)
    c = f(1 + 2**-11)
    prod = f(a * b)
    assert prod == f(-1.00048828125)
    sep = f(prod + c)
    assert sep == f(0.0)
    assert sep.tobytes() == b"\x00\x00\x00\x00"
    fused = f(am.fma(float(a), float(b), float(c)))
    assert fused == f(-2.0**-24)
    assert fused.tobytes()[::-1].hex() == "b3800000"
    assert am.fma(float(a), float(b), float(c)) == -2.0**-24


def test_stage2_trap_pair_does_not_separate():
    f = np.float32
    a0 = f(1 + 2**-12)
    b0 = f(1 - 2**-12)
    c0 = f(-1.0)
    assert f(f(a0 * b0) + c0) == f(-2.0**-24)


def test_stage2_bf16_tie_rounds_to_even():
    bits = am.bf16_bits(np.array([np.float32(1 + 2**-8)]))
    assert int(bits[0]) == 0x3F80


def test_stage3_encoding_and_slot_disjointness():
    assert am.encode(13, 10, 11, 12) == 0x66B516FB
    assert am.ATTN_MATCH == 0x0600107B
    assert am.ATTN_MASK == 0x0600707F
    assert am.decode(0x66B516FB) == dict(rd=13, rs1=10, rs2=11, rs3=12)
    k = 0x0600707F
    a, b, c, t = 0x0400307B, 0x0600307B, 0x0600507B, 0x0600107B
    diffs = [(a ^ b) & k, (a ^ c) & k, (b ^ c) & k,
             (a ^ t) & k, (b ^ t) & k, (c ^ t) & k]
    assert diffs == [0x02000000, 0x02006000, 0x00006000,
                     0x02002000, 0x00002000, 0x00004000]
    assert all(d != 0 for d in diffs)


def test_stage4_patch_line_counts():
    text = (REPO / "patches" / "binutils" /
            "0001-RISC-V-add-the-Xattn-vendor-extension.patch").read_text()
    counts = {}
    current = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[1]
            counts[current] = 0
        elif line.startswith("+") and not line.startswith("+++"):
            assert current is not None
            counts[current] += 1
    assert counts == {
        "bfd/elfxx-riscv.c": 5,
        "gas/testsuite/gas/riscv/x-attn-32.d": 13,
        "gas/testsuite/gas/riscv/x-attn-fail.d": 3,
        "gas/testsuite/gas/riscv/x-attn-fail.l": 4,
        "gas/testsuite/gas/riscv/x-attn.d": 13,
        "gas/testsuite/gas/riscv/x-attn.s": 4,
        "include/opcode/riscv-opc.h": 4,
        "include/opcode/riscv.h": 1,
        "opcodes/riscv-opc.c": 3,
    }
    assert sum(counts.values()) == 50
    non_test = sum(v for k, v in counts.items() if "/testsuite/" not in k)
    assert non_test == 13


def test_stage5_recognizer_text():
    doc = (REPO / "docs" / "recognizer.md").read_text()
    assert "Then every statement in all five nests must be accounted for" in doc
    assert "It may not contain other loops" in doc


def test_stage6_fault_text():
    spec = (REPO / "docs" / "spec.md").read_text()
    t = (REPO / "tests" / "baremetal" / "attn_test.c").read_text()
    assert "Every load happens before the first store" in spec
    assert "re-execution overwrites all" in spec
    assert "load_fault_precise" in t
    assert "reexecute_after_fault" in t


def test_stage7_score_matrix_sizes():
    assert 4096**2 * 4 == 67108864
    assert 128 * 128 * 4 == 65536
    assert 67108864 // 65536 == 1024
    abi = (REPO / "include" / "attn_abi.h").read_text()
    assert "#define ATTN_MAX_N 4096u" in abi


def test_study_guide_answers_present():
    doc = (REPO / "docs" / "study.md").read_text()
    assert doc.count("**Answer.**") == 7
    assert "Answers are checked by tests/test_study_answers.py." in doc
