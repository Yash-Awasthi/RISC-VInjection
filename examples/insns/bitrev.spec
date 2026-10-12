# Bit reversal of the low XLEN bits of rs1.
name   = bitrev
inputs = 1
semantics:
  uint64_t r = 0;
  for (unsigned i = 0; i < xlen; i++)
    r |= ((rs1 >> i) & 1) << (xlen - 1 - i);
  return r;
