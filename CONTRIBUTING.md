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

## Bump procedure

A bump moves the series to a new upstream head. It touches the five gitlinks,
`versions.env`, the re-exported `patches/`, and the compatibility table, which
records the SHA that was tested.

1. Export first. `scripts/patches.sh apply` moves branch `xattn` back to the
   pin, so a commit that exists only on the branch would drop off it:

   ```bash
   scripts/patches.sh export && git add patches && git commit -s
   ```

2. Fetch the branch `versions.env` names for the component, then move the pin
   in both places it is recorded — the index gitlink and `versions.env`:

   ```bash
   git -C gcc fetch origin releases/gcc-16
   git update-index --cacheinfo 160000,<new-sha>,gcc
   sed -i 's/^GCC_SHA=.*/GCC_SHA=<new-sha>/' versions.env
   scripts/check-pins.sh
   ```

3. Rebase the series onto the new pin and prove it. `apply` replays the patches
   with `git am --3way`; a conflict is resolved, `git am --continue`d, and the
   re-export then carries the resolution:

   ```bash
   scripts/patches.sh apply gcc
   scripts/patches.sh export gcc
   scripts/patches.sh check
   make check
   git add patches && git commit -s
   ```

4. Re-run the full CI. `.github/workflows/full.yml` is the only job that builds
   the toolchain and runs every test; it fires on any push that touches
   `patches/`, so the bump runs it. Do not push the bump until it is green.

5. Update the compatibility table in `docs/build-and-test.md` that the weekly
   drift job publishes — patch series, upstream branch and tested SHA — with
   the SHA `scripts/check-pins.sh` printed, so the table names the commit this
   bump was tested at.

`newlib` carries no patches: only its pin moves (steps 2 and 4).

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
