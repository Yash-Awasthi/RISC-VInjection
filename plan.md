# plan.md — RISC-VInjection (Xattn)

Consolidated plan. Replaces `docs/build-and-test.md`, `docs/implementation.md`,
`docs/new-instruction.md`, `docs/recognizer.md`, `docs/spec.md`,
`docs/study.md`, `docs/theory.md`, `docs/walkthrough.md` **as planning
documents**; they stay as reference material, but the state of work lives here.
`docs/spec.md` remains normative for the instruction and is never restated in
this file.

Generated 2026-11-24. Evidence base: `README.md`, the eight `docs/*.md` (1,617
lines), `Makefile`, `scripts/{setup,build,patches,xattn,attncc,artifacts}.sh`,
`scripts/xinsn.py`, `scripts/find_opcodes.py`, nine patch files under `patches/`,
`include/attn_core.h`, `tests/{test_core.py,run_dg.py,baremetal,recog,host}`,
`demo/mha_plain.c`, `artifacts/` (184 KB), the five submodules and their pinned
commits, and 74 tracked files.

**Order:** corrective → preventive → perfective → widening → depth → enterprise.

**Hierarchy:** Phase → Major (M#.#) → Minor (m#.#.#) → Subtask. One subtask = one

**Done tasks stay.** A finished subtask becomes `- [x]` in place with one evidence line under it (`verified-here: <command> → <result>`). Nothing is ever removed from this list.
PR = one command that proves it.

**Tag (exactly one):** `[C]` corrective · `[P]` preventive · `[F]` perfective ·
`[W]` widening · `[D]` depth · `[E]` enterprise.

**Method anchors:** `engineering-craft` (reproduce, then fix; a claim without a
command is a rumour), `game-dev` §2 (determinism, golden vectors),
`security-operations` §5 (fuzzing untrusted descriptors), `data-ml` §8
(evaluation with n and variance), `writing-docs` §1, `devops-cloud` §8/§9.

---

## 0. Verified ground truth

| Fact | Measured | Claimed | Source |
|---|---|---|---|
| Upstream bases | binutils `binutils-2_47-branch` @ `781713d`, GCC `releases/gcc-16` @ `041359f`, Spike `89c7471`, QEMU `615ece3`, newlib `06add56` | "current upstream sources" | `git submodule status` |
| Submodule branch fields | Spike and QEMU `branch = master`; newlib points at `cygwin/cygwin` `main` | — | `.gitmodules` |
| Patch series | 9 patches: binutils 1, GCC 4, QEMU 2, Spike 2 | — | `patches/` |
| Build | `scripts/build.sh`, six steps, ~15 min on 16 cores | same | README, script header |
| Tests | `make check` = `check-core` (pytest vs float64 model), `check-gcc` (dg files), `check-sim` (bare-metal on Spike and QEMU), `check-recog` (runtime loop recognition) | "all agree bit for bit" | `Makefile` |
| CI | **none** — no `.github/`, no other CI config | — | `ls -a` |
| Licence | **no `LICENSE`, no `COPYING`, no `CONTRIBUTING`** in 74 tracked files | — | `git ls-files` |
| Python deps | `python3 -m venv .venv && pip install -q numpy pytest` — unpinned | — | `Makefile:21-24` |
| `xinsn.py` tests | none (the general method has no automated test) | "takes a short spec … then tests it on both simulators" | `grep -rln xinsn tests` → only itself |
| Tracked evidence | `artifacts/` with dumps, run logs, loops, excerpt | — | `ls artifacts` |
| Instruction | `attn rd, rs1, rs2, rs3`, custom-3, `MATCH 0x0600107b`, `MASK 0x0600707f` | same | `docs/spec.md:1-20` |
| Host model | `include/attn_core.h`, shared by Spike, QEMU and host tests | same | `docs/spec.md` |
| Licence obligations | GCC and binutils patches are derivative works of GPLv3 code | — | upstream licences |

Invariants:

1. **One definition.** `include/attn_core.h` is the only semantics; Spike, QEMU and the host tests compile it. A second copy anywhere is a defect.
2. **Bit-exactness.** For a fixed input the three executions agree exactly, and the float64 model agrees within the tolerance the tests state. Any change to either must show the new numbers.
3. **The encoding is normative.** `MATCH/MASK`, the descriptor layouts in `docs/spec.md`, and the ELF attribute `xattn1p0` do not change without a spec version bump.
4. **Illegal without the extension.** Encoding when `_xattn` is absent raises an illegal-instruction trap in both simulators.
5. **Patches are the only delta.** `scripts/xattn.sh remove` restores a pristine tree; a difference in `git -C <sub> status` after remove is a bug.
6. **No silent upstream drift.** Submodules are pinned by commit; the build records the five submodule SHAs it used.

---

## Phase 1 — Corrective: the project must be reproducible by someone else

### M1.1 There is no CI

**Why:** every claim in the README is verified by a human running `make check` on
one machine. That is the whole risk: the next `git clone` may not build, and
nothing would say so.
**Done when:** a push builds and tests the project, and a claim that fails is
visible on the commit that broke it.

- [x] Fast job (≤10 min, no toolchain build): `check-core`, `python3 -m pytest -q tests/`, `shellcheck scripts/*.sh`, on every push. `[C]`
  - verified-here: `.github/workflows/ci.yml` job `fast`; each step re-run here in a `python:3.12` container against the pinned trees: `scripts/patches.sh apply binutils gcc spike qemu` → 4 lines, 7.8 s; `python3 -m pytest -q tests/` → `32 passed in 3.90s`; `shellcheck -x scripts/*.sh` → no output, exit 0; `actionlint` → no findings.
  - corrected: `python -m pytest tools/` measured `no tests ran`, exit 5 (`tools/` holds no tests) — the step is `pytest tests/`.
  - corrected: `check-gcc` needs `out/toolchain/bin/riscv64-unknown-elf-gcc` (`Makefile`), i.e. a build, so it moved to the full job (M1.1.2); the fast job does not build.
- [x] Full job (nightly + on a change under `patches/`, `include/`, `scripts/`): submodules, `scripts/patches.sh apply`, `scripts/build.sh`, `make check`, artifacts uploaded. `[C]`
  - verified-here: `.github/workflows/full.yml`; `actionlint` → no findings; every step was run here in containers against the pinned trees: `scripts/patches.sh apply` → 4 components, 7.8 s; `scripts/build.sh` (all six steps) → `== done`; `make check` → exit 0 in 97 s (`check-core`, 30+ `PASS xattn-*.c` dg files, bare-metal on Spike+QEMU, recognizer on both). Ubuntu 24.04 is the host because the pinned QEMU's `configure` refuses Python < 3.12 (`Cannot use '/usr/bin/python3', Python >= 3.12 is required` on Debian 12's 3.11).
  - needs-verify: the workflow has not run on a GitHub runner from this machine; the commands and the exit codes were reproduced in `debian:bookworm` + `python:3.12-slim-bookworm` containers, not on the runner image.
- [x] Cache the built toolchain and ccache between full runs by patch SHA; a cache hit must be validated by `make check`, never trusted blindly. `[C]`
  - verified-here: `full.yml` keys both caches on `sha256(submodule SHAs)` and `sha256(patches/*/*.patch)`, caches `out/toolchain` + `build/{binutils,gcc,newlib}` and validates a hit before the build: `riscv64-unknown-elf-gcc --version` → `GCC 16.2.1`, `-march=rv64gc_xattn -E` → ok, `as` accepts `attn` → ok; without the extension the same line fails (`Error: unrecognized opcode \`attn a3,a0,a1,a2', extension \`xattn' required`), so a stale toolchain drops the cache and rebuilds. Cached set compresses to 810 MB (`tar -czf`), then `make check` (exit 0) is the real validation. `actionlint` → no findings.
  - deviation: ccache is not wired into `scripts/build.sh` yet (that is m3.2.1), so only the toolchain trees are cached here.
- [x] Publish the job result and the five submodule SHAs as a badge/artefact so the README's claim carries evidence. `[C]`
  - verified-here: `README.md` carries both workflow badges (`ci.yml`, `full.yml`); `full.yml` writes `build/CI-TRACE.txt` (commit, date, runner, pinned SHA and checked-out SHA side by side, plus the gcc/Spike/QEMU versions) and uploads it. The git half run here → `binutils 781713d`, `gcc 041359f`, `newlib 06add56`, `qemu 615ece3`, `spike 89c7471` pinned, and `heads/xattn` for the four patched trees. `actionlint` → no findings.
  - corrected: the repository has **five** submodules, not six; every "six SHAs" in this file now says five (the six-step build is a different six).
  - needs-verify: the badge images resolve only once the workflows have run on GitHub.

### M1.2 The general method is untested

**Why:** the second half of the product is "`xinsn.py` plugs any instruction into
four projects". It has no test, so a change to it is only checked by hand on a
15-minute build — which means it is not checked.
**Done when:** a scratch instruction is created, applied, listed, tested and
removed by an automated test.

- [x] `tests/test_xinsn.py`: create a SPEC (`mac`, `rs1*rs2+rs3`) in a temp dir, `show`, assert the chosen encoding and the file list. `[C]`
  - verified-here: `python3 -m pytest -q tests/test_xinsn.py` → `3 passed in 1.43s`; pinned encoding `mac: format R4, custom-3 funct3=3 funct2=2, MATCH=0x0400307b MASK=0x0600707f`, 29 files.
- [x] Apply to a scratch copy of the trees, assert idempotence (second apply is a no-op), then `remove` and assert `git status --porcelain` is empty. `[C]`
  - verified-here: `python3 -m pytest -q tests/test_xinsn.py` → `5 passed in 41.63s`; a scratch copy of `gcc/gcc/config/riscv`, `spike/riscv`, `qemu/target/riscv` and the four binutils files takes the 29 edits, a second `apply` prints `already applied`, `remove mac --no-rebuild` leaves `git status --porcelain` empty. `remove` twice exits 1: `mac is not a custom instruction in the trees`.
- [x] Encoding safety: assert the allocated MATCH/MASK never collides with a standard opcode, another custom extension in the tree, or a second user instruction (uses `find_opcodes.py`). `[C]`
  - verified-here: `python3 -m pytest -q tests/test_xinsn.py` → `7 passed in 142.70s`; 3006 known encodings, every example slot free; five instructions applied in turn to one scratch tree get five distinct encodings (`vsum`, `fill`, `avgu` all start at `0x0600302b` until the previous one is applied).
- [x] Slow job: run the generated instruction on Spike and QEMU and assert the `CHECK` lines pass. `[C]`
  - verified-here: `XATTN_XINSN_SIM=1 .venv/bin/python -m pytest -q tests/test_xinsn.py -k both_simulators` → `1 passed in 238.13s`; underneath, `xinsn.py test examples/insns/mac.spec` → `qemu  mac: all checks passed`, `spike mac: all checks passed`, `objdump: 1 mac instruction(s)`. New target: `make check-xinsn-sim` (skipped without `scripts/build.sh` and the env var).
  - deviation: the QEMU subtree was rebuilt with `mac` applied in a separate Python 3.12 container and its binary copied into `build/qemu`, because this build container has Python 3.11 and the pinned QEMU requires ≥3.12. The `binutils`/`gcc`/`spike` steps ran for real.
- [x] Failure paths: malformed SPEC (missing name, `writes = none` without a test, memory semantics without a test) each exit non-zero with a specific message. `[C]`
  - verified-here: `python3 -m pytest -q tests/test_xinsn.py` → `15 passed in 157.45s`; the 8 `test_a_bad_spec_is_refused` cases exit 1 and name the spec file: `missing 'name = ...'`, `must match [a-z][a-z0-9]{1,15}`, `missing 'semantics:' block`, `unknown key 'writse'`, `needs a 'test:' block` (twice), `inputs must be 0..3`, `writes must be 'rd' or 'none'`.

### M1.3 Licence and contribution terms are missing

**Why:** the repository distributes patches against GCC and binutils, which are
GPLv3 works. With no `LICENSE`, no `COPYING` and no statement of derivative-work
status, nobody may legally reuse this and the author has no clear grant.
**Done when:** the terms are stated and the obligations are met.

- [x] Add `LICENSE` (GPL-3.0-or-later, matching the patched upstreams) and a `NOTICE` naming the five upstream projects and their licences. `[C]`
  - verified-here: `ls -la LICENSE NOTICE` → 35147 bytes (the canonical GPLv3 text, byte-identical to `gcc/COPYING3`) and 2815 bytes; `NOTICE` names binutils (`binutils-2_47-branch` @ `781713d`, GPL-3.0-or-later per COPYING3), GCC (`releases/gcc-16` @ `041359f`, GPL-3.0-or-later + GFDL + Runtime Library Exception), Spike (`89c7471`, BSD-3-Clause), QEMU (`615ece3`, GPL-2.0-or-later), newlib (`cygwin/cygwin` `main` @ `06add56`, per-file per `COPYING.NEWLIB`). Measured: `binutils/bfd/elfxx-riscv.c` and `binutils/opcodes/riscv-opc.c` both say "either version 3 of the License, or (at your option) any later version" and point at COPYING3.
- [ ] `CONTRIBUTING.md`: DCO sign-off, the patch-series format, and the rule that a semantic change updates `docs/spec.md` and the golden vectors together. `[C]`
- [ ] SPDX headers on the files this project owns (`include/`, `scripts/`, `tests/`, `tools/`); never add headers to patched upstream files. `[C]`
- [ ] State in README which parts are original and which are derived from GPLv3 upstreams. `[C]`

### M1.4 Pin the inputs and record them

- [ ] Write the five submodule SHAs into `versions.env`; `scripts/setup.sh` asserts `git submodule status` matches before building. `[C]`
- [ ] Fix `.gitmodules`: Spike/QEMU `branch = master` invites `--remote` drift — pin the branch names to the release lines actually used, and correct the newlib remote (upstream newlib is not `cygwin/cygwin`; verify the intended source and say why). `[C]`
- [ ] `scripts/build.sh` writes `out/BUILD-INFO` (five submodule SHAs, host gcc/clang, Python, numpy, date) and `make check` copies it into the artefacts. `[C]`

### M1.5 Make the README's claims executable

Each claim gets one command; a claim without one is deleted.

- [ ] "All three executions agree bit for bit" → a test that prints the max absolute difference and asserts exact equality for the five vector shapes. `[C]`
- [ ] "Precise traps" → a test per simulator for illegal-when-disabled, misaligned descriptor, out-of-range dims, and a faulting descriptor pointer. `[C]`
- [ ] "Scheduling under every pipeline model" → assert the `attn` pattern appears in `-dp` output for the pipeline models the GCC port supports, and state which ones were checked. `[C]`
- [ ] "Replaces all five loop nests with one `.ATTN`" → assert the `.ATTN` count in the generated assembly for `demo/mha_plain.c` at `-O2`, before and after. `[C]`
- [ ] "About 15 minutes on 16 cores" → record the measured wall time and core count in `docs/build-and-test.md` from the CI run, not from memory. `[C]`

### M1.6 Patch-series hygiene

- [ ] `scripts/patches.sh check`: every patch applies with `git apply --check` against the pinned SHA and re-applies idempotently. `[C]`
- [ ] Patches carry `git format-patch` headers (author, date, subject, body with rationale and upstream status). `[C]`
- [ ] Record in each patch header which upstream review list it targets and whether it was submitted. `[C]`
- [ ] `scripts/xattn.sh remove` asserts a clean tree afterwards; add the negative test (remove twice fails cleanly). `[C]`

---

## Phase 2 — Preventive

### M2.1 Upstream drift detection

**Why:** the patches target branch heads (`binutils-2_47-branch`,
`releases/gcc-16`) that move weekly. Today the pinned SHA hides drift until
someone bumps it and the series stops applying.
**Done when:** a scheduled job reports, without human work, whether the series
still applies to current upstream.

- [ ] Weekly job: fetch the five upstream branches, `git apply --check` the series against each head, and open an issue with the exact failing hunk when it breaks. `[P]`
- [ ] Publish a compatibility table (patch series × upstream branch × tested SHA) in `docs/build-and-test.md`, generated by that job. `[P]`
- [ ] Bump procedure in `CONTRIBUTING.md`: rebase series, re-run full CI, update `versions.env`, update the table. `[P]`

### M2.2 Robustness of the instruction against hostile descriptors

**Why:** `attn` reads two host structures (`attn_weights`, `attn_cfg`) and
writes a matrix. A malformed descriptor in either simulator must trap, never
read or write out of bounds.
**Done when:** a fuzz run finds no out-of-bounds access and no crash.

- [ ] Enumerate the descriptor fields and the legal ranges in `docs/spec.md`; assert each bound in `attn_core.h` with a trap. `[P]`
- [ ] Fuzz `attn_cfg`/`attn_weights` on the host model with libFuzzer (ASan+UBSan); commit the seed corpus and any crash input as a regression test. `[P]`
- [ ] Test denormals, NaN, ±Inf, and each `in_dtype`/`out_dtype` combination; write the required behaviour in the spec and assert it. `[P]`
- [ ] Assert softmax ties and all-masked rows behave as specified (uniform or zero, whichever the spec says), with a test per case. `[P]`
- [ ] ASan and UBSan builds of `tests/host/attn_host.c` in CI, `-ffp-contract=off` to keep results stable across compilers. `[P]`

### M2.3 Golden vectors

- [ ] Freeze a vector set (input, weights, config, expected output hash) per dtype and per feature (causal, additive mask, GQA, explicit scale) under `tests/vectors/`. `[P]`
- [ ] Any change to `attn_core.h` that moves a hash fails the test and requires an explicit re-freeze commit with the reason. `[P]`
- [ ] Version the vector file format so an old vector stays readable. `[P]`

### M2.4 Python and script hygiene

- [ ] `pyproject.toml` with pinned `numpy`, `pytest`; a lockfile; `pip install -e .` replaces the ad-hoc venv step. `[P]`
- [ ] `ruff` and `mypy` on `scripts/` and `tools/`; blocking. `[P]`
- [ ] `shellcheck` on every `scripts/*.sh`; all scripts already use `set -euo pipefail` — assert that in a test. `[P]`
- [ ] Every script gets `--help` and a non-zero exit on unknown flags. `[P]`

### M2.5 Build reproducibility

- [ ] Two builds from one commit in the same container produce identical toolchain and simulator binaries, or the differences are listed and explained. `[P]`
- [ ] Container image (Dockerfile or devcontainer) with the toolchain prerequisites and a digest recorded in `docs/build-and-test.md`. `[P]`
- [ ] `make check` fails if `out/BUILD-INFO` is missing or older than the patches. `[P]`

---

## Phase 3 — Perfective

### M3.1 One source of versions and inputs

**Why:** upstream branches, Python deps and the base image are pinned in three
places, so a rebuild months later is not the same build.
**Done when:** every script reads `versions.env` and the file is committed.

- **m3.1.1 Inputs**
  - [ ] Single `versions.env` for upstream branches, Python deps and base image; every script reads it. `[F]`
  - [ ] GCC to the current release branch, binutils to the current release branch, Spike and QEMU to tagged releases rather than `master`; re-run the full suite and record the result. `[F]`
- **m3.1.2 Dependency pinning**
  - [ ] Replace the unpinned `pip install numpy pytest` (`Makefile:21-24`) with a hashed requirements file. `[F]`

### M3.2 Faster, incremental builds

**Why:** a full build is ~15 minutes on 16 cores, and a QEMU-only change rebuilds
GCC.
**Done when:** per-step targets exist and cold/warm times are published.

- **m3.2.1 Build speed**
  - [ ] `ccache` wired into `scripts/build.sh`; publish cold and warm build times. `[F]`
- **m3.2.2 Granularity**
  - [ ] Split `build.sh` into per-step targets with independent `make build-binutils`, `build-gcc`, … so a QEMU-only change does not rebuild GCC. `[F]`
  - [ ] Replace the shell orchestration with `make` targets where the shell adds nothing; keep the shell for environment probing. `[F]`

### M3.3 Code shape and generated artefacts

**Why:** `attn_core.h` mixes configuration macros with kernels, `xinsn.py` is one
file, and `artifacts/` is hand-collected.
**Done when:** each has a boundary and a producer command.

- **m3.3.1 C header**
  - [ ] `include/attn_core.h`: split macro-heavy sections (`ATTN_*` configuration) from the numeric kernels; keep it header-only and C89-clean for the simulators. `[F]`
- **m3.3.2 Python**
  - [ ] `scripts/xinsn.py` split into modules (spec parse, encoding allocation, tree edit, test build) with the tests from M1.2 as the net. `[F]`
- **m3.3.3 Artefacts and docs**
  - [ ] Regenerate `artifacts/` from a CI run instead of committing hand-collected files; every file gets a "produced by <command> at <sha>" line. `[F]`
  - [ ] Documentation: one entry point (`docs/INDEX.md`) mapping each doc to the claims it supports and the test that proves it. `[F]`

---

## Phase 4 — Widening

### M4.1 Prove the general method with a second instruction

- [ ] Ship a second worked example end to end (a small, non-attention instruction such as `mac` or a RoPE step) as `examples/<name>.spec` plus a demo, with its own tests in `make check`. `[W]`
- [ ] `xinsn.py list --json` for tooling, and `xinsn.py verify SPEC` that checks a spec without touching the trees. `[W]`
- [ ] Templates: `xinsn.py new --template elementwise|reduction|memory` prefilled specs. `[W]`
- [ ] Document the failure modes of the method (encoding exhaustion per major opcode, conflicts with other vendor extensions, attribute naming). `[W]`

### M4.2 Recognizer coverage

- [ ] Add patterns for the transformer ops next to attention (standalone softmax, RoPE, layer norm) as separate recognitions with their own tests. `[W]`
- [ ] Recognition report on a real code base: which loops were recognised, which were not, and why — a table with per-file counts. `[W]`
- [ ] `-fno-attn` and a per-function attribute to opt out; test both. `[W]`
- [ ] Cost model: publish the runtime guard cost when the instruction is absent. `[W]`

### M4.3 Portability of the instruction

- [ ] RV32: full test coverage (the spec says valid on RV32 and RV64; prove it on both simulators for every vector). `[W]`
- [ ] Vector (V) variant or a documented reason not to; if done, a separate extension name and spec version. `[W]`
- [ ] Cross-check against a third implementation (QEMU TCG vs Spike interpreter already differ; add a scalar reference build of `attn_core.h` compiled for the host as the third). `[W]`

### M4.4 Teaching surface

- [ ] `docs/study.md` exercises get checked answers, one per stage. `[W]`
- [ ] A single walkthrough that adds a toy instruction from scratch in under 30 minutes, tested by CI on a scratch tree. `[W]`
- [ ] Publish the artefacts report as static HTML (no build step) with tables generated from the JSON results. `[W]`

---

## Phase 5 — Depth

### M5.1 Correctness depth

- [ ] Randomised differential testing: 1,000 random shapes, dtypes, head counts, mask types and scales against `tools/attn_model.py`; report failures by category. `[D]`
- [ ] State the tolerance derivation once (float32 accumulation order, bf16 input rounding) in `docs/theory.md`, and use it everywhere instead of per-test magic numbers. `[D]`
- [ ] Accumulation-order analysis: prove the spike, QEMU and host paths sum in the same order, or make the order explicit in `attn_core.h` and assert it. `[D]`
- [ ] Boundary shapes: n=1, e=1, heads=1, head_dim=1, n>cache, empty mask, maximum dims from the descriptor fields. `[D]`
- [ ] Cross-compiler stability: the same vectors under GCC and Clang at `-O0/-O2/-O3 -ffp-contract=off` must match. `[D]`

### M5.2 Performance depth

- [ ] Measure `attn` against the plain C loop on both simulators: retired instructions and simulated cycles per shape, in a table with the method stated. `[D]`
- [ ] Measure the speedup on real hardware only if a board is available; otherwise say clearly that no silicon number exists. `[D]`
- [ ] Estimator: model the cycle cost from the descriptor (n, e, heads) and publish the error against measurement. `[D]`
- [ ] Recognizer cost: `.ATTN` replacement vs the original loops at `-O2`, per file in the corpus. `[D]`

### M5.3 Recognizer quality

- [ ] Precision and recall of loop recognition over a labelled corpus (≥30 attention implementations from real projects); report false positives with the guard cost. `[D]`
- [ ] Robustness: loops with early exits, aliasing, non-contiguous strides, and mixed precision must be rejected, not mis-recognised. `[D]`
- [ ] State the recognised pattern formally in `docs/recognizer.md` as a grammar, and test that the implementation matches it. `[D]`

### M5.4 CLI and artefact craft

Method: `design-ux` §1 principles applied to a CLI — one job per command, output
that a machine can read, failures that name the fix.

- [ ] `scripts/attncc.sh --run` prints one line per stage (extract, compile, assemble, run, compare) with a pass/fail marker. `[D]`
- [ ] `xinsn.py` output: dry-run diff preview, colour only on a TTY, `--json`, and an exit code that distinguishes "spec invalid" from "build failed". `[D]`
- [ ] `make check` summary table at the end: target, pass, fail, time; non-zero exit on any failure. `[D]`
- [ ] Error messages name the file, line and fix for the five most common build failures (missing package, patch conflict, submodule not initialised, stale toolchain, wrong `-march`). `[D]`

---

## Phase 6 — Enterprise

### M6.1 Spec governance

**Why:** the encoding is normative and has no version discipline.
**Done when:** a semantic change cannot land without a version bump and a re-frozen vector set.

- **m6.1.1 Versioning**
  - [ ] `docs/spec.md` versioned with a changelog; a semantic change requires a new version, a vector re-freeze and a compatibility note. `[E]`
- **m6.1.2 Releases**
  - [ ] Tags per spec version, a source archive, the matching `BUILD-INFO`, and the vector set as the release's evidence. `[E]`

### M6.2 Upstream and contribution

**Why:** five forks and no submission package means the work stays unmergeable.
**Done when:** a reviewer can apply and test the series from the cover letter alone.

- **m6.2.1 Submission package**
  - [ ] Each patch with a commit message in the project's style, a cover letter, and a documented test plan a reviewer can run. `[E]`
- **m6.2.2 Ownership**
  - [ ] `CODEOWNERS` for `patches/`, `include/`, `scripts/`; a review checklist for anything touching `attn_core.h` (spec, vectors, all three executions). `[E]`

### M6.3 Operability and long-term cost

**Why:** a build failure has no first diagnostic, and the maintenance cost is unstated.
**Done when:** the runbook exists and the cost is written down.

- **m6.3.1 Runbook and security**
  - [ ] `docs/RUNBOOK.md`: build fails at each step, patch conflict, submodule drift, simulator aborts, vector mismatch — each with the first diagnostic command. `[E]`
  - [ ] `SECURITY.md`: how to report a simulator bug (a mis-executed instruction is a security issue in an emulator) and the response window. `[E]`
- **m6.3.2 Support matrix**
  - [ ] Host OS, GCC/Clang, Python, disk and time budget for a full build; CI enforces what it can. `[E]`
- **m6.3.3 Honest cost**
  - [ ] Cost of maintaining five forks stated (hours per upstream release), with the option to upstream the extension and drop the forks. `[E]`

---

## 7. Execution model: waves, effort, exit gates

Effort: **S** ≤ 1 day, **M** 2–3 days, **L** 1–2 weeks (build time dominates).

| Wave | Days | Objective | Majors | Effort | Gate |
|---|---|---|---|---|---|
| **W0** | 3–4 | Licence, CI, and a test for the method | M1.1–M1.3 | M+M+S | `LICENSE` + SPDX headers exist; a workflow runs `make check`; `scripts/xinsn.py` has a test |
| **W1** | 4–5 | Pinned inputs, executable README, patch hygiene | M1.4–M1.6 | M+S+M | every input is pinned in `versions.env`; every README claim maps to a `make` target; a patch reorders/applies cleanly from scratch |
| **W2** | 6–7 | Drift detection, hostile-input robustness, vectors | M2.1–M2.5 | M+M+M+M+M | an upstream bump produces a named failure; a hostile encoding traps in both simulators |
| **W3** | 8–9 | Versions, build speed, code shape | M3.1–M3.3 | M+M+M | cold/warm build times published; QEMU-only change does not rebuild GCC |
| **W4** | 10–12 | Second instruction, recognizer coverage, portability | M4.1–M4.4 | L+M+M+M | the general method produces a second working instruction end to end |
| **W5** | 13–15 | Correctness, performance, recognizer quality | M5.1–M5.4 | M+M+M+M | benchmarks and vector tables generated, not typed |
| **W6** | quarter | Governance, submission, runbook | M6.1–M6.3 | M | a reviewer can apply the series from the cover letter alone |

Wave rules: W0's licence work is not optional while shipping GPLv3 derivative
patches. W2 gates W4: a general method without hostile-input tests is a demo.

---

## 8. Dependencies and the critical path

```
M1.3 (licence)        → M6.2 (submission package)
M1.1 (CI)             → every gate after it
M1.2 (xinsn test)     → M3.3.2 (xinsn split) → M4.1 (second instruction)
M1.4 (pinned inputs)  → M3.1 (versions)      → M2.5 (reproducible build)
M2.3 (vectors)        → M5.1 (correctness depth) → M6.1 (spec governance)
```

Critical path: **M1.2 → M4.1**. The project's claim is a general method; until
`xinsn.py` has a test and a second instruction is produced by it, that claim rests
on one hand-built example.

Do not start: M4.1 before M1.2 (generality without a test is a story); M3.3.2
before M2.4 (splitting untested script code); M6.1 before M2.3 (governance without
frozen vectors has nothing to govern).

---

## 9. Verification harness (commands that exist today)

| Purpose | Command | Status |
|---|---|---|
| Full check | `make check` = `check-core check-gcc check-sim check-recog` | exists (`Makefile:21`) |
| Host model test | `make check-core` (pytest vs float64 model) | exists |
| Compiler test | `make check-gcc` (dg files) | exists |
| Simulator test | `make check-sim` (bare metal on Spike and QEMU) | exists |
| Recognizer test | `make check-recog` (runtime loop recognition) | exists |
| Build | `scripts/build.sh` (six steps, ~15 min / 16 cores) | exists |
| Patch apply/remove | `scripts/xattn.sh`, `scripts/patches.sh` | exists |
| Artefacts | `scripts/artifacts.sh` | exists |
| **CI** | — | **missing** (M1.1) |
| **`xinsn.py` test** | — | **missing** (M1.2) |
| **Pinned Python deps** | `Makefile:21-24` installs `numpy pytest` unpinned | **missing** (M3.1.2) |

---

## 10. Risk register

| # | Risk | Prob | Impact | Detection | Mitigation |
|---|---|---|---|---|---|
| R1 | No licence while shipping GPLv3-derived patches | High | Legal exposure | `ls LICENSE` → absent | M1.3 |
| R2 | No CI, so the suite is only run by hand | High | Silent breakage | `ls .github` → absent | M1.1 |
| R3 | The general method (`xinsn.py`) has no test | High | Unverifiable claim | `grep -rln xinsn tests` → none | M1.2 |
| R4 | Spike/QEMU track `master` | Med | Reproducibility | `.gitmodules` | M3.1 |
| R5 | Unpinned numpy/pytest | Med | Rebuild drift | `Makefile:21-24` | M3.1.2 |
| R6 | Patches bit-rot against upstream | High | Build failure | manual | M2.1 drift detection |
| R7 | Hostile encoding not tested in both simulators | Med | Emulator security bug | none | M2.2 |
| R8 | Hand-collected `artifacts/` | Med | Stale evidence | `git ls-files artifacts` | M3.3.3 |
| R9 | Five forks cost unbounded maintenance | High | Abandonment | unstated | M6.3.3 |
| R10 | No runbook: a build failure has no first diagnostic | Med | Hours lost | absent | M6.3.1 |

---

## 11. PR batching and rollback

| Batch | Contents | Rollback |
|---|---|---|
| B1 | `LICENSE` + SPDX headers | revert (headers are comments) |
| B2 | CI workflow + cache | revert workflow |
| B3 | `xinsn.py` test + refactor | revert test first, then refactor |
| B4 | `versions.env` + scripts reading it | revert file; pins return to inline |
| B5 | per-step build targets | revert Makefile |
| B6 | regenerated `artifacts/` | revert directory |

Rollback rules: patches are the only delta, so `scripts/xattn.sh remove` must always
restore a pristine tree — a rollback that leaves the submodules dirty is a bug
(M1.6). Spec changes bump the version (M6.1).

---

## 12. Progress metrics

| Metric | Now (measured) | W2 | W4 | How measured |
|---|---|---|---|---|
| Tracked files | 74 | + CI, licence, vectors | + second instruction | `git ls-files \| wc -l` |
| Licence files | 0 | 1 + headers | 1 | file existence |
| CI workflows | 0 | 1 | 1+ | `.github/workflows` |
| Patches | 9 (binutils 1, GCC 4, QEMU 2, Spike 2) | + hygiene test | + second instruction | `find . -name '*.patch'` |
| `make check` steps | 4 | + drift + hostile | + second instruction | `Makefile` |
| Pinned inputs | inline, 3 places | 1 file | 1 file | `versions.env` |
| Build time (cold/warm) | ~15 min (doc) | measured | improved | `scripts/build.sh` output |

---

## Appendix A — Blocked on the owner

- Hardware numbers: no RISC-V board is available, so every performance claim stays simulator-based until one is.
- Upstream submission decision: whether to send the series to binutils/GCC/Spike/QEMU review lists, and under whose name.
- newlib source: confirm the intended upstream (the current submodule points at `cygwin/cygwin`).
- QEMU and Spike branch policy: tag-pinned or `master`-tracking.

## Appendix B — Definition of done

1. The failing case exists as a test before the fix; a semantics change also re-freezes the golden vectors.
2. `make check` green, or the full CI job green, with the output pasted; the five submodule SHAs recorded.
3. No invariant in §0 broken: one definition in `attn_core.h`, bit-exact agreement, normative encoding, illegal when disabled, clean `remove`, pinned inputs.
4. `docs/spec.md` updated for any semantic change; the README claim updated or removed with the command that proves it.
5. Licence headers present on original files; no header added to upstream-derived patches.

## Appendix C — Evidence ledger

| Claim | Command | Result | Status |
|---|---|---|---|
| 74 tracked files | `git ls-files \| wc -l` | 74 | verified-here |
| No licence / COPYING / CONTRIBUTING | `ls LICENSE COPYING CONTRIBUTING` | none | verified-here |
| No CI | `ls -a \| grep .github` | absent | verified-here |
| 9 patches | `find . -name '*.patch' \| wc -l` | 9 | verified-here |
| Four check targets | `grep -nE '^check' Makefile` | check, check-core, check-gcc, check-sim, check-recog | verified-here |
| `xinsn.py` exists, untested | `find . -name 'xinsn*'`, `grep -rln xinsn tests` | `scripts/xinsn.py`; no test reference | verified-here |
| 5 submodules + scripts | `ls` | binutils, gcc, newlib, qemu, spike, scripts, patches, include | verified-here |
| Unpinned Python deps | `sed -n '21,24p' Makefile` | `pip install -q numpy pytest` | verified-here |
| Submodule SHAs and "current upstream" | `git submodule status` (not re-run here) | needs-verify | needs-verify |
| "~15 min on 16 cores" | README / script header | doc claim | needs-verify |
| "all three agree bit for bit" | `make check-sim` not run here | needs-verify | needs-verify |

---

## 13. Journal

- 2026-11-24 m1.1.1 [x] fast CI job | proof: `python3 -m pytest -q tests/` → 32 passed in 3.90s; `shellcheck -x scripts/*.sh` → exit 0; `actionlint` → no findings | next: m1.1.2
- 2026-11-24 m1.2.1 [x] xinsn.py show/encoding/file-list test | proof: `python3 -m pytest -q tests/test_xinsn.py` → 3 passed | next: m1.2.2
- 2026-11-24 m1.2.2 [x] apply/idempotence/remove round trip on a scratch tree | proof: `python3 -m pytest -q tests/test_xinsn.py` → 5 passed; `remove mac --no-rebuild` → `git status --porcelain` empty | next: m1.2.3
- 2026-11-24 m1.2.3 [x] encoding safety | proof: `python3 -m pytest -q tests/test_xinsn.py` → 7 passed; 5 examples applied in turn → 5 distinct encodings | next: m1.2.4
- 2026-11-24 m1.2.5 [x] spec validation + 8 failure-path tests | proof: `python3 -m pytest -q tests/test_xinsn.py` → 15 passed in 157.45s | next: m1.2.4
- 2026-11-24 m1.2.4 [x] generated instruction on QEMU and Spike (slow job) | proof: `make check-xinsn-sim` under the hood → `qemu mac: all checks passed`, `spike mac: all checks passed`, `objdump: 1 mac instruction(s)`; pytest → 1 passed | deviation: qemu binary built in a py3.12 container (pinned QEMU needs Python≥3.12) | next: m1.1.2
- 2026-11-24 m1.1.2 [x] full CI job (build + make check + artefacts) | proof: `make check` → exit 0 in 97s; `scripts/patches.sh apply` → 7.8s; `actionlint` → no findings | needs-verify: not yet run on a GitHub runner | next: m1.1.3
- 2026-11-24 m1.1.3 [x] toolchain cache by patch SHA + validation before use | proof: cache set compresses to 810 MB; validation `gcc 16.2.1 -march=rv64gc_xattn` + `as` accepts `attn`; without the extension → `extension 'xattn' required` | next: m1.1.4
- 2026-11-24 m1.1.4 [x] CI badges + SHAs artefact | proof: README badges; `full.yml` → `build/CI-TRACE.txt` with pinned vs checked-out SHAs (5 submodules) + versions; `actionlint` clean | next: m1.3.1
- 2026-11-24 m1.3.1 [x] LICENSE (GPLv3) + NOTICE with the five upstreams | proof: `ls -la LICENSE NOTICE` → 35147 + 2815 bytes; byte-identical to gcc/COPYING3 | next: m1.3.2
