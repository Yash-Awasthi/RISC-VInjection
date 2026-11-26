# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose and spell out the encoding of a custom instruction."""

import find_opcodes

from scripts.xinsn_common import REPO, SpecError

FORMAT_FIELDS = {"R0": ("funct3", "funct7"), "R1": ("funct3", "funct7"),
                 "R": ("funct3", "funct7"), "R4": ("funct3", "funct2")}


def choose_encoding(sp):
    """(match, mask, description) for the instruction."""
    if sp.slot != "auto":
        major, f3, f = sp.slot.split(":")
        op = find_opcodes.MAJORS[major]
        mask = find_opcodes.FORMATS[sp.format]["mask"]
        match = op | int(f3) << 12 | int(f) << 25
        return match, mask, sp.slot
    existing = find_opcodes.load_defs(find_opcodes.default_sources(REPO))
    # Our own earlier apply must not make the slot look taken.
    existing.pop(sp.name, None)
    classes = find_opcodes.load_classes(
        REPO / "binutils/opcodes/riscv-opc.c")
    for s in find_opcodes.free_slots(sp.format, existing,
                                     find_opcodes.MAJORS, classes, True):
        if not s["used_by"]:
            return s["match"], s["mask"], "%s funct3=%d %s=%d" % (
                s["major"], s["funct3"], FORMAT_FIELDS[sp.format][1],
                s.get("funct2", s.get("funct7")))
    raise SpecError(
        "no %s slot is free of every known encoding" % sp.format)


def word(sp, match, regs):
    shifts = {"rd": 7, "rs1": 15, "rs2": 20, "rs3": 27}
    w = match
    for r, n in zip(sp.regs, regs):
        w |= n << shifts[r]
    return w


def encoding_line(sp, match, mask, where):
    """The one encoding line show, apply and verify print for a spec."""
    return ("%s: format %s, %s, MATCH=0x%08x MASK=0x%08x, -march=..._%s"
            % (sp.name, sp.format, where, match, mask, sp.ext))
