# Xattn patch series: cover letter

`attn` is one RISC-V instruction that computes a complete multi-head
self-attention block from four address operands, in custom-3. The normative
definition is `docs/spec.md`; the executable form is `include/attn_core.h`,
which Spike, QEMU, libgcc and the host tests all run unchanged.

This file is the submission package. The five trees are pinned in
`versions.env`; the series lives on branch `xattn` in each and is exported
by `scripts/patches.sh export`. Each patch carries its rationale, the test
it was checked with, the upstream review list and `Submitted: no`. Nothing
in this series has been sent to a list.

## Series

binutils, 1 patch, pinned `781713dde4c8`, list `binutils@sourceware.org`:

    RISC-V: add the Xattn vendor extension

gcc, 5 patches, pinned `041359f347cb`, list `gcc-patches@gcc.gnu.org`:

    RISC-V: add Xattn, its builtin and the attention recognizer
    Move the attention recognizer into the middle end
    Add the generic __builtin_attn and libgcc's __attn
    Represent attn as its own RTL code
    libgcc: attn_core.h, attn_abi.h: add the SPDX licence line

qemu, 3 patches, pinned `615ece3c406b`, list `qemu-devel@nongnu.org`:

    target/riscv: add the Xattn extension
    target/riscv: let attn_core.h build without libc headers
    target/riscv: attn_core.h, attn_abi.h: add the SPDX licence line

spike, 3 patches, pinned `89c7471fd811`, no list in tree; riscv-isa-sim
takes pull requests on GitHub:

    Add the Xattn extension (--isa=..._xattn)
    Let attn_core.h build without libc headers
    riscv: attn_core.h, attn_abi.h: add the SPDX licence line

## Test plan

Run from the repository root on a machine with the build prerequisites in
`docs/build-and-test.md` section 1.

1. `git submodule update --init` then `scripts/check-pins.sh`. Expected:
   five lines, one per submodule, each the commit `versions.env` pins. A
   drifted tree stops here with `error: <NAME>_SHA in ... is ..., but the
   superproject pins ...`.
2. `scripts/patches.sh apply`. Expected: one line per component; each of
   the four trees checked out on branch `xattn` above its pin. This is the
   step a reviewer's `git am` replaces: 12 patches, in the order listed
   above.
3. `scripts/build.sh`. Expected: six `== <step>` lines and `== done`;
   about 15 minutes on 16 cores. It writes `out/BUILD-INFO` with the five
   pinned and built SHAs.
4. `make check`. Expected: exit 0. It runs `check-core` (the header
   against the float64 model), `check-gcc` (the testsuite files: the
   instruction, the builtin, the recognizer), `check-sched`, `check-demo`, `check-sim`
   (bare metal on Spike and QEMU, 14 value and trap checks each),
   `check-recog`, `check-lint` and `check-shell`.
5. `make check-three-way`. Expected: seven rows, each `maxdiff` of zero,
   so Spike, QEMU and the host model agree bit for bit.
6. `scripts/patches.sh remove`. Expected: every tree clean and detached at
   its pin; `git -C gcc status --porcelain` empty. A difference there is a
   bug: the patches are the only delta.

## What the reviewer is being asked to accept

- One encoding in custom-3 that overlaps no standard or vendor encoding
  (`scripts/find_opcodes.py`).
- One definition of the semantics, compiled into all three executions,
  with bit-exact agreement (`docs/spec.md` section 3, `make check-three-way`).
- Illegal-instruction when the extension is absent or the configuration is
  reserved (`docs/spec.md` section 4, `tests/test_core.py`).
- The recognizer is a separate opt-in pass in the gcc series, so a target
  that does not want it keeps plain loops.

A semantic change needs the process in `docs/review.md`: spec version,
re-frozen vectors, all three executions.