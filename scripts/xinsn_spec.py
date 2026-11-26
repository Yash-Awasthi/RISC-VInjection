# SPDX-License-Identifier: GPL-3.0-or-later
"""Parse an instruction spec file and find one by name."""

import re
import sys
from pathlib import Path

import find_opcodes

from scripts.xinsn_common import REPO, SpecError

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


def find_spec(name):
    for p in (REPO / "examples/insns" / (name + ".spec"),
              REPO / "build/xinsn/specs" / (name + ".spec")):
        if p.exists():
            return p
    sys.exit("no spec found for %s (looked in examples/insns and "
             "build/xinsn/specs); pass the spec file instead" % name)
