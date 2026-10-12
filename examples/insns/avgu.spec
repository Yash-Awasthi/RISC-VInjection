# Unsigned average without overflow: rd = floor((rs1 + rs2) / 2) over XLEN bits.
name   = avgu
inputs = 2
semantics:
  uint64_t m = xlen == 32 ? 0xffffffffu : ~0ull;
  uint64_t a = rs1 & m, b = rs2 & m;
  return (a & b) + ((a ^ b) >> 1);
