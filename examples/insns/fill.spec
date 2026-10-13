# Store rs1 to rs2 consecutive 64-bit words starting at address rd.
# rd is an operand, not a result: writes = none.
name   = fill
inputs = 2
writes = none
memory = yes
semantics:
  for (uint64_t i = 0; i < rs2; i++)
    ST64 (rd + 8 * i, rs1);
  return 0;
test:
  static uint64_t b[10];
  __builtin_riscv_fill ((uintptr_t) (b + 1), 0x1234567890abcdefull, 8);
  CHECK (b[0] == 0 && b[9] == 0);
  for (int i = 1; i <= 8; i++)
    CHECK (b[i] == 0x1234567890abcdefull);
