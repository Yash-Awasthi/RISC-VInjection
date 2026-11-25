# Reviewing a change to include/attn_core.h

`include/attn_core.h` is the one executable definition of the `attn`
instruction. Spike, QEMU and libgcc each run a byte-for-byte copy of it, and
the host tests run it directly. A change there is a change to the
specification, so the checklist below is the minimum for any edit, a comment
included.

## 1. Spec

- Decide what kind of change it is. Any observable change, a trap included,
  is a semantic change (docs/spec.md section 7).
- A semantic change carries a new version in the title of docs/spec.md and a
  new row in its changelog. Read both: `sed -n '1,15p' docs/spec.md`.
- A cosmetic change keeps the version, but still needs a changelog note that
  says no semantics moved, as the version 1.0 row does.

## 2. Vectors

- tests/vectors holds 14 frozen vectors plus MANIFEST.json, and the manifest
  records the hash of include/attn_core.h, so any edit to the header makes
  the frozen check fail.
- Confirm the check does fail, and read the message it prints:
  `.venv/bin/python tools/freeze_vectors.py`.
- Re-freeze only with a recorded reason, and for a semantic change only at
  the new version:
  `.venv/bin/python tools/freeze_vectors.py --refreeze --reason "TEXT"`.
- Read the new manifest entry, and confirm the reason names the spec version.
  Then run the vectors: `make check-core` and
  `.venv/bin/python -m pytest -q tests/test_vectors.py`.

## 3. The executions

The header is copied into each tree, never edited there. tests/test_core.py
compares the bytes and fails on drift, so a fix belongs in include/ first.

### Spike

- Copy: spike/riscv/attn_core.h. Memory goes through mmu_t load and store,
  and a fault becomes a trap_t exception.
- Check the copy moved with include/ by running `make check-sim`, which
  executes the bare-metal image on Spike and requires every byte of Y to
  equal the host core, trap cases included.

### QEMU

- Copy: qemu/target/riscv/attn_core.h. Memory goes through cpu_ld*_data_ra
  and cpu_st*_data_ra, and a fault leaves through cpu_loop_exit_restore.
- Run `make check-sim`; it runs the same image on QEMU and compares it with
  the host core, trap cases included.
- Run `make check-three-way` when the arithmetic changes: it requires QEMU,
  Spike and the host core to agree bit for bit on all 7 configurations.

### libgcc and the host

- Copies: gcc/libgcc/attn_core.h for the software fallback `__attn`, and
  include/attn_core.h for the host core behind ctypes.
- Run `make check-core`: the host core against the float64 model on 13
  configurations, plus the byte comparison of all three copies.
- Run `make check-recog`: it calls libgcc `__attn` through `__builtin_attn`
  without Xattn and requires the same bytes as the plain loops.
