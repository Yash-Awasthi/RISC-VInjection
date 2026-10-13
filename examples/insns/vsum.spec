# Sum of rs2 32-bit words starting at address rs1 (a memory-reading
# reduction): rd = sum_{i < rs2} *(uint32_t *) (rs1 + 4 i).
name   = vsum
inputs = 2
writes = rd
memory = yes
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
  CHECK (__builtin_riscv_vsum ((uintptr_t) a, 100) == want);
  CHECK (__builtin_riscv_vsum ((uintptr_t) a, 0) == 0);
  CHECK (__builtin_riscv_vsum ((uintptr_t) (a + 99), 1) == a[99]);
