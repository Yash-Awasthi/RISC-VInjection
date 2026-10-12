#!/usr/bin/env python3
"""List free RISC-V encodings for a new custom instruction.

Every MATCH/MASK pair already defined in the checked-out binutils
(include/opcode/riscv-opc.h) and Spike (riscv/encoding.h) trees is loaded,
then each candidate slot in the custom-0..3 major opcodes is tested for
overlap.  Two encodings collide when some 32-bit word satisfies both, which
is exactly when (match1 ^ match2) & mask1 & mask2 == 0.

  find_opcodes.py --inputs 3            # R4: rd, rs1, rs2, rs3
  find_opcodes.py --inputs 2 --first    # R:  rd, rs1, rs2
  find_opcodes.py --format I --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MAJORS = {"custom-0": 0x0B, "custom-1": 0x2B, "custom-2": 0x5B,
          "custom-3": 0x7B}

# Fixed-field masks per format.  R1 is R with rs2 locked to zero, R0 also
# locks rs1: they cost no extra opcode space beyond their R slot.
FORMATS = {
    "R4": dict(mask=0x0600707F, fields=("funct3", "funct2")),
    "R": dict(mask=0xFE00707F, fields=("funct3", "funct7")),
    "R1": dict(mask=0xFFF0707F, fields=("funct3", "funct7")),
    "R0": dict(mask=0xFFFFF07F, fields=("funct3", "funct7")),
    "I": dict(mask=0x0000707F, fields=("funct3",)),
}
INPUTS_TO_FORMAT = {0: "R0", 1: "R1", 2: "R", 3: "R4"}

DEFINE = re.compile(r"#define\s+(MATCH|MASK)_(\w+)\s+(0x[0-9a-fA-F]+|\d+)")
ROW = re.compile(r'\{\s*"[^"]+",\s*\w+,\s*INSN_CLASS_(\w+),\s*"[^"]*",'
                 r'\s*MATCH_(\w+)')


def load_classes(opc_c):
    """{insn name: ISA class} from the binutils opcode table."""
    if not opc_c.is_file():
        return {}
    return {name.lower(): cls
            for cls, name in ROW.findall(opc_c.read_text(errors="replace"))}


def is_vendor(cls):
    """Vendor (X*) extensions share the custom space by design: only one
    vendor's encodings are enabled by a given -march string."""
    return cls is not None and cls.startswith("X")


def load_defs(paths):
    """{name: (match, mask)} from every header that exists."""
    found = {}
    for p in paths:
        if not p.is_file():
            continue
        m = {}
        for kind, name, val in DEFINE.findall(p.read_text(errors="replace")):
            m.setdefault(name, {})[kind] = int(val, 0)
        for name, d in m.items():
            if "MATCH" in d and "MASK" in d:
                found[name.lower()] = (d["MATCH"], d["MASK"])
    return found


def default_sources(tree):
    return [tree / "binutils/include/opcode/riscv-opc.h",
            tree / "spike/riscv/encoding.h"]


def collides(a, b):
    (m1, k1), (m2, k2) = a, b
    return ((m1 ^ m2) & k1 & k2) == 0


def candidates(fmt, majors):
    f = FORMATS[fmt]
    for name, op in majors.items():
        for f3 in range(8):
            if "funct2" in f["fields"]:
                for f2 in range(4):
                    yield name, dict(funct3=f3, funct2=f2), \
                        op | f3 << 12 | f2 << 25, f["mask"]
            elif "funct7" in f["fields"]:
                for f7 in range(128):
                    yield name, dict(funct3=f3, funct7=f7), \
                        op | f3 << 12 | f7 << 25, f["mask"]
            else:
                yield name, dict(funct3=f3), op | f3 << 12, f["mask"]


def free_slots(fmt, existing, majors=MAJORS, classes=None, strict=False):
    """A slot is free when it overlaps no standard encoding; with strict it
    must overlap nothing.  Slots with the fewest vendor overlaps come first."""
    classes = classes or {}
    out = []
    for major, fields, match, mask in candidates(fmt, majors):
        hits = [n for n, e in existing.items() if collides((match, mask), e)]
        vendor = [n for n in hits if is_vendor(classes.get(n))]
        std = [n for n in hits if n not in vendor]
        out.append(dict(major=major, opcode=majors[major], **fields,
                        match=match, mask=mask, used_by=std + vendor if strict
                        else std, shared_with=[] if strict else vendor))
    return sorted(out, key=lambda s: (bool(s["used_by"]),
                                      len(s["shared_with"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--inputs", type=int, choices=sorted(INPUTS_TO_FORMAT),
                   help="number of source registers (picks the format)")
    g.add_argument("--format", choices=sorted(FORMATS))
    ap.add_argument("--major", choices=sorted(MAJORS), action="append",
                    help="restrict to these major opcodes (repeatable)")
    ap.add_argument("--tree", type=Path, default=REPO,
                    help="directory holding binutils/ and spike/")
    ap.add_argument("--header", type=Path, action="append", default=[],
                    help="extra header with MATCH_/MASK_ defines")
    ap.add_argument("--all", action="store_true", help="also show used slots")
    ap.add_argument("--strict", action="store_true",
                    help="treat vendor-extension encodings as taken too")
    ap.add_argument("--first", action="store_true", help="print one free slot")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    fmt = a.format or INPUTS_TO_FORMAT[3 if a.inputs is None else a.inputs]
    srcs = default_sources(a.tree) + a.header
    existing = load_defs(srcs)
    if not existing:
        sys.exit("no MATCH_/MASK_ definitions found in: "
                 + ", ".join(map(str, srcs)))
    majors = {k: MAJORS[k] for k in (a.major or MAJORS)}
    classes = load_classes(a.tree / "binutils/opcodes/riscv-opc.c")
    slots = free_slots(fmt, existing, majors, classes, a.strict)
    show = slots if a.all else [s for s in slots if not s["used_by"]]
    if a.first:
        show = show[:1]
        if not show:
            sys.exit("no free %s slot" % fmt)

    if a.json:
        print(json.dumps(dict(format=fmt, known=len(existing), slots=show),
                         indent=1))
        return
    print("format %s, %d known encodings, %d of %d slots free"
          % (fmt, len(existing), sum(not s["used_by"] for s in slots),
             len(slots)), file=sys.stderr)
    for s in show:
        fields = " ".join("%s=%d" % (k, s[k])
                          for k in ("funct3", "funct2", "funct7") if k in s)
        note = ""
        if s["used_by"]:
            note = " used by " + ",".join(s["used_by"][:4])
        elif s["shared_with"]:
            note = " shared with %d vendor insns (%s)" % (
                len(s["shared_with"]), ",".join(s["shared_with"][:3]))
        print("%-8s %-22s MATCH=0x%08x MASK=0x%08x%s"
              % (s["major"], fields, s["match"], s["mask"], note))


if __name__ == "__main__":
    main()
