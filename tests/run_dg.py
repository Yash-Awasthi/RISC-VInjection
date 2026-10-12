#!/usr/bin/env python3
"""Run GCC testsuite files without DejaGnu.

Understands the directives the Xattn tests use: dg-do compile|preprocess,
dg-options, dg-error (on the same line), and dg-final scan-assembler,
scan-assembler-not, scan-assembler-times and scan-tree-dump.

  run_dg.py [--cc PATH] FILE...
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CC = REPO / "out/toolchain/bin/riscv64-unknown-elf-gcc"


def tcl_regex(s):
    # The directive is a Tcl string: "\\t" reaches the regex engine as "\t".
    return s.replace("\\\\", "\\")


def run(cc, src, tmp):
    text = src.read_text()
    do = re.search(r"dg-do (\w+)", text).group(1)
    opts = re.search(r'dg-options "([^"]*)"', text).group(1).split()
    errors = {i + 1: m.group(1)
              for i, line in enumerate(text.splitlines())
              for m in [re.search(r'dg-error "([^"]*)"', line)] if m}
    out = tmp / (src.stem + (".i" if do == "preprocess" else ".s"))
    cmd = [str(cc), *opts, "-E" if do == "preprocess" else "-S", str(src),
           "-o", str(out)]
    r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
    problems = []
    for line, msg in errors.items():
        if not re.search(r"%s:%d:\d+: error: .*%s" % (re.escape(src.name),
                                                      line, msg), r.stderr):
            problems.append("missing error at line %d: %s" % (line, msg))
    if errors:
        return problems
    if r.returncode:
        return ["compiler failed:\n" + r.stderr]
    asm = out.read_text() if out.exists() else ""
    for kind, args in re.findall(r"dg-final \{ (scan-[\w-]+) (.*?) \} \} \*/",
                                 text):
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', args)
        vals = [a or b for a, b in parts]
        pat = tcl_regex(vals[0])
        if kind == "scan-assembler":
            ok = re.search(pat, asm)
        elif kind == "scan-assembler-not":
            ok = not re.search(pat, asm)
        elif kind == "scan-assembler-times":
            ok = len(re.findall(pat, asm)) == int(vals[1])
        elif kind == "scan-tree-dump":
            dumps = list(tmp.glob(src.stem + ".c.*t." + vals[1]))
            ok = dumps and re.search(pat, dumps[0].read_text())
        else:
            problems.append("unsupported directive " + kind)
            continue
        if not ok:
            problems.append("%s %s failed" % (kind, " ".join(vals)))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cc", type=Path, default=DEFAULT_CC)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    failed = 0
    for f in a.files:
        with tempfile.TemporaryDirectory(dir=REPO / "build") as d:
            problems = run(a.cc, f.resolve(), Path(d))
        print(("FAIL " if problems else "PASS ") + f.name)
        for p in problems:
            print("     " + p)
        failed += bool(problems)
    print("%d of %d passed" % (len(a.files) - failed, len(a.files)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
