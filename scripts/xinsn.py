#!/usr/bin/env python3
"""Plug a new custom RISC-V instruction into binutils, GCC, Spike and QEMU.

  xinsn.py show  SPEC      encoding and the files that would change
  xinsn.py apply SPEC      edit the four source trees (idempotent)
  xinsn.py test  SPEC      build a test for it and run it on Spike and QEMU
                           (after scripts/build.sh has rebuilt the trees)

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
"""

import argparse
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import find_opcodes  # noqa: E402

FORMAT_FIELDS = {"R0": ("funct3", "funct7"), "R1": ("funct3", "funct7"),
                 "R": ("funct3", "funct7"), "R4": ("funct3", "funct2")}


# ---------------------------------------------------------------- spec

class Spec:
    def __init__(self, path):
        text = Path(path).read_text()
        head, sep, body = text.partition("\nsemantics:")
        if not sep:
            sys.exit("%s: missing 'semantics:' block" % path)
        kv = {}
        for line in head.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        self.name = kv.get("name", "")
        if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", self.name):
            sys.exit("name must match [a-z][a-z0-9]{1,15}")
        self.inputs = int(kv.get("inputs", "2"))
        if not 0 <= self.inputs <= 3:
            sys.exit("inputs must be 0..3")
        self.writes_rd = kv.get("writes", "rd") == "rd"
        self.memory = kv.get("memory", "no") == "yes"
        self.slot = kv.get("slot", "auto")
        body, _, test = body.partition("\ntest:")
        self.body = body.strip("\n")
        self.test = test.strip("\n")
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
        sys.exit("no %s slot is free of every known encoding" % self.format)

    def word(self, match, regs):
        shifts = {"rd": 7, "rs1": 15, "rs2": 20, "rs3": 27}
        w = match
        for r, n in zip(self.regs, regs):
            w |= n << shifts[r]
        return w


# ---------------------------------------------------------------- editing

class Editor:
    def __init__(self, dry):
        self.dry = dry
        self.touched = []

    def insert(self, path, anchor, text, after=True, present=None):
        """Insert TEXT after (or before) the first line containing ANCHOR,
        unless PRESENT (default: TEXT) is already in the file."""
        p = REPO / path
        s = p.read_text()
        if (present or text.strip()) in s:
            return
        i = s.find(anchor)
        if i < 0:
            sys.exit("%s: anchor not found: %r" % (path, anchor))
        if after:
            i = s.index("\n", i) + 1
        else:
            i = s.rfind("\n", 0, i) + 1
        self.touched.append(path)
        if not self.dry:
            p.write_text(s[:i] + text + s[i:])

    def write(self, path, text):
        p = REPO / path
        if p.exists() and p.read_text() == text:
            return
        self.touched.append(path)
        if not self.dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)


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
        subprocess.run(["g++", "-O1", "-I", riscv, riscv / (gen + ".cc"),
                        "-o", exe], check=True)
        text = subprocess.run([exe], check=True, capture_output=True,
                              text=True).stdout
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
        body = (f'(set (match_operand:X 0 "register_operand" "=r")\n'
                f'\t(%s:X [%s]\n\t\t   %s))' % (code, ins, unspec))
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

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["show", "apply", "test"])
    ap.add_argument("spec")
    a = ap.parse_args()
    sp = Spec(a.spec)
    if a.cmd == "test":
        run_test(sp)
        return
    match, mask, where = sp.encoding()
    print("%s: format %s, %s, MATCH=0x%08x MASK=0x%08x, -march=..._%s"
          % (sp.name, sp.format, where, match, mask, sp.ext))
    ed = Editor(dry=a.cmd == "show")
    apply_binutils(sp, ed, match, mask)
    apply_gcc(sp, ed)
    apply_spike(sp, ed, match, mask)
    apply_qemu(sp, ed, match)
    for p in dict.fromkeys(ed.touched):
        print(("would change " if ed.dry else "changed ") + p)
    if not ed.touched:
        print("already applied")
    elif not ed.dry:
        print("next: scripts/build.sh binutils gcc spike qemu && "
              "scripts/xinsn.py test " + a.spec)


if __name__ == "__main__":
    main()
