"""scripts/xinsn.py: the general method, tested.

The method is the second half of the product ("any instruction into four
projects"), so it gets the same treatment as attn_core.h: a fixed input, a
recorded output, and a command that fails when either moves.

These tests read the pinned upstream trees in binutils/, gcc/, spike/ and
qemu/, so they need `git submodule update --init` and
`scripts/patches.sh apply` (no toolchain build).
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
XINSN = REPO / "scripts" / "xinsn.py"

MAC_SPEC = """\
# Multiply-accumulate: rd = rs1 * rs2 + rs3 (low XLEN bits).
name   = mac
inputs = 3
writes = rd
memory = no
slot   = auto
semantics:
  return rs1 * rs2 + rs3;
"""


def xinsn(*args):
    return subprocess.run([sys.executable, str(XINSN), *args],
                          capture_output=True, text=True, cwd=REPO)


def write_spec(tmp_path, name, text):
    p = tmp_path / (name + ".spec")
    p.write_text(text)
    return p


def test_show_names_the_encoding(tmp_path):
    """The chosen encoding is reported, it is the documented one, and it
    sits in the custom opcode space with the R4 mask."""
    r = xinsn("show", str(write_spec(tmp_path, "mac", MAC_SPEC)))
    assert r.returncode == 0, r.stderr
    first = r.stdout.splitlines()[0]
    assert first == ("mac: format R4, custom-3 funct3=3 funct2=2, "
                     "MATCH=0x0400307b MASK=0x0600707f, -march=..._xmac"), first
    assert int("0x0400307b", 16) & 0x7F == 0x7B          # major opcode 0x7b
    assert int("0x0600707f", 16) == 0x0600707F           # R4 fixed fields


def test_show_lists_the_files_it_would_change(tmp_path):
    """The files the instruction touches, one per line: a change to the
    generator that silently drops a tree must show up here."""
    r = xinsn("show", str(write_spec(tmp_path, "mac", MAC_SPEC)))
    assert r.returncode == 0, r.stderr
    changed = [line.split(" ", 2)[2] for line in r.stdout.splitlines()
               if line.startswith("would change ")]
    assert changed == FILES


FILES = [
    "binutils/include/opcode/riscv-opc.h",
    "binutils/include/opcode/riscv.h",
    "binutils/bfd/elfxx-riscv.c",
    "binutils/opcodes/riscv-opc.c",
    "binutils/gas/testsuite/gas/riscv/x-mac.s",
    "binutils/gas/testsuite/gas/riscv/x-mac.d",
    "gcc/gcc/config/riscv/riscv-ext-xmac.def",
    "gcc/gcc/config/riscv/riscv-ext.def",
    "gcc/gcc/config/riscv/t-riscv",
    "gcc/gcc/config/riscv/mac.md",
    "gcc/gcc/config/riscv/riscv.md",
    "gcc/gcc/config/riscv/riscv-builtins.cc",
    "gcc/gcc/config/riscv/riscv-ftypes.def",
    "gcc/gcc/config/riscv/mac.def",
    "spike/riscv/mac_core.h",
    "spike/riscv/xmac.cc",
    "spike/riscv/extensions.cc",
    "spike/riscv/riscv.mk.in",
    "qemu/target/riscv/xmac.decode",
    "qemu/target/riscv/tcg/insn_trans/trans_xmac.c.inc",
    "qemu/target/riscv/mac_core.h",
    "qemu/target/riscv/tcg/mac_helper.c",
    "qemu/target/riscv/cpu_cfg_fields.h.inc",
    "qemu/target/riscv/cpu_cfg.h",
    "qemu/target/riscv/cpu.c",
    "qemu/target/riscv/meson.build",
    "qemu/target/riscv/tcg/meson.build",
    "qemu/target/riscv/tcg/translate.c",
    "qemu/target/riscv/helper.h",
]


def test_show_is_a_dry_run(tmp_path):
    """show writes nothing: the trees are unchanged afterwards, and the
    second run says the same thing as the first."""
    spec = write_spec(tmp_path, "mac", MAC_SPEC)
    before = {p: (REPO / p).read_bytes() for p in FILES[:4]}
    a = xinsn("show", str(spec))
    b = xinsn("show", str(spec))
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout
    assert {p: (REPO / p).read_bytes() for p in FILES[:4]} == before
