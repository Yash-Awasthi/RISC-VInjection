#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plug a new custom RISC-V instruction into binutils, GCC, Spike and QEMU.

  xinsn.py new   [SPEC]    ask for the instruction (name, operands, C code,
                           test), write SPEC, then do "all"
  xinsn.py show  SPEC      encoding and, for each file it would change, a
                           unified diff; nothing is written.  --json prints
                           the encoding and the diffs as one document;
                           --color=auto|always|never colours the diff
                           (auto, the default, only on a terminal)
  xinsn.py verify SPEC     check a spec: its encoding, a free slot, a new
                           extension, the files it would change; no writes
  xinsn.py apply SPEC      edit the four source trees (idempotent)
  xinsn.py test  SPEC      build a test for it and run it on Spike and QEMU
                           (after scripts/build.sh has rebuilt the trees)
  xinsn.py all   SPEC      apply, rebuild, test: every step in one go
  xinsn.py list            every custom instruction in the trees, with its
                           encoding; --json prints one JSON array
  xinsn.py remove WHAT     take one out again and rebuild; WHAT is a name,
                           an opcode (MATCH or any instruction word, 0x...)
                           or a SPEC.  "attn" removes Xattn
                           (scripts/xattn.sh remove).  --no-rebuild edits
                           the trees and skips scripts/build.sh and the
                           toolchain check (used by tests/test_xinsn.py).

A SPEC file holds "key = value" lines, then a "semantics:" line followed by
the C body of the instruction:

  name     = mac           mnemonic; the ISA extension becomes Xmac
  inputs   = 3             source registers rs1..rs3 (0 to 3)
  writes   = rd            "rd": the result goes to rd;
                           "none": rd is one more source (like attn)
  memory   = no            "yes" if the semantics use LD*/ST*
  slot     = auto          or major:funct3:funct  e.g. custom-1:2:0
  semantics:
    return rs1 * rs2 + rs3;
  test:                    optional; required for memory = yes or
    CHECK (__builtin_riscv_mac (2, 3, 4) == 10);      writes = none

The body sees uint64_t rd, rs1, rs2, rs3 (zero-extended register values),
unsigned xlen, the loads LD8/LD16/LD32/LD64(addr), the stores
ST8/ST16/ST32/ST64(addr, value) and ILLEGAL(), which raises an
illegal-instruction trap.  The returned value is written to rd (truncated
and sign-extended on RV32).  The same body is compiled into Spike, QEMU
and the host model used by "test", so all three agree by construction.

The optional "test:" block is the body of main() in a bare-metal program
run on QEMU and Spike; CHECK (cond) records a failure.  Without it, an
instruction that writes rd from registers only is checked against the
host model on 64 input vectors.

In C the instruction is __builtin_riscv_<name>(...) with -march=..._x<name>,
taking the registers in operand order and returning rd's value.

Exit codes: 0 on success, 2 when the spec cannot be used, 3 when a build
step failed, 1 for anything else (a failing test, verify finding a taken
slot, an unknown instruction to remove).
"""

import argparse
import difflib
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import find_opcodes  # noqa: E402

# main() turns these into the exit status, so a caller can tell a bad spec
# from a failed build without reading the message.
EXIT_SPEC = 2
EXIT_BUILD = 3


class SpecError(Exception):
    """The spec cannot be used: exit 2."""


class BuildError(Exception):
    """A build step failed: exit 3."""


FORMAT_FIELDS = {"R0": ("funct3", "funct7"), "R1": ("funct3", "funct7"),
                 "R": ("funct3", "funct7"), "R4": ("funct3", "funct2")}

# ---------------------------------------------------------------- templates

TEMPLATES = {
    "elementwise": """\
# Elementwise: rd = rs1 + rs2, no memory access.
# Automatic vectors: there is no 'test:' block on purpose.
name   = {name}
inputs = 2
writes = rd
memory = no
slot   = auto
semantics:
  return rs1 + rs2;
""",
    "reduction": """\
# Reduction over rs2 32-bit words at rs1:
# rd = sum of *(uint32_t *) (rs1 + 4 i), 0 <= i < rs2.
name   = {name}
inputs = 2
writes = rd
memory = yes
slot   = auto
semantics:
  uint64_t s = 0;
  if (rs2 > 65536)
    ILLEGAL ();
  for (uint64_t i = 0; i < rs2; i++)
    s += LD32 (rs1 + 4 * i);
  return s;
test:
  static uint32_t a[100];
  for (int i = 0; i < 100; i++)
    a[i] = i * 2654435761u;
  uint64_t want = 0;
  for (int i = 0; i < 100; i++)
    want += a[i];
  CHECK (__builtin_riscv_{name} ((uintptr_t) a, 100) == want);
  CHECK (__builtin_riscv_{name} ((uintptr_t) a, 0) == 0);
  CHECK (__builtin_riscv_{name} ((uintptr_t) (a + 99), 1) == a[99]);
""",
    "memory": """\
# Store rs1 to rs2 consecutive 64-bit words at rd; rd is an operand,
# not a result, so writes = none.
name   = {name}
inputs = 2
writes = none
memory = yes
slot   = auto
semantics:
  for (uint64_t i = 0; i < rs2; i++)
    ST64 (rd + 8 * i, rs1);
  return 0;
test:
  static uint64_t b[10];
  __builtin_riscv_{name} ((uintptr_t) (b + 1), 0x1234567890abcdefull, 8);
  CHECK (b[0] == 0 && b[9] == 0);
  for (int i = 1; i <= 8; i++)
    CHECK (b[i] == 0x1234567890abcdefull);
""",
}


# ---------------------------------------------------------------- spec

class Spec:
    KEYS = ("name", "inputs", "writes", "memory", "slot")

    def __init__(self, path, need_test=True):
        text = Path(path).read_text()
        head, sep, body = text.partition("\nsemantics:")
        if not sep:
            raise SpecError("%s: missing 'semantics:' block" % path)
        kv = {}
        for line in head.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        for k in kv:
            if k not in self.KEYS:
                raise SpecError("%s: unknown key '%s' (the keys are %s)"
                         % (path, k, ", ".join(self.KEYS)))
        self.name = kv.get("name", "")
        if not self.name:
            raise SpecError("%s: missing 'name = ...'" % path)
        if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", self.name):
            raise SpecError("%s: name '%s' must match [a-z][a-z0-9]{1,15}"
                     % (path, self.name))
        if kv.get("inputs", "2") not in ("0", "1", "2", "3"):
            raise SpecError("%s: inputs must be 0..3, not '%s'"
                     % (path, kv.get("inputs")))
        self.inputs = int(kv.get("inputs", "2"))
        if kv.get("writes", "rd") not in ("rd", "none"):
            raise SpecError("%s: writes must be 'rd' or 'none', not '%s'"
                     % (path, kv.get("writes")))
        if kv.get("memory", "no") not in ("yes", "no"):
            raise SpecError("%s: memory must be 'yes' or 'no', not '%s'"
                     % (path, kv.get("memory")))
        self.writes_rd = kv.get("writes", "rd") == "rd"
        self.memory = kv.get("memory", "no") == "yes"
        self.slot = kv.get("slot", "auto")
        body, _, test = body.partition("\ntest:")
        self.body = body.strip("\n")
        self.test = test.strip("\n")
        if need_test and not self.test:
            if self.memory:
                raise SpecError("%s: 'memory = yes' needs a 'test:' block: a "
                                "model alone cannot check what the "
                                "instruction loads or stores" % path)
            if not self.writes_rd:
                raise SpecError(
                    "%s: 'writes = none' needs a 'test:' block: the result "
                    "is in memory, so there is nothing to compare against "
                    "the model" % path)
        self.ext = "x" + self.name
        self.EXT = self.ext.upper()
        self.N = self.name.upper()
        # Register operands in assembly order.
        self.regs = ["rd"] + ["rs1", "rs2", "rs3"][:self.inputs]
        self.sources = self.regs[1:] if self.writes_rd else self.regs
        self.format = find_opcodes.INPUTS_TO_FORMAT[self.inputs]

    def encoding(self):
        """(match, mask, description) for the instruction."""
        if self.slot != "auto":
            major, f3, f = self.slot.split(":")
            op = find_opcodes.MAJORS[major]
            mask = find_opcodes.FORMATS[self.format]["mask"]
            match = op | int(f3) << 12 | int(f) << 25
            return match, mask, self.slot
        existing = find_opcodes.load_defs(find_opcodes.default_sources(REPO))
        # Our own earlier apply must not make the slot look taken.
        existing.pop(self.name, None)
        classes = find_opcodes.load_classes(
            REPO / "binutils/opcodes/riscv-opc.c")
        for s in find_opcodes.free_slots(self.format, existing,
                                         find_opcodes.MAJORS, classes, True):
            if not s["used_by"]:
                return s["match"], s["mask"], "%s funct3=%d %s=%d" % (
                    s["major"], s["funct3"], FORMAT_FIELDS[self.format][1],
                    s.get("funct2", s.get("funct7")))
        raise SpecError(
            "no %s slot is free of every known encoding" % self.format)

    def word(self, match, regs):
        shifts = {"rd": 7, "rs1": 15, "rs2": 20, "rs3": 27}
        w = match
        for r, n in zip(self.regs, regs):
            w |= n << shifts[r]
        return w


# ---------------------------------------------------------------- editing

class Editor:
    """Applies edits, or with remove=True takes the same edits out again:
    inserted text is cut, written files are deleted.  A dry edit keeps the
    result in memory instead of writing it, so the preview diff is the whole
    change to a file, not each insert on its own."""

    def __init__(self, dry, remove=False):
        self.dry = dry
        self.remove = remove
        self.touched = []
        self.original = {}      # path -> text before any edit
        self.current = {}       # path -> text after the edits so far

    def read(self, path):
        if path not in self.current:
            p = REPO / path
            self.original[path] = p.read_text() if p.exists() else ""
            self.current[path] = self.original[path]
        return self.current[path] or ""

    def commit(self, path, text):
        """Record TEXT as the file's new content and write it unless dry;
        TEXT None deletes the file."""
        self.read(path)
        self.touched.append(path)
        self.current[path] = text
        if self.dry:
            return
        p = REPO / path
        if text is None:
            if p.exists():
                p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def insert(self, path, anchor, text, after=True, present=None):
        """Insert TEXT after (or before) the first line containing ANCHOR,
        unless PRESENT (default: TEXT) is already in the file."""
        s = self.read(path)
        if self.remove:
            # A PRESENT check marks text other instructions may share.
            if present is None and text in s:
                self.commit(path, s.replace(text, "", 1))
            return
        if (present or text.strip()) in s:
            return
        i = s.find(anchor)
        if i < 0:
            sys.exit("%s: anchor not found: %r" % (path, anchor))
        if after:
            i = s.index("\n", i) + 1
        else:
            i = s.rfind("\n", 0, i) + 1
        self.commit(path, s[:i] + text + s[i:])

    def write(self, path, text):
        if self.remove:
            if path in self.current or (REPO / path).exists():
                self.commit(path, None)
            return
        if self.read(path) == text:
            return
        self.commit(path, text)


def diff_text(path, old, new):
    """Unified diff of PATH from OLD to NEW: a/ and b/ headers, @@ hunks,
    -/+ lines; "" when nothing changes."""
    return "\n".join(difflib.unified_diff(
        old.splitlines(), (new or "").splitlines(),
        "a/" + path, "b/" + path, lineterm=""))


def colour_wanted(mode):
    """--color=auto colours only a terminal; always and never decide
    themselves."""
    if mode == "always":
        return True
    return mode == "auto" and sys.stdout.isatty()


def _colour_of(line):
    if line.startswith(("---", "+++")):
        return "1"                      # bold headers
    if line.startswith("@@"):
        return "36"                     # cyan hunk headers
    if line.startswith("+"):
        return "32"                     # green added lines
    if line.startswith("-"):
        return "31"                     # red removed lines
    return None


def colourise(diff, on):
    """Paint the diff for a terminal; unchanged when ON is false."""
    if not on:
        return diff
    out = []
    for line in diff.splitlines():
        code = _colour_of(line)
        out.append("\x1b[%sm%s\x1b[0m" % (code, line) if code else line)
    return "\n".join(out)



# ---------------------------------------------------------------- shared core

def core_header(sp):
    N = sp.N
    return f"""/* {sp.name}_core.h -- semantics of the {sp.EXT} instruction `{sp.name}'.
   Generated by scripts/xinsn.py; shared by Spike, QEMU and the host model.  */

#ifndef {N}_CORE_H
#define {N}_CORE_H

#include <stdint.h>

struct {sp.name}_mem
{{
  void *ctx;
  uint64_t (*ld) (void *ctx, uint64_t addr, unsigned bytes);
  void (*st) (void *ctx, uint64_t addr, uint64_t val, unsigned bytes);
}};

#define LD8(a) ((uint8_t) xinsn_m_->ld (xinsn_m_->ctx, (a), 1))
#define LD16(a) ((uint16_t) xinsn_m_->ld (xinsn_m_->ctx, (a), 2))
#define LD32(a) ((uint32_t) xinsn_m_->ld (xinsn_m_->ctx, (a), 4))
#define LD64(a) ((uint64_t) xinsn_m_->ld (xinsn_m_->ctx, (a), 8))
#define ST8(a, v) xinsn_m_->st (xinsn_m_->ctx, (a), (uint8_t) (v), 1)
#define ST16(a, v) xinsn_m_->st (xinsn_m_->ctx, (a), (uint16_t) (v), 2)
#define ST32(a, v) xinsn_m_->st (xinsn_m_->ctx, (a), (uint32_t) (v), 4)
#define ST64(a, v) xinsn_m_->st (xinsn_m_->ctx, (a), (uint64_t) (v), 8)
#define ILLEGAL() do {{ *xinsn_illegal_ = 1; return 0; }} while (0)

static inline uint64_t
{sp.name}_exec (const struct {sp.name}_mem *xinsn_m_, unsigned xlen,
	       uint64_t rd, uint64_t rs1, uint64_t rs2, uint64_t rs3,
	       int *xinsn_illegal_)
{{
  /* Internal names end in _ so the semantics cannot shadow them.  */
  (void) xinsn_m_; (void) xlen; (void) rd; (void) rs1; (void) rs2; (void) rs3;
  (void) xinsn_illegal_;
{sp.body}
}}

#undef LD8
#undef LD16
#undef LD32
#undef LD64
#undef ST8
#undef ST16
#undef ST32
#undef ST64
#undef ILLEGAL

#endif
"""


# ---------------------------------------------------------------- binutils

def apply_binutils(sp, ed, match, mask):
    ops = {0: "d", 1: "d,s", 2: "d,s,t", 3: "d,s,t,r"}[sp.inputs]
    ed.insert("binutils/include/opcode/riscv-opc.h", "#define MATCH_VT_MASKC ",
              f"#define MATCH_{sp.N} 0x{match:x}\n#define MASK_{sp.N} 0x{mask:x}\n",
              after=False)
    ed.insert("binutils/include/opcode/riscv-opc.h",
              "DECLARE_INSN(vt_maskc, MATCH_VT_MASKC, MASK_VT_MASKC)",
              f"DECLARE_INSN({sp.name}, MATCH_{sp.N}, MASK_{sp.N})\n",
              after=False)
    ed.insert("binutils/include/opcode/riscv.h", "  INSN_CLASS_XVENTANACONDOPS,",
              f"  INSN_CLASS_{sp.EXT},\n")
    ed.insert("binutils/bfd/elfxx-riscv.c",
              '  {"xventanacondops",	ISA_SPEC_CLASS_DRAFT,	1, 0, 0 },',
              f'  {{"{sp.ext}",		ISA_SPEC_CLASS_DRAFT,	1, 0, 0 }},\n')
    ed.insert("binutils/bfd/elfxx-riscv.c",
              '      return riscv_subset_supports (rps, "xventanacondops");',
              f'    case INSN_CLASS_{sp.EXT}:\n'
              f'      return riscv_subset_supports (rps, "{sp.ext}");\n')
    ed.insert("binutils/bfd/elfxx-riscv.c", '      return "xventanacondops";',
              f'    case INSN_CLASS_{sp.EXT}:\n      return "{sp.ext}";\n')
    ed.insert("binutils/opcodes/riscv-opc.c",
              "/* Vendor-specific (SiFive) vector coprocessor interface",
              f'/* {sp.EXT}.  */\n{{"{sp.name}", 0, INSN_CLASS_{sp.EXT}, '
              f'"{ops}", MATCH_{sp.N}, MASK_{sp.N}, match_opcode, 0 }},\n\n',
              after=False)
    names = ["a3", "a0", "a1", "a2"][:len(sp.regs)]
    nums = [13, 10, 11, 12][:len(sp.regs)]
    asm = "\t%s\t%s\n" % (sp.name, ", ".join(names))
    w = sp.word(match, nums)
    t = "binutils/gas/testsuite/gas/riscv/x-%s" % sp.name
    ed.write(t + ".s", "target:\n" + asm)
    ed.write(t + ".d", f"""#as: -march=rv64i_{sp.ext}
#source: x-{sp.name}.s
#objdump: -d

.*:[ 	]+file format .*


Disassembly of section .text:

0+000 <target>:
[ 	]+0:[ 	]+{w:08x}[ 	]+{sp.name}[ 	]+{",".join(names)}
""")


# ---------------------------------------------------------------- gcc

def regen_gcc_ext(ed):
    """Regenerate riscv-ext.opt and riscv-ext.texi from the .def files."""
    if ed.dry:
        return
    riscv = REPO / "gcc/gcc/config/riscv"
    tmp = REPO / "build/tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for gen, out in (("gen-riscv-ext-opt", riscv / "riscv-ext.opt"),
                     ("gen-riscv-ext-texi", REPO / "gcc/gcc/doc/riscv-ext.texi")):
        exe = tmp / gen
        try:
            subprocess.run(["g++", "-O1", "-I", riscv, riscv / (gen + ".cc"),
                            "-o", exe], check=True)
            text = subprocess.run([exe], check=True, capture_output=True,
                                  text=True).stdout
        except (subprocess.CalledProcessError, OSError) as e:
            raise BuildError("build failed: cannot build the GCC extension "
                             "generator %s (%s)" % (gen, e)) from e
        if out.read_text() != text:
            out.write_text(text)


def apply_gcc(sp, ed):
    g = "gcc/gcc/config/riscv/"
    ed.write(g + "riscv-ext-%s.def" % sp.ext, f"""/* {sp.EXT} extension definition file for RISC-V.
   Generated by xinsn.py.  Format of DEFINE_RISCV_EXT: see riscv-ext.def.  */

DEFINE_RISCV_EXT(
  /* NAME */ {sp.ext},
  /* UPPERCASE_NAME */ {sp.EXT},
  /* FULL_NAME */ "Custom {sp.name} instruction",
  /* DESC */ "",
  /* URL */ ,
  /* DEP_EXTS */ ({{}}),
  /* SUPPORTED_VERSIONS */ ({{{{1, 0}}}}),
  /* FLAG_GROUP */ {sp.ext},
  /* BITMASK_GROUP_ID */ BITMASK_NOT_YET_ALLOCATED,
  /* BITMASK_BIT_POSITION*/ BITMASK_NOT_YET_ALLOCATED,
  /* EXTRA_EXTENSION_FLAGS */ 0)
""")
    ed.insert(g + "riscv-ext.def", '#include "riscv-ext-spacemit.def"',
              '#include "riscv-ext-%s.def"\n' % sp.ext)
    ed.insert(g + "t-riscv", "RISCV_EXT_DEFS = \\",
              "  $(srcdir)/config/riscv/riscv-ext-%s.def \\\n" % sp.ext)
    regen_gcc_ext(ed)

    # RTL pattern.  Without memory side effects the result is a pure
    # function of the registers, so it may be CSEd and scheduled freely.
    n = len(sp.sources)
    first = 1 if sp.writes_rd else 0
    ins = "\n\t\t      ".join(
        '(match_operand:X %d "register_operand" "r")' % (first + i)
        for i in range(n)) or "(const_int 0)"
    asm = ",".join("%%%d" % i for i in range(len(sp.regs)))
    volatile = sp.memory or not sp.writes_rd
    unspec = ("UNSPECV_" if volatile else "UNSPEC_") + sp.EXT
    code = "unspec_volatile" if volatile else "unspec"
    if sp.writes_rd:
        body = ('(set (match_operand:X 0 "register_operand" "=r")\n'
                '\t(%s:X [%s]\n\t\t   %s))' % (code, ins, unspec))
    else:
        body = '(%s:X [%s]\n\t\t   %s)' % (code, ins, unspec)
    clobber = "\n   (clobber (mem:BLK (scratch)))" if sp.memory else ""
    pattern = f"""(define_insn "riscv_{sp.name}_<mode>"
  [{body}{clobber}]
  "TARGET_{sp.EXT}"
  "{sp.name}\\t{asm}"
  [(set_attr "type" "arith")
   (set_attr "mode" "<MODE>")])
"""
    ed.write(g + "%s.md" % sp.name,
             ";; %s: generated by scripts/xinsn.py.\n\n" % sp.EXT + pattern)
    ed.insert(g + "riscv.md", '(include "andes.md")',
              '(include "%s.md")\n' % sp.name)
    enum = '(define_c_enum "unspecv" [' if volatile else '(define_c_enum "unspec" ['
    ed.insert(g + "riscv.md", enum, "  %s\n" % unspec)

    # Builtins, one per XLEN.
    for bits, mode in ((32, "SI"), (64, "DI")):
        t = "U" + mode
        args = ", ".join([t] * n)
        ret = t if sp.writes_rd else "VOID"
        ftype = "DEF_RISCV_FTYPE (%d, (%s%s))" % (
            n, ret, ", " + args if n else "")
        ed.insert(g + "riscv-ftypes.def", "DEF_RISCV_FTYPE (4, (SI, SI, SI, SI, UQI))",
                  ftype + "\n", present=ftype)
        ed.insert(g + "riscv-builtins.cc",
                  "AVAIL (hard_float, TARGET_HARD_FLOAT || TARGET_ZFINX)",
                  "AVAIL (%s%d, TARGET_%s && %sTARGET_64BIT)\n" % (
                      sp.name, bits, sp.EXT, "!" if bits == 32 else ""))
    def ftname(mode):
        t = "U" + mode
        parts = [t if sp.writes_rd else "VOID", "FTYPE"] + [t] * n
        return "RISCV_" + "_".join(parts)
    kind = "RISCV_BUILTIN_DIRECT" if sp.writes_rd else \
        "RISCV_BUILTIN_DIRECT_NO_TARGET"
    ed.write(g + "%s.def" % sp.name,
             f"// {sp.EXT}: generated by scripts/xinsn.py.\n"
             f'RISCV_BUILTIN ({sp.name}_si, "{sp.name}", {kind}, {ftname("SI")}, {sp.name}32),\n'
             f'RISCV_BUILTIN ({sp.name}_di, "{sp.name}", {kind}, {ftname("DI")}, {sp.name}64),\n')
    ed.insert(g + "riscv-builtins.cc", '  #include "andes.def"',
              '  #include "%s.def"\n' % sp.name)
    if ed.remove:
        drop_unused_ftypes(sp, ed, g, ftname)


def drop_unused_ftypes(sp, ed, g, ftname):
    """Take out the builtin function types this instruction added once no
    other builtin still names them."""
    riscv = REPO / g
    users = "".join(p.read_text() for p in riscv.glob("*.def")
                    if p.name != "riscv-ftypes.def"
                    and not (p.name == sp.name + ".def" and not ed.dry))
    users += (riscv / "riscv-builtins.cc").read_text()
    n = len(sp.sources)
    for mode in ("SI", "DI"):
        if ftname(mode) in users:
            continue
        t = "U" + mode
        line = "DEF_RISCV_FTYPE (%d, (%s%s))\n" % (
            n, t if sp.writes_rd else "VOID",
            ", " + ", ".join([t] * n) if n else "")
        p = riscv / "riscv-ftypes.def"
        text = p.read_text()
        if line in text:
            ed.touched.append(g + "riscv-ftypes.def")
            if not ed.dry:
                p.write_text(text.replace(line, "", 1))


# ---------------------------------------------------------------- spike

def apply_spike(sp, ed, match, mask):
    regs = {"rd": "insn.rd()", "rs1": "insn.rs1()", "rs2": "insn.rs2()",
            "rs3": "insn.rs3()"}
    args = ", ".join("&arg_%s" % r for r in sp.regs)
    reads = "".join(
        "  reg_t %s = s->XPR[%s] & xmask;\n" % (r, regs[r]) for r in sp.regs)
    zero = "".join("  reg_t %s = 0;\n" % r for r in ("rs1", "rs2", "rs3")
                   if r not in sp.regs)
    write = ("  if (insn.rd())\n    s->XPR.write(insn.rd(), XLEN == 32 ? "
             "(reg_t)(int64_t)(int32_t)v : v);\n") if sp.writes_rd else \
        "  (void)v;\n"
    used = "|".join(regs[r] for r in sp.regs)
    ed.write("spike/riscv/%s_core.h" % sp.name, core_header(sp))
    ed.write("spike/riscv/%s.cc" % sp.ext, f"""// {sp.EXT}: generated by scripts/xinsn.py.

#include "extension.h"
#include "mmu.h"
#include "processor.h"
#include "trap.h"
#include "{sp.name}_core.h"

namespace {{

struct reg_arg_t : public arg_t {{
  int field;
  explicit reg_arg_t(int f) : field(f) {{}}
  std::string to_string(insn_t insn) const override {{
    switch (field) {{
      case 0: return xpr_name[insn.rd()];
      case 1: return xpr_name[insn.rs1()];
      case 2: return xpr_name[insn.rs2()];
      default: return xpr_name[insn.rs3()];
    }}
  }}
}};

const reg_arg_t arg_rd(0), arg_rs1(1), arg_rs2(2), arg_rs3(3);

uint64_t ld(void *p, uint64_t a, unsigned n)
{{
  mmu_t *m = static_cast<processor_t *>(p)->get_mmu();
  switch (n) {{
    case 1: return m->load<uint8_t>(a);
    case 2: return m->load<uint16_t>(a);
    case 4: return m->load<uint32_t>(a);
    default: return m->load<uint64_t>(a);
  }}
}}

void st(void *p, uint64_t a, uint64_t v, unsigned n)
{{
  mmu_t *m = static_cast<processor_t *>(p)->get_mmu();
  switch (n) {{
    case 1: m->store<uint8_t>(a, v); break;
    case 2: m->store<uint16_t>(a, v); break;
    case 4: m->store<uint32_t>(a, v); break;
    default: m->store<uint64_t>(a, v); break;
  }}
}}

template <int XLEN, bool RVE>
reg_t exec(processor_t *p, insn_t insn, reg_t pc)
{{
  if (RVE && (({used}) & 0x10))
    throw trap_illegal_instruction(insn.bits());
  const reg_t xmask = XLEN == 32 ? 0xffffffffull : ~0ull;
  state_t *s = p->get_state();
{reads}{zero}  {sp.name}_mem m = {{ p, ld, st }};
  int illegal = 0;
  uint64_t v = {sp.name}_exec(&m, XLEN, rd, rs1, rs2, rs3, &illegal);
  if (illegal)
    throw trap_illegal_instruction(insn.bits());
{write}  return pc + 4;
}}

class ext_t : public extension_t {{
 public:
  const char *name() const override {{ return "{sp.name}"; }}

  std::vector<insn_desc_t> get_instructions(const processor_t &) override {{
    return {{{{0x{match:x}, 0x{mask:x},
             exec<32, false>, exec<64, false>, exec<32, true>, exec<64, true>,
             exec<32, false>, exec<64, false>, exec<32, true>, exec<64, true>}}}};
  }}

  std::vector<disasm_insn_t *> get_disasms(const processor_t *) override {{
    return {{new disasm_insn_t("{sp.name}", 0x{match:x}, 0x{mask:x}, {{{args}}})}};
  }}
}};

}}  // namespace

extension_t *{sp.ext}_create()
{{
  static ext_t ext;
  return &ext;
}}
""")
    ed.insert("spike/riscv/extensions.cc", "extension_t *xattn_create();",
              "extension_t *%s_create();\n" % sp.ext)
    ed.insert("spike/riscv/extensions.cc", '    {"attn", xattn_create},',
              '    {"%s", %s_create},\n' % (sp.name, sp.ext))
    ed.insert("spike/riscv/riscv.mk.in", "\txattn.cc \\",
              "\t%s.cc \\\n" % sp.ext)


# ---------------------------------------------------------------- qemu

def decode_pattern(sp, match):
    bits = format(match, "032b")
    fields = {"R4": [(5, "....."), (2, None), (5, "....."), (5, "....."),
                     (3, None), (5, "....."), (7, None)],
              "R": [(7, None), (5, "....."), (5, "....."), (3, None),
                    (5, "....."), (7, None)],
              "R1": [(7, None), (5, None), (5, "....."), (3, None),
                     (5, "....."), (7, None)],
              "R0": [(7, None), (5, None), (5, None), (3, None),
                     (5, "....."), (7, None)]}[sp.format]
    out, pos = [], 0
    for width, free in fields:
        out.append(free or bits[pos:pos + width])
        pos += width
    return " ".join(out)


def apply_qemu(sp, ed, match):
    q = "qemu/target/riscv/"
    fields = "".join("%%%s %s\n" % (r, {"rd": "7:5", "rs1": "15:5",
                                        "rs2": "20:5", "rs3": "27:5"}[r])
                     for r in sp.regs)
    names = " ".join(sp.regs)
    refs = " ".join("%" + r for r in sp.regs)
    ed.write(q + "%s.decode" % sp.ext, f"""#
# {sp.EXT}: generated by scripts/xinsn.py.
#
# SPDX-License-Identifier: GPL-2.0-or-later
#

{fields}
&{sp.name}  {names}

@f  {decode_pattern(sp, 0).replace("0", ".").replace("1", ".")} &{sp.name} {refs}

{sp.name}   {decode_pattern(sp, match)} @f
""")
    get = ", ".join(
        "get_gpr(ctx, a->%s, EXT_ZERO)" % r if r in sp.regs else "tcg_constant_tl(0)"
        for r in ("rd", "rs1", "rs2", "rs3"))
    write = ("    gen_set_gpr(ctx, a->rd, dest);\n" if sp.writes_rd else "")
    ed.write(q + "tcg/insn_trans/trans_%s.c.inc" % sp.ext, f"""/*
 * {sp.EXT}: generated by scripts/xinsn.py.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

static bool trans_{sp.name}(DisasContext *ctx, arg_{sp.name} *a)
{{
    if (!ctx->cfg_ptr->ext_{sp.ext}) {{
        return false;
    }}
    TCGv dest = dest_gpr(ctx, a->rd);
    decode_save_opc(ctx, 0);
    gen_helper_{sp.name}(dest, tcg_env, {get});
{write}    return true;
}}
""")
    ed.write(q + "%s_core.h" % sp.name, core_header(sp))
    ed.write(q + "tcg/%s_helper.c" % sp.name, f"""/*
 * {sp.EXT}: generated by scripts/xinsn.py.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "qemu/osdep.h"
#include "cpu.h"
#include "internals.h"
#include "exec/helper-proto.h"
#include "accel/tcg/cpu-ldst.h"
#include "{sp.name}_core.h"

typedef struct {{
    CPURISCVState *env;
    uintptr_t ra;
}} Ctx;

static uint64_t ld(void *p, uint64_t a, unsigned n)
{{
    Ctx *c = p;
    a = adjust_addr(c->env, a);
    switch (n) {{
    case 1: return cpu_ldub_data_ra(c->env, a, c->ra);
    case 2: return cpu_lduw_le_data_ra(c->env, a, c->ra);
    case 4: return cpu_ldl_le_data_ra(c->env, a, c->ra);
    default: return cpu_ldq_le_data_ra(c->env, a, c->ra);
    }}
}}

static void st(void *p, uint64_t a, uint64_t v, unsigned n)
{{
    Ctx *c = p;
    a = adjust_addr(c->env, a);
    switch (n) {{
    case 1: cpu_stb_data_ra(c->env, a, v, c->ra); break;
    case 2: cpu_stw_le_data_ra(c->env, a, v, c->ra); break;
    case 4: cpu_stl_le_data_ra(c->env, a, v, c->ra); break;
    default: cpu_stq_le_data_ra(c->env, a, v, c->ra); break;
    }}
}}

target_ulong helper_{sp.name}(CPURISCVState *env, target_ulong rd,
                       target_ulong rs1, target_ulong rs2, target_ulong rs3)
{{
    Ctx ctx = {{ env, GETPC() }};
    struct {sp.name}_mem m = {{ &ctx, ld, st }};
    int illegal = 0;
    unsigned xlen = riscv_cpu_xlen(env);
    uint64_t v = {sp.name}_exec(&m, xlen, rd, rs1, rs2, rs3, &illegal);
    if (illegal) {{
        riscv_raise_exception(env, RISCV_EXCP_ILLEGAL_INST, GETPC());
    }}
    return xlen == 32 ? (target_ulong)(int32_t)v : (target_ulong)v;
}}
""")
    ed.insert(q + "cpu_cfg_fields.h.inc", "BOOL_FIELD(ext_xlrbr)",
              "BOOL_FIELD(ext_%s)\n" % sp.ext)
    ed.insert(q + "cpu_cfg.h", "MATERIALISE_EXT_PREDICATE(xlrbr);",
              "MATERIALISE_EXT_PREDICATE(%s)\n" % sp.ext)
    # isa_edata_arr is kept in canonical (alphabetical) order.
    cpu = (REPO / q / "cpu.c").read_text()
    xs = re.findall(r"    ISA_EXT_DATA_ENTRY\((x[a-z0-9]*),", cpu)
    later = [x for x in xs if x > sp.ext and x != sp.ext]
    anchor = "    ISA_EXT_DATA_ENTRY(%s," % (later[0] if later else xs[-1])
    ed.insert(q + "cpu.c", anchor,
              "    ISA_EXT_DATA_ENTRY(%s, PRIV_VERSION_1_12_0, ext_%s),\n"
              % (sp.ext, sp.ext), after=not later)
    ed.insert(q + "meson.build",
              "  decodetree.process('xlrbr.decode', extra_args: '--static-decode=decode_xlrbr'),",
              "  decodetree.process('%s.decode', extra_args: "
              "'--static-decode=decode_%s'),\n" % (sp.ext, sp.ext))
    ed.insert(q + "tcg/meson.build", "  'zce_helper.c',",
              "  '%s_helper.c',\n" % sp.name)
    ed.insert(q + "tcg/translate.c", '#include "decode-xlrbr.c.inc"',
              '#include "decode-%s.c.inc"\n' % sp.ext)
    ed.insert(q + "tcg/translate.c", '#include "insn_trans/trans_xlrbr.c.inc"',
              '#include "insn_trans/trans_%s.c.inc"\n' % sp.ext)
    ed.insert(q + "tcg/translate.c", "    { has_xlrbr_p, decode_xlrbr},",
              "    { has_%s_p, decode_%s},\n" % (sp.ext, sp.ext))
    ed.insert(q + "helper.h", "DEF_HELPER_FLAGS_2(crc32c, TCG_CALL_NO_RWG_SE, tl, tl, tl)",
              "DEF_HELPER_5(%s, tl, env, tl, tl, tl, tl)\n" % sp.name)


# ---------------------------------------------------------------- test

def host_model(sp, out_dir):
    """Build a host program that evaluates the semantics on stdin vectors."""
    src = out_dir / "model.c"
    core = out_dir / ("%s_core.h" % sp.name)
    core.write_text(core_header(sp))
    src.write_text(f"""#include <inttypes.h>
#include <stdio.h>
#include "{sp.name}_core.h"
int main (void)
{{
  unsigned xlen;
  uint64_t r[4];
  while (scanf ("%u %" SCNx64 " %" SCNx64 " %" SCNx64 " %" SCNx64, &xlen,
		&r[0], &r[1], &r[2], &r[3]) == 5)
    {{
      int illegal = 0;
      uint64_t v = {sp.name}_exec (0, xlen, r[0], r[1], r[2], r[3], &illegal);
      if (xlen == 32)
	v = (uint64_t) (int64_t) (int32_t) v;
      printf ("%d %" PRIx64 "\\n", illegal, v);
    }}
  return 0;
}}
""")
    exe = out_dir / "model"
    subprocess.run(["cc", "-O2", "-I", out_dir, src, "-o", exe], check=True)
    return exe


def vector_test(sp, out):
    """Program checking the builtin against the host model on 64 vectors."""
    rng = random.Random(sp.name)
    edge = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
            0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF]
    vecs = []
    for i in range(64):
        vecs.append([edge[i % len(edge)] if i < 27 else rng.getrandbits(64)
                     for _ in range(3)])
    model = host_model(sp, out)
    # Unused source registers read as zero, as in the simulators.
    vecs = [v[:sp.inputs] + [0] * (3 - sp.inputs) for v in vecs]
    inp = "".join("64 0 %x %x %x\n" % tuple(v) for v in vecs)
    res = subprocess.run([model], input=inp, capture_output=True, text=True,
                         check=True).stdout.split("\n")
    rows = []
    for v, line in zip(vecs, res):
        illegal, val = line.split()
        if illegal != "0":
            continue
        rows.append("    { 0x%xull, 0x%xull, 0x%xull, 0x%sull }," % (*v, val))
    args = ", ".join("t->a[%d]" % i for i in range(sp.inputs))
    return f"""  static const struct vec {{ uint64_t a[3]; uint64_t want; }} vecs[] = {{
{chr(10).join(rows)}
  }};
  for (unsigned i = 0; i < sizeof vecs / sizeof vecs[0]; i++)
    {{
      const struct vec *t = &vecs[i];
      CHECK (__builtin_riscv_{sp.name} ({args}) == t->want);
    }}"""


def run_test(sp):
    if not sp.test and (sp.memory or not sp.writes_rd):
        sys.exit("test: add a 'test:' block; vectors only work for "
                 "instructions that write rd from registers alone")
    out = REPO / "build/xinsn" / sp.name
    out.mkdir(parents=True, exist_ok=True)
    body = sp.test or vector_test(sp, out)
    (out / "test.c").write_text(f"""/* Generated by xinsn.py test for {sp.name}.  */
#include <stdint.h>
#include "bm.h"

static int failures;
#define CHECK(cond) do {{ if (!(cond)) {{ bm_puts ("check failed at line "); bm_puthex (__LINE__); bm_puts (": " #cond "\\n"); failures++; }} }} while (0)

int
main (void)
{{
{body}
  bm_puts (failures ? "{sp.name}: FAILED\\n" : "{sp.name}: all checks passed\\n");
  return failures != 0;
}}
""")
    cc = REPO / "out/toolchain/bin/riscv64-unknown-elf-gcc"
    bm = REPO / "tests/baremetal"
    flags = ["-march=rv64gc_" + sp.ext, "-mabi=lp64d", "-mcmodel=medany",
             "-O2", "-nostdlib", "-nostartfiles", "-ffreestanding",
             "-I", bm, "-T", bm / "link.ld", "-static",
             "-Wl,--no-warn-rwx-segments"]
    env = dict(__import__("os").environ, TMPDIR=str(REPO / "build/tmp"))
    ok = True
    for sim in ("qemu", "spike"):
        elf = out / ("test-%s.elf" % sim)
        subprocess.run([cc, *flags] + (["-DBM_SPIKE"] if sim == "spike" else [])
                       + [bm / "crt.S", bm / "bm.c", out / "test.c", "-o", elf],
                       check=True, env=env)
        if sim == "qemu":
            cmd = [REPO / "build/qemu/qemu-system-riscv64", "-M", "virt",
                   "-bios", "none", "-nographic", "-monitor", "none",
                   "-serial", "stdio", "-cpu", "rv64,%s=on" % sp.ext,
                   "-kernel", elf]
        else:
            cmd = [REPO / "out/spike/bin/spike", "--isa=rv64gc_" + sp.ext, elf]
        env2 = dict(env, PATH=str(REPO / "out/host/bin") + ":" + env["PATH"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                           env=env2)
        print("%-5s %s" % (sim, r.stdout.strip() or r.stderr.strip()))
        ok &= r.returncode == 0
    dis = subprocess.run([REPO / "out/toolchain/bin/riscv64-unknown-elf-objdump",
                          "-d", out / "test-qemu.elf"], capture_output=True,
                         text=True).stdout
    used = len(re.findall(r"\t%s\t" % sp.name, dis))
    print("objdump: %d %s instruction(s) in the test" % (used, sp.name))
    sys.exit(0 if ok and used else 1)


# ---------------------------------------------------------------- main

def edit_all(sp, ed, match, mask):
    apply_binutils(sp, ed, match, mask)
    apply_gcc(sp, ed)
    apply_spike(sp, ed, match, mask)
    apply_qemu(sp, ed, match)


def rebuild():
    """Run scripts/build.sh; a failure of any kind is a BuildError."""
    try:
        subprocess.run([REPO / "scripts/build.sh", "binutils", "gcc", "spike",
                        "qemu"], check=True)
    except subprocess.CalledProcessError as e:
        raise BuildError("build failed: scripts/build.sh exited %d"
                         % e.returncode) from e
    except OSError as e:
        raise BuildError("build failed: cannot run scripts/build.sh (%s)"
                         % e) from e


def encoding_line(sp, match, mask, where):
    """The one encoding line show, apply and verify print for a spec."""
    return ("%s: format %s, %s, MATCH=0x%08x MASK=0x%08x, -march=..._%s"
            % (sp.name, sp.format, where, match, mask, sp.ext))


def cmd_apply(spec, dry, as_json=False, colour=False):
    sp = Spec(spec)
    match, mask, where = sp.encoding()
    if not as_json:
        print(encoding_line(sp, match, mask, where))
    ed = Editor(dry=dry)
    edit_all(sp, ed, match, mask)
    paths = list(dict.fromkeys(ed.touched))
    if as_json:
        print(json.dumps({
            "encoding": encoding_line(sp, match, mask, where),
            "name": sp.name, "ext": sp.ext, "format": sp.format,
            "match": match, "mask": mask,
            "files": [{"path": p,
                       "diff": diff_text(p, ed.original.get(p, ""),
                                         ed.current.get(p, ""))}
                      for p in paths]}, indent=2))
        return sp
    for p in paths:
        print(("would change " if dry else "changed ") + p)
        if dry:
            print(colourise(diff_text(p, ed.original.get(p, ""),
                                      ed.current.get(p, "")), colour))
    if not paths:
        print("already applied")
    if not dry:
        # remove NAME finds the spec here later.
        keep = REPO / "build/xinsn/specs" / (sp.name + ".spec")
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spec, keep)
    return sp


def ask(prompt, default=None, check=None):
    while True:
        v = input("%s%s: " % (prompt, " [%s]" % default if default else ""))
        v = v.strip() or (default or "")
        if not check or check(v):
            return v
        print("  not valid, try again")


def ask_block(prompt):
    print(prompt + " (end with a line holding only '.')")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join("  " + ln if ln and not ln.startswith("  ") else ln
                     for ln in lines)


def cmd_new(spec, template=None):
    if template:
        if spec:
            name = Path(spec).stem
            if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", name):
                sys.exit("name '%s' must match [a-z][a-z0-9]{1,15}" % name)
            path = Path(spec)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEMPLATES[template].format(name=name))
            print("wrote %s" % path)
            return
        name = ask("name (lower case, e.g. mac)", None,
                   lambda v: re.fullmatch(r"[a-z][a-z0-9]{1,15}", v))
        path = REPO / "examples/insns" / (name + ".spec")
        path.write_text(TEMPLATES[template].format(name=name))
        print("wrote %s" % path)
        if ask("apply, rebuild and test now? (y/n)", "y") == "y":
            cmd_all(path)
        return
    print("New custom RISC-V instruction.  The C code sees uint64_t rd, rs1,"
          "\nrs2, rs3, unsigned xlen, LD8..LD64(addr), ST8..ST64(addr, v) and"
          "\nILLEGAL(); it returns the value for rd.")
    name = ask("name (lower case, e.g. mac)", None,
               lambda v: re.fullmatch(r"[a-z][a-z0-9]{1,15}", v))
    inputs = ask("source registers rs1..rs3 (0-3)", "2",
                 lambda v: v in ("0", "1", "2", "3"))
    writes = ask("writes rd? rd = result, none = rd is an input", "rd",
                 lambda v: v in ("rd", "none"))
    memory = ask("uses LD*/ST*? (yes/no)", "no", lambda v: v in ("yes", "no"))
    slot = ask("encoding slot (auto finds a free one)", "auto")
    body = ask_block("C code of the instruction")
    test = ask_block("test: body of main(), CHECK (cond) per check; "
                     "empty for automatic vectors")
    spec = Path(spec or REPO / "examples/insns" / (name + ".spec"))
    spec.write_text(f"""# Written by xinsn.py new.
name   = {name}
inputs = {inputs}
writes = {writes}
memory = {memory}
slot   = {slot}
semantics:
{body}
""" + ("test:\n%s\n" % test if test.strip() else ""))
    print("wrote %s" % spec)
    if ask("apply, rebuild and test now? (y/n)", "y") == "y":
        cmd_all(spec)


def cmd_all(spec):
    sp = cmd_apply(spec, dry=False)
    rebuild()
    run_test(sp)


def custom_insns():
    """[(name, match, mask, generated_by_xinsn, ext)] for every custom
    instruction in the trees: Xattn and everything xinsn.py added."""
    h = (REPO / "binutils/include/opcode/riscv-opc.h").read_text()
    out = []
    riscv = REPO / "gcc/gcc/config/riscv"
    for d in sorted(riscv.glob("riscv-ext-x*.def")):
        ext = d.stem[len("riscv-ext-"):]
        name = "attn" if ext == "xattn" else ext[1:]
        mm = [re.search(r"#define %s_%s (0x[0-9a-f]+)" % (k, name.upper()), h)
              for k in ("MATCH", "MASK")]
        if not all(mm):
            continue
        out.append((name, int(mm[0].group(1), 16), int(mm[1].group(1), 16),
                    "xinsn.py" in d.read_text(), ext))
    return out


def custom_rows():
    """[{name, ext, match, mask, source}] for tooling (list --json)."""
    return [dict(name=name, ext=ext, match=match, mask=mask,
                 source="xinsn.py" if gen else "scripts/xattn.sh")
            for name, match, mask, gen, ext in custom_insns()]


def cmd_list(as_json=False):
    if as_json:
        print(json.dumps(custom_rows(), indent=2))
        return
    rows = custom_insns()
    if not rows:
        print("no custom instructions in the trees")
    for name, match, mask, gen, ext in rows:
        print("%-12s MATCH=0x%08x MASK=0x%08x  %s" % (
            name, match, mask,
            "added by xinsn.py" if gen else "Xattn (scripts/xattn.sh)"))


def cmd_verify(spec):
    """Check a spec without touching the trees: its encoding, the slot
    against every known encoding, the extension name, and the files the
    edits would change."""
    sp = Spec(spec)
    match, mask, where = sp.encoding()
    print(encoding_line(sp, match, mask, where))
    defs = find_opcodes.load_defs(find_opcodes.default_sources(REPO))
    # Our own earlier apply must not look like a collision, as in encoding().
    hits = sorted(n for n, e in defs.items()
                  if n != sp.name and find_opcodes.collides((match, mask), e))
    if hits:
        sys.exit("%s: %s collides with %s already in the trees; "
                 "pick a free slot" % (spec, where, ", ".join(hits)))
    print("ok: %d known encodings checked; the slot collides with none"
          % len(defs))
    elf = (REPO / "binutils/bfd/elfxx-riscv.c").read_text()
    if re.search(r'\{\s*"%s"\s*,\s*ISA_SPEC_CLASS_' % re.escape(sp.ext), elf):
        sys.exit("%s: the ELF attribute %s1p0 is taken; %s is an existing "
                 "vendor extension" % (spec, sp.ext, sp.ext))
    print("ok: extension %s is new (not already a vendor extension)" % sp.ext)
    ed = Editor(dry=True)
    try:
        edit_all(sp, ed, match, mask)
    except SystemExit as e:
        sys.exit("%s (%d files would change before that)"
                 % (e.code, len(dict.fromkeys(ed.touched))))
    print("ok: %d files would change; the trees are not touched"
          % len(dict.fromkeys(ed.touched)))


def find_spec(name):
    for p in (REPO / "examples/insns" / (name + ".spec"),
              REPO / "build/xinsn/specs" / (name + ".spec")):
        if p.exists():
            return p
    sys.exit("no spec found for %s (looked in examples/insns and "
             "build/xinsn/specs); pass the spec file instead" % name)


def cmd_remove(what, build=True):
    rows = custom_insns()
    if Path(what).is_file():
        spec = Path(what)
        name = Spec(spec).name
    else:
        name = what
        if re.fullmatch(r"0x[0-9a-fA-F]+", what):
            word = int(what, 16)
            hit = [r for r in rows if word & r[2] == r[1]]
            if not hit:
                sys.exit("no custom instruction has opcode %s" % what)
            name = hit[0][0]
            print("%s is %s" % (what, name))
        spec = None
    row = next((r for r in rows if r[0] == name), None)
    if row is None:
        sys.exit("%s is not a custom instruction in the trees "
                 "(see: xinsn.py list)" % name)
    if not row[3]:
        subprocess.run([REPO / "scripts/xattn.sh", "remove"], check=True)
        return
    sp = Spec(spec or find_spec(name), need_test=False)
    ed = Editor(dry=False, remove=True)
    # The encoding in the trees, so the cut text matches what was inserted.
    edit_all(sp, ed, row[1], row[2])
    for p in dict.fromkeys(ed.touched):
        print("changed " + p)
    if not build:
        print("%s removed from the trees; not rebuilt" % name)
        return
    rebuild()
    gas = subprocess.run(
        [REPO / "out/toolchain/bin/riscv64-unknown-elf-as",
         "-march=rv64gc", "-o", "/dev/null", "-"],
        input="\t%s\n" % sp.name, text=True, capture_output=True)
    print("%s removed: the assembler %s it" % (
        name, "rejects" if gas.returncode else "still accepts"))
    if not gas.returncode:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["new", "show", "verify", "apply", "test",
                                    "all", "list", "remove"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--json", action="store_true",
                    help="list: print one JSON array instead of text;\n"
                         "show: print the encoding and every diff as one\n"
                         "JSON document")
    ap.add_argument("--color", choices=("auto", "always", "never"),
                    default="auto",
                    help="show: colour the diff; auto (the default) colours\n"
                         "only when stdout is a terminal")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="remove: edit the trees but do not run\n"
                         "scripts/build.sh, and skip the toolchain check")
    ap.add_argument("--template", choices=sorted(TEMPLATES),
                    help="new: write a prefilled spec from TEMPLATE")
    a = ap.parse_args()
    if a.json and (a.cmd not in ("list", "show") or a.no_rebuild):
        ap.error("--json needs 'list' or 'show'")
    if a.template and a.cmd != "new":
        ap.error("--template needs 'new'")
    if a.cmd in ("show", "verify", "apply", "test", "all", "remove") \
            and not a.arg:
        ap.error("%s needs an argument" % a.cmd)
    try:
        if a.cmd == "new":
            cmd_new(a.arg, a.template)
        elif a.cmd == "list":
            cmd_list(a.json)
        elif a.cmd == "remove":
            cmd_remove(a.arg, build=not a.no_rebuild)
        elif a.cmd == "verify":
            cmd_verify(a.arg)
        elif a.cmd == "all":
            cmd_all(a.arg)
        elif a.cmd == "test":
            run_test(Spec(a.arg))
        else:
            cmd_apply(a.arg, dry=a.cmd == "show", as_json=a.json,
                      colour=colour_wanted(a.color))
            if a.cmd == "apply":
                print("next: scripts/build.sh binutils gcc spike qemu && "
                      "scripts/xinsn.py test " + a.arg)
    except SpecError as e:
        print(e, file=sys.stderr)
        return EXIT_SPEC
    except BuildError as e:
        print(e, file=sys.stderr)
        return EXIT_BUILD
    return 0


if __name__ == "__main__":
    sys.exit(main())

