# Contributing

Two rules cover most of it: **the patches are the only delta from upstream**,
and **a claim without a command is a rumour**. Everything below follows from
them.

## Sign-off (DCO 1.1)

Every commit must carry a `Signed-off-by` line:

```bash
git commit -s            # or: git commit --signoff
```

The line means you wrote the change, or have the right to submit it under this
repository's licence (`LICENSE`, GPL-3.0-or-later), and that you understand it
is public. It must use your real name and an address you control. No
`Signed-off-by` for paperwork you cannot sign: no bots signing for people.

Commits without it are rejected, not fixed up.

## How the change lives in the tree

The Xattn changes are kept in four submodules on a branch called `xattn`, and
exported to `patches/`. Do not hand-edit `patches/*.patch`.

```bash
scripts/patches.sh apply            # pinned upstream commits -> branch xattn
#   ... edit binutils/ gcc/ spike/ qemu/ ...
git -C gcc commit -s -m 'RISC-V: ...'
scripts/patches.sh export gcc       # rewrite patches/gcc/*.patch
git add patches/gcc && git commit -s
```

* One patch, one idea, with a `git format-patch` header: author, date, subject,
  and a body that says what breaks without it and what you tested.
* Each patch header names the upstream list it targets and whether it has been
  submitted.
* Check the series against the pinned commit before pushing:

```bash
scripts/patches.sh apply && make check
```

* `scripts/xattn.sh remove` must leave a pristine tree. If
  `git -C gcc status --porcelain` is not empty afterwards, the change leaks
  outside the branch: fix that before anything else.

## Tests

```bash
make check              # host model, compiler tests, both simulators, recognizer
make check-xinsn-sim    # a generated instruction on QEMU and Spike (slow)
python3 -m pytest -q tests/   # the two above minus the build-dependent parts
```

* New behaviour needs a test that fails without it. Say in the commit message
  which test failed before and passes after.
* A change to `scripts/xinsn.py` needs `tests/test_xinsn.py` to pass; it is the
  only automated test of the general method.
* No test may depend on a build that is not in `make check`.

## The encoding and the semantics are normative

`docs/spec.md` defines the instruction: encoding, descriptor layouts, exact
behaviour, exceptions. So:

* a **semantic** change (any observable behaviour, including a trap) requires a
  new spec version in `docs/spec.md` with a changelog entry, a re-frozen vector
  set (until `tests/vectors/` exists, the frozen check is
  `tests/test_core.py` against `tools/attn_model.py`), and a compatibility note
  in the commit message;
* a **cosmetic** change (comments, formatting, a faster equivalent kernel that
  is bit-identical) requires no version bump, but must show the vectors still
  pass;
* `include/attn_core.h` has exactly one definition, copied into
  `spike/riscv/`, `qemu/target/riscv/` and `gcc/libgcc/`.
  `tests/test_core.py::test_simulator_cores_match_include` fails when a copy
  drifts; copy the file over, never edit the copies.

## Licence headers

* Original files (`include/`, `scripts/`, `tests/`, `tools/`, `demo/`,
  `examples/`, `docs/`) carry `SPDX-License-Identifier: GPL-3.0-or-later`.
* Files inside a submodule keep their upstream headers, untouched. Never add an
  SPDX line to a patched upstream file: the patch would then claim a licence
  grant it cannot make.
* See `NOTICE` for which part comes from where.

## Style

* C: the surrounding code's style, C11 for the host tests, C89-compatible in
  headers that a simulator compiles.
* Shell: `set -euo pipefail`, `shellcheck -x scripts/*.sh` clean.
* Python: no new dependencies without a line here and a pinned version in the
  install step (`Makefile`, until M3.1.2 replaces it with a hashed file).
* Commit subject: `area: what changed — the proof`. The body carries the
  command and its output.
