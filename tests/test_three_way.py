# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike, QEMU and the host model agree bit for bit.

The reference bytes in `cases.h` are produced by `include/attn_core.h` compiled
on the host (`tests/baremetal/gen_cases.py`), and that file is also checked
there against the float64 model.  So a simulator that reports `maxdiff=0` for a
case agrees with the host model down to the last bit of every element.

This test runs the same bare-metal image on both simulators, prints the largest
absolute difference per case and requires it to be exactly zero.  It needs a
built toolchain and simulators, so it is off unless `XATTN_SIM=1`.
"""

import os
import pathlib
import re
import struct
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GCC = REPO / "out" / "toolchain" / "bin" / "riscv64-unknown-elf-gcc"
SPIKE = REPO / "out" / "spike" / "bin" / "spike"
QEMU = REPO / "build" / "qemu" / "qemu-system-riscv64"
OUT = REPO / "build" / "baremetal-gcc"
ELF_QEMU = OUT / "attn_test-qemu.elf"
ELF_SPIKE = OUT / "attn_test-spike.elf"

LINE = re.compile(r"^(PASS|FAIL) (\S+) maxdiff=([0-9a-f]{16})")

pytestmark = pytest.mark.skipif(
    os.environ.get("XATTN_SIM") != "1"
    or not all(p.exists() for p in (GCC, SPIKE, QEMU)),
    reason="needs XATTN_SIM=1 and a built toolchain, Spike and QEMU",
)


def build():
    subprocess.run(
        [
            "make", "-C", "tests/baremetal",
            f"CC={GCC}", "ARCH=rv64gc_xattn", f"OUT={OUT}",
            f"PYTHON={REPO / '.venv' / 'bin' / 'python'}",
            str(ELF_QEMU), str(ELF_SPIKE),
        ],
        cwd=REPO, check=True, capture_output=True, text=True,
    )


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return r.stdout


def cases(output):
    """name -> max absolute difference, as a float."""
    found = {}
    for line in output.splitlines():
        m = LINE.match(line.strip())
        if m:
            bits = int(m.group(3), 16) & 0xFFFFFFFF
            found[m.group(2)] = (m.group(1), struct.unpack("<f", struct.pack("<I", bits))[0])
    assert found, f"no result lines in:\n{output[-2000:]}"
    return found


def show(per_case):
    print(f"\n{'case':<26} {'QEMU':>12} {'Spike':>12}  verdict")
    for name in sorted(per_case):
        verdict, q = per_case[name]["qemu"]
        _, s = per_case[name]["spike"]
        print(f"{name:<26} {q:>12.9g} {s:>12.9g}  {verdict}")


def test_the_three_executions_agree_bit_for_bit():
    build()
    qemu_out = run([
        str(QEMU), "-M", "virt", "-bios", "none", "-nographic",
        "-monitor", "none", "-serial", "stdio", "-cpu", "rv64,xattn=on",
        "-kernel", str(ELF_QEMU),
    ])
    spike_out = run([str(SPIKE), "--isa=rv64gc_xattn", str(ELF_SPIKE)])

    q, s = cases(qemu_out), cases(spike_out)
    per_case = {name: {"qemu": q[name], "spike": s[name]} for name in q.keys() & s.keys()}
    missing = (q.keys() ^ s.keys())
    assert not missing, f"cases only one simulator reported: {sorted(missing)}"
    show(per_case)

    assert per_case, "no cases ran"
    for name, both in per_case.items():
        for who in ("qemu", "spike"):
            verdict, diff = both[who]
            assert verdict == "PASS", f"{name} failed on {who}"
            assert diff == 0.0, f"{name}: {who} differs from the host by {diff}"
