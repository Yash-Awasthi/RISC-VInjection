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
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _dir in (str(REPO), str(REPO / "scripts")):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
import find_opcodes  # noqa: E402

from scripts.xinsn_build import rebuild, run_test  # noqa: E402
from scripts.xinsn_common import EXIT_BUILD, EXIT_SPEC, BuildError, SpecError  # noqa: E402
from scripts.xinsn_encoding import choose_encoding, encoding_line  # noqa: E402
from scripts.xinsn_spec import TEMPLATES, Spec, find_spec  # noqa: E402
from scripts.xinsn_tree import (  # noqa: E402
    Editor,
    colour_wanted,
    colourise,
    custom_insns,
    custom_rows,
    diff_text,
    edit_all,
)


def cmd_apply(spec, dry, as_json=False, colour=False):
    sp = Spec(spec)
    match, mask, where = choose_encoding(sp)
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
    match, mask, where = choose_encoding(sp)
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
