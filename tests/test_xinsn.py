"""scripts/xinsn.py: the general method, tested.

The method is the second half of the product ("any instruction into four
projects"), so it gets the same treatment as attn_core.h: a fixed input, a
recorded output, and a command that fails when either moves.

These tests read the pinned upstream trees in binutils/, gcc/, spike/ and
qemu/, so they need `git submodule update --init` and
`scripts/patches.sh apply` (no toolchain build).
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


# ---------------------------------------------------- apply, remove, round trip

# The parts of the four trees xinsn.py edits.  A scratch copy of these is
# the same input the real trees give it, without the gigabytes the rest of
# gcc and qemu would cost.
SCRATCH_DIRS = ["gcc/gcc/config/riscv", "spike/riscv", "qemu/target/riscv"]
SCRATCH_FILES = [
    "binutils/include/opcode/riscv-opc.h",
    "binutils/include/opcode/riscv.h",
    "binutils/bfd/elfxx-riscv.c",
    "binutils/opcodes/riscv-opc.c",
    "gcc/gcc/doc/riscv-ext.texi",   # written by gen-riscv-ext-texi
    ".gitignore",
]


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=test",
                           "-c", "user.email=test@example.invalid",
                           "-C", str(root), *args],
                          capture_output=True, text=True)


@pytest.fixture
def scratch(tmp_path_factory):
    """A commit-clean copy of the touched parts of the four trees."""
    root = tmp_path_factory.mktemp("scratch")
    for d in SCRATCH_DIRS:
        shutil.copytree(REPO / d, root / d)
    for f in SCRATCH_FILES:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / f, root / f)
    shutil.copytree(REPO / "scripts", root / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert git(root, "init", "-q").returncode == 0
    assert git(root, "add", "-A").returncode == 0
    assert git(root, "commit", "-qm", "scratch trees").returncode == 0
    return root


def scratch_xinsn(root, *args):
    return subprocess.run(
        [sys.executable, str(root / "scripts/xinsn.py"), *args],
        capture_output=True, text=True, cwd=root)


def test_apply_changes_the_trees_and_repeats_nothing(scratch, tmp_path):
    spec = write_spec(tmp_path, "mac", MAC_SPEC)
    first = scratch_xinsn(scratch, "apply", str(spec))
    assert first.returncode == 0, first.stderr
    changed = [l.split(" ", 1)[1] for l in first.stdout.splitlines()
               if l.startswith("changed ")]
    assert changed == FILES
    for created in ("binutils/gas/testsuite/gas/riscv/x-mac.s",
                    "gcc/gcc/config/riscv/riscv-ext-xmac.def",
                    "spike/riscv/xmac.cc",
                    "qemu/target/riscv/tcg/mac_helper.c"):
        assert (scratch / created).is_file(), created
    dirty = git(scratch, "status", "--porcelain").stdout

    again = scratch_xinsn(scratch, "apply", str(spec))
    assert again.returncode == 0, again.stderr
    assert "already applied" in again.stdout
    assert "changed " not in again.stdout
    assert git(scratch, "status", "--porcelain").stdout == dirty


def test_remove_restores_a_clean_tree(scratch, tmp_path):
    spec = write_spec(tmp_path, "mac", MAC_SPEC)
    applied = scratch_xinsn(scratch, "apply", str(spec))
    assert applied.returncode == 0, applied.stderr
    removed = scratch_xinsn(scratch, "remove", "mac", "--no-rebuild")
    assert removed.returncode == 0, removed.stderr
    assert "mac removed from the trees" in removed.stdout
    status = git(scratch, "status", "--porcelain").stdout
    assert status == "", "remove left the trees dirty:\n" + status


# ------------------------------------------------------------ encoding safety

sys.path.insert(0, str(REPO / "scripts"))
import find_opcodes as fo  # noqa: E402

ENCODING = re.compile(r"MATCH=0x([0-9a-f]{8}) MASK=0x([0-9a-f]{8})")


def encoding_of(text):
    m = ENCODING.search(text)
    assert m, "no encoding in:\n" + text
    return int(m.group(1), 16), int(m.group(2), 16)


def test_every_example_slot_is_free(tmp_path):
    """Each example spec lands in the custom opcode space and overlaps no
    encoding already in the trees (3006 at the pinned commits)."""
    defs = fo.load_defs(fo.default_sources(REPO))
    assert len(defs) > 1000, "no upstream encodings found"
    for spec in sorted((REPO / "examples/insns").glob("*.spec")):
        r = xinsn("show", str(spec))
        assert r.returncode == 0, r.stderr
        match, mask = encoding_of(r.stdout)
        assert match & 0x7F in fo.MAJORS.values(), spec.name
        hits = [n for n, e in defs.items() if fo.collides((match, mask), e)]
        assert hits == [], "%s collides with %s" % (spec.name, hits)


EXAMPLE_ORDER = ["vsum", "fill", "avgu", "mac", "bitrev"]


def test_two_instructions_never_share_a_slot(scratch):
    """An instruction already in the trees moves the next `slot = auto`
    choice, so five instructions applied one after another have five
    different encodings."""
    taken = []
    for name in EXAMPLE_ORDER:
        spec = REPO / "examples/insns" / (name + ".spec")
        shown = scratch_xinsn(scratch, "show", str(spec))
        assert shown.returncode == 0, shown.stderr
        enc = encoding_of(shown.stdout)
        for other_name, other in taken:
            assert not fo.collides(enc, other), \
                "%s and %s share an encoding" % (name, other_name)
        applied = scratch_xinsn(scratch, "apply", str(spec))
        assert applied.returncode == 0, applied.stderr
        taken.append((name, enc))
    listed = scratch_xinsn(scratch, "list")
    assert listed.returncode == 0
    for name in EXAMPLE_ORDER:
        assert re.search(r"^%s +MATCH=0x" % name, listed.stdout, re.M), name


# ------------------------------------------------------------- failure paths

BAD_SPECS = {
    "no name": ("inputs = 2\nsemantics:\n  return rs1;\n",
                "missing 'name = ...'"),
    "bad name": ("name = MAC\ninputs = 2\nsemantics:\n  return rs1;\n",
                 "must match [a-z][a-z0-9]{1,15}"),
    "no semantics": ("name = mac\ninputs = 2\n", "missing 'semantics:' block"),
    "unknown key": ("name = mac\nwritse = rd\nsemantics:\n  return rs1;\n",
                    "unknown key 'writse'"),
    "no test, writes none": ("name = fill\ninputs = 2\nwrites = none\n"
                             "memory = yes\nsemantics:\n  return 0;\n",
                             "needs a 'test:' block"),
    "no test, memory": ("name = vsum\ninputs = 2\nmemory = yes\n"
                        "semantics:\n  return LD32 (rs1);\n",
                        "needs a 'test:' block"),
    "inputs 4": ("name = mac\ninputs = 4\nsemantics:\n  return rs1;\n",
                 "inputs must be 0..3"),
    "writes typo": ("name = mac\ninputs = 2\nwrites = result\n"
                    "semantics:\n  return rs1;\n",
                    "writes must be 'rd' or 'none'"),
}


@pytest.mark.parametrize("text,want", BAD_SPECS.values(), ids=BAD_SPECS.keys())
def test_a_bad_spec_is_refused(tmp_path, text, want):
    """Each malformed spec exits non-zero, names the spec file and says
    what is wrong — before anything is written to the trees."""
    spec = tmp_path / "bad.spec"
    spec.write_text(text)
    r = xinsn("show", str(spec))
    assert r.returncode == 1, r.stdout
    assert want in r.stderr, r.stderr
    assert str(spec) in r.stderr


# ------------------------------------------------- the same on both simulators

TOOLCHAIN = REPO / "out/toolchain/bin/riscv64-unknown-elf-gcc"
SPIKE = REPO / "out/spike/bin/spike"
QEMU = REPO / "build/qemu/qemu-system-riscv64"


@pytest.mark.skipif(
    os.environ.get("XATTN_XINSN_SIM") != "1"
    or not all(p.exists() for p in (TOOLCHAIN, SPIKE, QEMU)),
    reason="slow: needs a built toolchain and XATTN_XINSN_SIM=1 "
           "(make check-xinsn-sim)")
def test_generated_instruction_runs_on_both_simulators():
    """Apply `mac` to the real trees, rebuild, and run the generated test
    program on QEMU and on Spike: the CHECK lines pass on both, and
    objdump finds the instruction in the program."""
    r = xinsn("all", str(REPO / "examples/insns" / "mac.spec"))
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert "qemu  mac: all checks passed" in r.stdout, r.stdout
    assert "spike mac: all checks passed" in r.stdout, r.stdout
    assert re.search(r"objdump: [1-9]\d* mac instruction\(s\)", r.stdout), \
        r.stdout
