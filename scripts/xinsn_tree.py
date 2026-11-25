# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit the binutils, GCC, Spike and QEMU trees for one instruction."""

import difflib
import re
import subprocess
import sys

from scripts.xinsn_common import REPO, BuildError, core_header
from scripts.xinsn_encoding import word


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
    w = word(sp, match, nums)
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


def edit_all(sp, ed, match, mask):
    apply_binutils(sp, ed, match, mask)
    apply_gcc(sp, ed)
    apply_spike(sp, ed, match, mask)
    apply_qemu(sp, ed, match)


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
