# Multiply-accumulate: rd = rs1 * rs2 + rs3 (low XLEN bits).
name   = mac
inputs = 3
writes = rd
memory = no
slot   = auto
semantics:
  return rs1 * rs2 + rs3;
