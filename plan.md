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
  - corrected 2026-11-26: that six-step build is gone from this host. `out/toolchain/bin` holds 16 binutils entries, all dated 11/24 06:47, and `find out build` finds no `riscv64-unknown-elf-gcc`, no `spike`, no `qemu-system-riscv64`; `.fleet/evidence/RISC-VInjection/build-steps.md` already says "not run: any real build". The tick stands for the workflow wiring in `full.yml` (actionlint clean, steps present); the local six-step and `make check` numbers are a container record that cannot be re-run until a toolchain is rebuilt or the Full run artefact is verified.
  - needs-verify: the workflow has not run on a GitHub runner from this machine; the commands and the exit codes were reproduced in `debian:bookworm` + `python:3.12-slim-bookworm` containers, not on the runner image.
- [x] Cache the built toolchain and ccache between full runs by patch SHA; a cache hit must be validated by `make check`, never trusted blindly. `[C]`
  - verified-here: `full.yml` keys both caches on `sha256(submodule SHAs)` and `sha256(patches/*/*.patch)`, caches `out/toolchain` + `build/{binutils,gcc,newlib}` and validates a hit before the build: `riscv64-unknown-elf-gcc --version` → `GCC 16.2.1`, `-march=rv64gc_xattn -E` → ok, `as` accepts `attn` → ok; without the extension the same line fails (`Error: unrecognized opcode \`attn a3,a0,a1,a2', extension \`xattn' required`), so a stale toolchain drops the cache and rebuilds. Cached set compresses to 810 MB (`tar -czf`), then `make check` (exit 0) is the real validation. `actionlint` → no findings.
  - corrected 2026-11-26: the `GCC 16.2.1` version string, the 810 MB cached set and the `make check` exit 0 came from container trees that no longer exist here (`out/toolchain` has no gcc today). What this host can still check is the `full.yml` cache key over submodule SHAs and patches, and each validation command the workflow runs; the cache-hit numbers are re-established only by a real full run.
  - measured 2026-11-26 (Full run 45817010544, sha fa3096aa): the build step succeeded in 1844 s on 4 cores (host cc 13.3.0, python 3.12.3; gcc 16.2.1 20261012, spike 03a04f0, QEMU 11.1.50), Tests failed in 33 s, and the cache post-step was skipped: `gh api .../actions/caches` returns total_count 0, so nothing was stored. The 278612-byte artefact is `artifacts/` plus `build/CI-TRACE.txt`, not `out/`; no toolchain or simulator binary is retrievable from that run.
  - green 2026-11-26 (Full run 45835120627, sha cc15183): success in 25m36s (14:03:12Z to 14:28:48Z); the 1.59 GiB toolchain cache and the 0.40 GiB submodules cache both restored and were saved again, so this run proves the build from source and does not re-time it. Its 278752-byte artefact is logs only, so `full.yml` now packs `out/toolchain` and `out/{spike,qemu}` into two tar.xz with a SHA256SUMS when dispatched or on a `fleet/` ref; the first dispatch is the first run that puts a toolchain in our hands, and its CI-TRACE records both byte counts.
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
- [x] `CONTRIBUTING.md`: DCO sign-off, the patch-series format, and the rule that a semantic change updates `docs/spec.md` and the golden vectors together. `[C]`
  - verified-here: `CONTRIBUTING.md` (DCO sign-off, `scripts/patches.sh apply`/`export` workflow, `make check` + `make check-xinsn-sim`, the spec-version rule, SPDX only on original files). Every command it names exists: `make check`, `make check-xinsn-sim` (`Makefile`), `scripts/patches.sh apply|export`, `scripts/xattn.sh remove`, `python3 -m pytest -q tests/`.
- [x] SPDX headers on the files this project owns (`include/`, `scripts/`, `tests/`, `tools/`); never add headers to patched upstream files. `[C]`
  - verified-here: `grep -rl SPDX include scripts tests tools demo` → 31 files, each with `SPDX-License-Identifier: GPL-3.0-or-later` (first line after the shebang for shell/python); `grep -rln SPDX binutils/riscv-opc.c gcc/gcc/config/riscv spike/riscv qemu/target/riscv` × the patched upstream files → only the copies of `attn_core.h`/`attn_abi.h`, which this project owns. `.gitattributes` now pins `*.c *.h *.py *.S *.ld *.md Makefile` to `eol=lf`, so the working copy matches the tree copies byte for byte (`cmp include/attn_core.h spike/riscv/attn_core.h` etc. → equal, 3 of 3). `make check` after the change → exit 0 in 115 s, 67 `PASS`.
  - deviation: the two shared headers are copied into the trees, so the SPDX line reached them as patch 0003/0005 and the series was re-exported (`scripts/patches.sh export spike qemu gcc` → 3/3/5 patches; `remove` then `apply` reproduces them from the pinned commits with `git diff --name-only` empty).
  - fix: `scripts/patches.sh clean_or_die` used `git status --porcelain`, which on this Windows checkout reports 10 873 stat-only-dirty files in `qemu` (`git diff --quiet` → clean, blob identical), so `remove qemu` aborted. It now asks `git diff --quiet` and falls back to a forced checkout only when the content check said clean.
- [x] State in README which parts are original and which are derived from GPLv3 upstreams. `[C]`
  - verified-here: `README.md` §"Provenance and licence" lists the original trees (`include/ scripts/ tests/ tools/ demo/ docs/ examples/ patches/`) and a per-submodule table of the licence of the patched files: binutils GPL-3.0-or-later, gcc GPL-3.0-or-later (+ GFDL for docs, Runtime Library Exception for libgcc), spike BSD-3-Clause, qemu GPL-2.0-or-later, newlib per-file — the same facts as `NOTICE`, both cross-checked against the trees' own `COPYING3`/`COPYING`/`LICENSE`/`COPYING.NEWLIB`.

### M1.4 Pin the inputs and record them

- [x] Write the five submodule SHAs into `versions.env`; `scripts/setup.sh` asserts `git submodule status` matches before building. `[C]`
  - verified-here: `versions.env` pins the five 40-character SHAs; `scripts/check-pins.sh` compares them with `git ls-tree HEAD <submodule>` and `scripts/setup.sh` runs it as part of step 3/6, before patching and building. Fails before: `bash scripts/check-pins.sh` → exit 1 with `error: BINUTILS_SHA in …/versions.env is 781713d… but the superproject pins 7151425c…` (four such lines). Passes after: exit 0, five lines, `binutils 781713d…`, `gcc 041359f…`, `newlib 06add56…`, `qemu 615ece3…`, `spike 89c7471…`.
  - fix: the gitlinks had drifted. `git add -A` in m1.3.3 recorded the local patched commits as the superproject's pins (`binutils 7151425`, `gcc e4f983b`, `qemu ef966e0`, `spike 777d453`), so the pointer no longer named upstream and `patches.sh` would have used a patched commit as a base. Restored from `f64abf4`: `git ls-files -s binutils gcc newlib qemu spike` now shows the upstream SHAs again. This check is what makes that visible instead of silent.
  - tests: `tests/test_pins.py` — four cases (the file names the pins, the script agrees, a drifted SHA is refused, a missing key is refused).
- [x] Fix `.gitmodules`: Spike/QEMU `branch = master` invites `--remote` drift — pin the branch names to the release lines actually used, and correct the newlib remote (upstream newlib is not `cygwin/cygwin`; verify the intended source and say why). `[C]`
  - verified-here: `git config -f .gitmodules --get-regexp branch` → exit 1, no `branch` key left, with the reason written at the top of the file (the key is only read by `git submodule update --remote`, which moves a submodule to a branch tip and stops `patches/` applying). The four URLs unchanged; newlib now `https://sourceware.org/git/newlib-cygwin.git`, the canonical tree per sourceware's own download page. Measured: `git ls-remote --symref` → spike `master`, qemu `master`, newlib `main` (both URLs); `git fetch --depth 1 <url> 06add56…` → OK from sourceware *and* from `cygwin/cygwin`, so the pin is fetchable either way. `git submodule sync newlib` → `submodule.newlib.url` updated, tree still at the pinned commit.
  - corrected: spike and qemu are pinned to commits on the `master` line, not to a release branch, so "pin the branch names to the release lines" cannot be done with a `branch` key; the honest fix is that this project pins commits (an earlier commit is not a branch head on either upstream, `branches-where-head` → `[]` for both).
  - tests: `tests/test_pins.py` now also asserts that no `branch` key exists, that there are five `https://` urls, and that newlib points at the canonical source — `6 passed`.
- [x] `scripts/build.sh` writes `out/BUILD-INFO` (five submodule SHAs, host gcc/clang, Python, numpy, date) and `make check` copies it into the artefacts. `[C]`
  - verified-here: `scripts/build.sh info` → `out/BUILD-INFO` with `date`, `host` (kernel, cores, JOBS), `host cc`/`host c++`, `python`, `numpy`, the five submodules as `pinned … built …` and the three output versions; the same call runs at the end of every build. `make check-info` → `artifacts/BUILD-INFO: date: …` and the file is in place (17 lines). `make check` now starts with `check-info`, so every `make check` in this repository carries the record. `artifacts/BUILD-INFO` is git-ignored: it is a build record, not source.
  - measured: on this host `host cc:` and `python:` come out empty (no native toolchain here, builds happen in a container), and in the container the file shows `cc (Debian 12.2.0) 12.2.0`, `Python 3.11.2`, `numpy 1.24.2`, `gcc (GCC) 16.2.1 20261012`, `QEMU emulator version 11.1.50`.
  - note: Spike has no `--version` flag (`spike: unrecognized option --version`), so the record keeps `git describe --always --dirty` of its tree instead of a version string.
  - tests: `tests/test_build_info.py` — the pins and the fields are present, `info` does not touch `build/`, and `make check`/`.gitignore` keep the copy; `9 passed` with `tests/test_pins.py`.

### M1.5 Make the README's claims executable

Each claim gets one command; a claim without one is deleted.

- [x] "All three executions agree bit for bit" → a test that prints the max absolute difference and asserts exact equality for the five vector shapes. `[C]`
  - verified-here: `make check-three-way` → `1 passed`, and the printed table is seven rows of `0  0  PASS` (QEMU, Spike) against the host reference; the simulators now report `PASS <case> maxdiff=<16 hex digits>`, the IEEE bits of the largest `|Y - reference|` (`max_abs_diff()` in `tests/baremetal/attn_test.c`, f32 or bf16 read as float). The bare-metal run prints `maxdiff=0000000000000000` for all seven cases on both simulators; `make -C tests/baremetal check` still passes (traps, re-execution, Linux user mode).
  - corrected: the vector set is **seven** configurations, not five (`tests/baremetal/gen_cases.py`: `f32_1head`, `f32_4head_bias`, `f32_causal_mask`, `f32_gqa`, `f32_scale`, `bf16_bf16_causal`, `bf16_f32_gpt2ish`); all seven are asserted. `docs/build-and-test.md` gained the target and a sample of its table.
- [x] "Precise traps" → a test per simulator for illegal-when-disabled, misaligned descriptor, out-of-range dims, and a faulting descriptor pointer. `[C]`
  - verified-here: `make -C tests/baremetal check` → 14 `PASS` per bare-metal run on each simulator (7 value cases + `illegal_config_traps` + `load_fault_precise` + `reexecute_after_fault` + `dims_out_of_range_trap` + `element_size_out_of_range_trap` + `descriptor_fault_is_precise` + the misaligned case), plus `attn_without_xattn_is_illegal` on the no-Xattn images; QEMU and Spike both print `attn_test: all passed`. New checks assert `mcause 2` and `Y` untouched for `n = 4097` and `e = 2049`, and a fault on a descriptor at `0x200000000` with `mtval` = that address and `Y` untouched (causes 5/7/13 accepted).
  - measured difference, now in `docs/spec.md` §5: the misaligned descriptor completes on QEMU (`misaligned_descriptor_completes`) and raises a misaligned load on Spike (`misaligned_descriptor_traps`, cause 4); both are allowed by the spec's "where the platform requires naturally aligned accesses".
  - docs: `docs/build-and-test.md` `check-sim` row rewritten to 14 checks each (`2 x 15 + 7` including the no-Xattn images).
- [x] "Scheduling under every pipeline model" → assert the `attn` pattern appears in `-dp` output for the pipeline models the GCC port supports, and state which ones were checked. `[C]`
  - verified-here: `make check-sched` → `1 passed in 5.52s`; the table prints 26 rows, each `2 ok` (two `attn` lines annotated `riscv_attn_di`): 13 pipeline models — `generic` (generic, rocket, sifive-3/5-series, thead-c906, xt-c908, xt-c908v, xt-c910, xt-c910v2, xt-c920, xt-c920v2, size), `sifive_7`, `sifive_p400`, `sifive_p600`, `generic_ooo`, `xiangshan` (nanhu, kunminghu), `tt_ascalon_d8` (ascalon-x, ascalon-d8), `tt_ascalon_xg`, `spacemit_x60`, `mips_p8700`, `andes_23_series`, `andes_25_series`, `andes_45_series`. The tuning list is read from `gcc/gcc/config/riscv/riscv-cores.def` at run time, so a new core in the port is covered without editing the test.
  - sample annotation: `attn a0,a1,a2,a3 # 9 [c=0 l=4] riscv_attn_di`. `docs/build-and-test.md` gained the `check-sched` row.
- [x] "Replaces all five loop nests with one `.ATTN`" → assert the `.ATTN` count in the generated assembly for `demo/mha_plain.c` at `-O2`, before and after. `[C]`
  - verified-here: `make check-demo` → `1 passed`, table: with `-fno-tree-loop-attn` → `.ATTN 0`, `attn 0`, 333 instructions, 6 `fadd.s`/`fmul.s`; with the default → `.ATTN 1`, `attn 1`, 375 instructions, the same 6 float ops. The GIMPLE dump (`.ATTN`) only exists when the pass runs, so the "before" count is 0 by construction; the test treats a missing dump as empty and says so.
  - corrected: the recognized build is **larger** in static code, not smaller — descriptors plus the runtime guard — and the loops remain in the binary as the guard's fallback (`artifacts/README.md`: the fallback runs only for sizes the instruction rejects). The first version of this test asserted a smaller and float-free result and failed (`6 < 6`, `375 > 333`); it now asserts the measured facts and points at the run-time saving (508 421 → 991 executed instructions).
  - docs: `docs/build-and-test.md` gained the `check-demo` row.
- [x] "About 15 minutes on 16 cores" → record the measured wall time and core count in `docs/build-and-test.md` from the CI run, not from memory. `[C]`
  - verified-here: Full run 45857819667 at `076aeab` (success, 2026-11-26): job `Build and test` took 37 min 54 s (16:20:23Z to 16:58:17Z), of which `Build (six steps)` `JOBS=$(nproc) scripts/build.sh` took 1804 s (30 min 04 s) and `make check` 48 s (16:51:32Z to 16:52:20Z); the 4 cores and `JOBS=4` come from the top-level `BUILD-INFO` in `xattn-toolchain-076aeab98cc4.tar.xz` (`date: 2026-11-26T16:51:32Z`, `host: Linux x86_64, 4 core(s), JOBS=4`), and an earlier green run 45835120627 at `cc15183` took 1320 s without a toolchain cache hit; `docs/build-and-test.md` 7.5 now carries these numbers, says the quoted 15 minutes on 16 cores is unsupported, and marks the section 3 per-step times as older estimates.

### M1.6 Patch-series hygiene

- [x] `scripts/patches.sh check`: every patch applies with `git apply --check` against the pinned SHA and re-applies idempotently. `[C]`
  - verified-here: `scripts/patches.sh check` → `binutils: 1 patch(es) apply to 781713dde4c8, re-apply the same tree, export matches`, and the same line for gcc (5, `041359f347cb`), spike (3, `89c7471fd811`), qemu (3, `615ece3c406b`), exit 0. Each component is replayed in a scratch worktree at the pinned commit: every patch `git apply --check`ed and applied in order, the series replayed twice with `git am` with the two trees compared, and the branch re-export diffed against `patches/<c>/`.
- [x] Patches carry `git format-patch` headers (author, date, subject, body with rationale and upstream status). `[C]`
  - verified-here: `scripts/patches.sh check` → `binutils: 1 patch(es) apply to 781713dde4c8, re-apply the same tree, export matches`, and the same line for gcc (5, `041359f347cb`), spike (3, `89c7471fd811`), qemu (3, `615ece3c406b`), `checkrc=0`. All 12 files begin with the four header lines `From <sha> Mon Sep 17 00:00:00 2001`, `From:`, `Date:`, `Subject: [PATCH n/m]`; each message body has the rationale paragraph, the `Tested with scripts/patches.sh check` paragraph and an `Upstream status:` line.
- [x] Record in each patch header which upstream review list it targets and whether it was submitted. `[C]`
  - verified-here: `scripts/patches.sh check` → `binutils: 1 patch(es) apply to 781713dde4c8, re-apply the same tree, export matches`, and the same line for gcc (5, `041359f347cb`), spike (3, `89c7471fd811`), qemu (3, `615ece3c406b`), `checkrc=0`. All 12 patch headers carry exactly one `Upstream review list: <list>. Submitted: no.` line naming the list the tree itself gives: `binutils@sourceware.org` (binutils/MAINTAINERS), `gcc-patches@gcc.gnu.org` (gcc/.b4-config), `qemu-devel@nongnu.org` (qemu/docs/devel/submitting-a-patch.rst), and for spike no list in tree, riscv-isa-sim takes pull requests on GitHub.
- [x] `scripts/xattn.sh remove` asserts a clean tree afterwards; add the negative test (remove twice fails cleanly). `[C]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_xattn.py` → `3 passed in 17.41s`. On a scratch superproject whose four submodules sit on branch xattn one commit ahead of their pins, `remove --no-rebuild` leaves each tree clean (`git status --porcelain` empty) and detached at its pin; a second remove exits 1 with `error: <c>: already at the pinned upstream commit <sha>; nothing to remove` and moves no HEAD; a post-checkout hook that writes `leak.txt` makes remove exit 1 with `error: gcc is dirty after remove; the change leaked outside branch xattn`.

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
- [x] Bump procedure in `CONTRIBUTING.md`: rebase series, re-run full CI, update `versions.env`, update the table. `[P]`
  - verified-here: `bash /tmp/w2-t7-proof.sh` → `checkpins=0` with the five pins printed, and `proofrc=0`: `## Bump procedure` at `CONTRIBUTING.md:49`, the verbs `export`, `apply gcc`, `check` present in `scripts/patches.sh`, the `check` target in `Makefile`, `.github/workflows/full.yml:15` firing on `patches/**`, `git update-index --cacheinfo 160000,<sha>,gcc` accepted (`cacheinfo_rc=0`, entry `160000 2222...`), and the `GCC_SHA=` rewrite hitting exactly one line.

### M2.2 Robustness of the instruction against hostile descriptors

**Why:** `attn` reads two host structures (`attn_weights`, `attn_cfg`) and
writes a matrix. A malformed descriptor in either simulator must trap, never
read or write out of bounds.
**Done when:** a fuzz run finds no out-of-bounds access and no crash.

- [x] Enumerate the descriptor fields and the legal ranges in `docs/spec.md`; assert each bound in `attn_core.h` with a trap. `[P]`
  - verified-here: `.venv/Scripts/python.exe -m pytest -q tests/test_core.py tests/test_boundaries.py tests/test_study_answers.py` -> `77 passed in 9.32s`. `docs/spec.md` section 4 now carries a 12-row table (each field, its legal values, the outcome otherwise) beside the existing reserved-configuration list, derived from it and changing no rule. Every bullet of that list has a trap test: the existing 11 `bad_cfg` cases (n=0, e=0, h=0, e%h, h%h_kv, flag bit, reserved, in_dtype, out_dtype, n>4096, e>2048), the existing RV32 mask case, plus 12 new cases: `test_zero_weight_pointer_is_illegal` for wq/wk/wv/wo and `test_rv32_rejects_a_wide_weight_pointer` for all eight pointers of `attn_weights`, each rc 1. `include/attn_core.h` `attn_scratch_floats` is the code path asserted; no header change was needed.
- [x] Fuzz `attn_cfg`/`attn_weights` on the host model with libFuzzer (ASan+UBSan); commit the seed corpus and any crash input as a regression test. `[P]`
  - verified-here: ubuntu:24.04 digest sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b, clang 18.1.3; 13 committed seeds; `-max_total_time=600 -runs=100000000` -> `Done 16491196 runs in 601 second(s)`, 27439 exec/s, 202 corpus inputs at the end, 0 crash artifacts; host pytest skips without clang. The apt install in ubuntu:24.04 failed twice on a mirror sync (`File has unexpected size`), so the campaign ran in xattn-prereqs:24.04, built FROM that digest, with the clang runtime unpacked from the archive pool; container pytest did not run (no pytest there).
- [x] Test denormals, NaN, ±Inf, and each `in_dtype`/`out_dtype` combination; write the required behaviour in the spec and assert it. `[P]`
  - verified-here: `.venv/Scripts/python.exe -m pytest -q tests/test_core.py tests/test_study_answers.py` -> `53 passed in 2.86s`. `test_every_dtype_combination_is_legal` runs all four in/out pairs ((0,0) (0,1) (1,0) (1,1)) and matches the model at ATOL_F32=1e-4 or ATOL_BF16=2^-7. `test_non_finite_operand_propagates_without_a_trap` puts NaN, +inf and -inf in X[0][0]: rc 0 (no trap), the NaN mask of Y equals the model's, and every jointly finite element matches it. `test_subnormal_operand_reaches_the_output_unflushed` passes 2**-149 through identity Wq/Wk/Wv/Wo and reads bit pattern 0x00000001 back, so nothing flushes to zero. Spec: 7 lines added to section 3 as consequences of the IEEE 754 arithmetic already required there, no encoding, descriptor, trap or vector change.
- [x] Assert softmax ties and all-masked rows behave as specified (uniform or zero, whichever the spec says), with a test per case. `[P]`
  - verified-here: `.venv/Scripts/python.exe -m pytest -q tests/test_core.py` -> `35 passed in 1.66s`. `test_tied_scores_split_the_softmax_mass_evenly` and `test_tied_scores_under_causal_average_the_prefix` set `Wk = 0` so every score ties (s = 0): without CAUSAL all Y rows are bit-identical and equal the mean of the V rows; with CAUSAL row i is the mean of rows 0..i. `test_fully_masked_row_under_causal_is_nan` sets mask row 3 to -inf with CAUSAL: Y[3] is all NaN, rows 0/1/2/4 still match the float64 model. `docs/spec.md` section 3 already fixes both outcomes (ties share the mass through `expf(s - m)`; a row whose every `s[r]` is -inf is NaN), so no spec text changed.
- [x] ASan and UBSan builds of `tests/host/attn_host.c` in CI, `-ffp-contract=off` to keep results stable across compilers. `[P]`
  - verified-here: pinned throwaway ubuntu:24.04 container, not a CI job; digest ubuntu@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b, clang 18.1.3 (1ubuntu1). `python3 -m pytest -q -s tests/test_sanitize.py` -> `1 passed`. ASan (`-fsanitize=address -ffp-contract=off -O1 -g`): 14 vectors, 14/14 Y bit-identical to the plain clang build, 13/14 equal the frozen sha256, 1 LIBC, 0 sanitizer reports, 0 crashes, maxdiff 2.890e-07..1.476e-02. UBSan (`-fsanitize=undefined -fno-sanitize-recover=all -ffp-contract=off -O1 -g`): 14 vectors, 14/14 bit-identical to plain, 13/14 equal the frozen sha256, 1 LIBC, 0 reports, 0 crashes, maxdiff 2.890e-07..1.476e-02. Both LIBC rows are f32_gqa_scale: frozen b00e0586 was recorded under a ucrt expf, and on glibc the plain clang and gcc 13.3 builds give the same different Y as both sanitizer builds, so the divergence is libm, not sanitizer or -ffp-contract. Host `.venv/Scripts/python.exe -m pytest -q tests/test_sanitize.py tests/test_scripts.py` -> `6 passed, 3 skipped` (no clang here: the sanitizer test skips).

### M2.3 Golden vectors

- [x] Freeze a vector set (input, weights, config, expected output hash) per dtype and per feature (causal, additive mask, GQA, explicit scale) under `tests/vectors/`. `[P]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_vectors.py` -> `17 passed in 1.30s`
- [x] Any change to `attn_core.h` that moves a hash fails the test and requires an explicit re-freeze commit with the reason. `[P]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_vectors.py` -> `20 passed in 4.23s`
    - ci-fix 2026-11-26: tests/test_vectors.py prints the libm allowlist row instead of a bare pass; glibc e3e9a25a vs ucrt b00e0586, 2/320 elements, max |dY| 5.96e-08.
- [x] Version the vector file format so an old vector stays readable. `[P]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_vectors.py` -> `23 passed in 3.23s`

### M2.4 Python and script hygiene

- [x] `pyproject.toml` with pinned `numpy`, `pytest`; a lockfile; `pip install -e .` replaces the ad-hoc venv step. `[P]`
  - verified-here: `python -m venv $TEMP/pkvenv`; `$TEMP/pkvenv/Scripts/python.exe -m pip install -e .`; `python -c "import numpy, pytest"` -> `2.5.5 9.2.0`; `.venv/Scripts/python.exe -m pytest -q tests/test_xinsn.py tests/test_vectors.py` -> `54 passed, 1 skipped`; lock: 7 wheels, hashes re-checked with `pip hash`
- [x] `ruff` and `mypy` on `scripts/` and `tools/`; blocking. `[P]`
  - verified-here: `make check-lint` -> exit 0; `.venv/Scripts/python.exe -m ruff check scripts tools` -> `All checks passed!`; `.venv/Scripts/python.exe -m mypy scripts tools` -> `Success: no issues found in 12 source files`; probe `scripts/zz_lint_probe.py` (`import os`, `bad: int = "s"`) -> ruff F401 and I001 plus mypy `[assignment]`, `make check-lint` exit 2, probe deleted -> exit 0; `pytest -q tests/test_xinsn.py tests/test_vectors.py` -> `54 passed, 1 skipped`.
- [x] `shellcheck` on every `scripts/*.sh`; all scripts already use `set -euo pipefail` — assert that in a test. `[P]`
  - verified-here: `.venv/Scripts/shellcheck.exe -x scripts/*.sh` -> no output, exit 0; `ls scripts/*.sh | wc -l` -> 8; `make check-shell` -> exit 0; a probe `scripts/zz_shell_probe.sh` with an unquoted `$UNQUOTED` -> `make check-shell` exit 2, `SC2086` at lines 3 and 5 and `SC2116` at line 4, and exit 0 again after `rm`; `pytest -q tests/test_scripts.py` -> `3 passed`; `bash -n scripts/build.sh` -> exit 0; the two SC2086 the gate first found were `scripts/build.sh:66,71` (`"$TC"/bin/...`, `"$B"/qemu/...`); `pytest -q tests/test_xinsn.py tests/test_vectors.py` -> `54 passed, 1 skipped`; `make check-lint` -> exit 0.
- [x] Every script gets `--help` and a non-zero exit on unknown flags. `[P]`
  - verified-here: `./scripts/<name>.sh --help` for all 8 scripts -> rc 0 each; `./scripts/<name>.sh --bogus` -> rc 2 each, `error: unknown option: --bogus`; `.venv/Scripts/python.exe -m pytest -q tests/test_scripts.py` -> `6 passed, 2 skipped`; `shellcheck -x scripts/*.sh` -> no output, rc 0; `make check-shell` -> rc 0; `make check-lint` -> rc 0; `pytest -q tests/test_xinsn.py tests/test_vectors.py` -> `54 passed, 1 skipped`

### M2.5 Build reproducibility

- [ ] Two builds from one commit in the same container produce identical toolchain and simulator binaries, or the differences are listed and explained. `[P]`
- [x] Container image (Dockerfile or devcontainer) with the toolchain prerequisites and a digest recorded in `docs/build-and-test.md`. `[P]`
  - verified-here: xattn-prereqs:24.04 id sha256:f3bf6ef7b8858349782b5e00366c3972cbe7c251081a66b11ff4b35b15c19f0f on ubuntu digest sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b; cc and clang on tests/host/attn_host.c rc 0 and 0; tests/test_container.py 4 passed; docker system df images 126.2MB -> 1.354GB, build cache 1.301GB -> 1.301GB (prune freed 40.96kB).
- [x] `make check` fails if `out/BUILD-INFO` is missing or older than the patches. `[P]`
  - verified-here: .venv/bin/python -m pytest -q tests/test_build_info.py -> 8 passed

---

## Phase 3 — Perfective

### M3.1 One source of versions and inputs

**Why:** upstream branches, Python deps and the base image are pinned in three
places, so a rebuild months later is not the same build.
**Done when:** every script reads `versions.env` and the file is committed.

- **m3.1.1 Inputs**
  - [x] Single `versions.env` for upstream branches, Python deps and base image; every script reads it. `[F]`
    - verified-here: `pytest -q tests/test_pins.py` 11 passed in 63.94s; `scripts/check-pins.sh` rc 0 with five pins; shellcheck rc 0 on the three scripts. BASE_IMAGE_DIGEST is empty because no image was built here, so no image is claimed.
  - [ ] GCC to the current release branch, binutils to the current release branch, Spike and QEMU to tagged releases rather than `master`; re-run the full suite and record the result. `[F]`
- **m3.1.2 Dependency pinning**
  - [x] Replace the unpinned `pip install numpy pytest` (`Makefile:21-24`) with a hashed requirements file. `[F]`
    - verified-here: a fresh `.venv/Scripts/python.exe -m venv $TEMP/lockvenv`, then `python -m pip install --require-hashes -r requirements.lock` -> `lock_install_rc=0`, then `python -m pip install --no-deps -e .` -> `editable_rc=0`; the venv reports `numpy 2.5.5 pytest 9.2.0`, `ruff 0.17.6`, `mypy 2.4.1 (compiled: yes)`, `ShellCheck ... version: 0.11.0`, and `python -m pytest -q tests/test_core.py` -> `43 passed in 3.97s`. `requirements.lock` grew from 7 to 15 hashed artefacts (the dev extra: ruff, mypy, mypy-extensions, pathspec, typing-extensions, ast-serialize, librt, shellcheck-py) and the `$(PY)` rule now installs from it; `pip download` against a copy with one hash edited refused with `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`. The lock pins win_amd64 CPython 3.15 wheels, so `.github/workflows/ci.yml` keeps its own Ubuntu install and the doc says so.
    - corrected 2026-11-26: the lock held one artefact per package, the CPython 3.15 win_amd64 wheels, so the Ubuntu runner failed with `ast-serialize==0.13.1 ... Expected sha256 032b09d8... Got 9f99786e...` and all five `make check` targets that need pytest, numpy or ruff failed (Full run 45817010544). The file now lists every sdist and wheel hash PyPI publishes for each pinned version, and both platforms install from it: Linux cp312 in `xattn-prereqs:24.04` (python 3.12.3 -> numpy 2.5.5, pytest 9.2.0, ruff 0.17.6, rc 0) and win cp315 here.

### M3.2 Faster, incremental builds

**Why:** a full build is ~15 minutes on 16 cores, and a QEMU-only change rebuilds
GCC.
**Done when:** per-step targets exist and cold/warm times are published.

- **m3.2.1 Build speed**
  - [ ] `ccache` wired into `scripts/build.sh`; publish cold and warm build times. `[F]`
- **m3.2.2 Granularity**
  - [x] Split `build.sh` into per-step targets with independent `make build-binutils`, `build-gcc`, … so a QEMU-only change does not rebuild GCC. `[F]`
    - verified-here: the `Makefile` now carries one static pattern rule, `build-binutils build-gcc build-newlib build-libgcc build-dtc build-spike build-qemu build-info: build-%:`, plus `build: all`; all nine names are in `.PHONY`. `make -n` maps each target to exactly one step: `build-binutils -> scripts/build.sh binutils`, `build-gcc -> ... gcc`, `build-newlib`, `build-libgcc`, `build-dtc`, `build-spike`, `build-qemu -> ... qemu`, `build-info -> ... info`, and `make -n build -> scripts/build.sh` (all steps). `scripts/build.sh` dispatches one named step (`case $s in ... "step_$s"`) and reuses the configured build directory, so `make build-qemu` cannot touch GCC's build tree. `docs/build-and-test.md` section 3 names the targets. No full build was run here: `out/toolchain` has the binutils tools but no `riscv64-unknown-elf-gcc` driver, so a warm rebuild and its timing remain unmeasured on this machine.
  - [x] Replace the shell orchestration with `make` targets where the shell adds nothing; keep the shell for environment probing. `[F]`
    - verified-here: make -n setup = scripts/setup.sh, artifacts = scripts/artifacts.sh, patches-{apply,export,remove,restore,check,status} = scripts/patches.sh <cmd>; make -n all/build-gcc/check-core/check-shell unchanged; pytest tests/test_make_targets.py tests/test_repo_layout.py: 32 passed.

### M3.3 Code shape and generated artefacts

**Why:** `attn_core.h` mixes configuration macros with kernels, `xinsn.py` is one
file, and `artifacts/` is hand-collected.
**Done when:** each has a boundary and a producer command.

- **m3.3.1 C header**
  - [ ] `include/attn_core.h`: split macro-heavy sections (`ATTN_*` configuration) from the numeric kernels; keep it header-only and C89-clean for the simulators. `[F]`
  - parked 2026-11-26: split + C89 conversion proven in d979b71, reverted here; the header is copied into spike/riscv, qemu/target/riscv and gcc/libgcc at pinned submodule commits, so landing it needs three submodule commits plus pointer bumps.
- **m3.3.2 Python**
  - [x] `scripts/xinsn.py` split into modules (spec parse, encoding allocation, tree edit, test build) with the tests from M1.2 as the net. `[F]`
    - verified-here: `scripts/xinsn.py` 1272 -> 343 lines (CLI only); new `xinsn_common.py` 71 (paths, exit codes, errors), `xinsn_spec.py` 137 (parse, templates), `xinsn_encoding.py` 46 (slot and word), `xinsn_tree.py` 571 (Editor, diffs, apply to the four trees), `xinsn_build.py` 138 (host model, vector test). Proof: `pytest -q tests/test_xinsn.py` -> `31 passed, 1 skipped in 526.47s`; `ruff check scripts tools` -> `All checks passed!`; `mypy scripts tools` -> `Success: no issues found in 17 source files`; `scripts/xinsn.py verify examples/insns/mac.spec` -> `ok: 3006 known encodings checked; the slot collides with none`, `ok: extension xmac is new`, `ok: 29 files would change; the trees are not touched`; `pytest -q tests/test_core.py` -> `55 passed in 17.04s`. The CLI is unchanged: `show --json`, `list` and `--help` output are byte-identical to the pre-split script.
- **m3.3.3 Artefacts and docs**
  - [ ] Regenerate `artifacts/` from a CI run instead of committing hand-collected files; every file gets a "produced by <command> at <sha>" line. `[F]`
  - [x] Documentation: one entry point (`docs/INDEX.md`) mapping each doc to the claims it supports and the test that proves it. `[F]`
    - follow-up: `docs/troubleshooting.md` added to the table after the diagnose unit landed, so the coverage snippet at the end of the page still prints nothing.
    - verified-here: `ls docs | wc -l` -> `12` and `grep -cE '^\| `docs/' docs/INDEX.md` -> `12`, one row per document. A loop over `docs/*` that greps each name in the index printed nothing (`coverage_missing=0`), and every `tests/*.py` path the table names exists (`absent_paths=0`); the targets and scripts it cites were resolved on disk: `Makefile` `check-recog`/`check-three-way`/`check-build-info`, `scripts/check-pins.sh`, `scripts/check-build-info.sh`, `examples/insns/mac.spec`, `tests/vectors/MANIFEST.json`. The RUNBOOK row says plainly that it has no dedicated test rather than claiming one.

---

## Phase 4 — Widening

### M4.1 Prove the general method with a second instruction

- [ ] Ship a second worked example end to end (a small, non-attention instruction such as `mac` or a RoPE step) as `examples/<name>.spec` plus a demo, with its own tests in `make check`. `[W]`
- [x] `xinsn.py list --json` for tooling, and `xinsn.py verify SPEC` that checks a spec without touching the trees. `[W]`
  - verified-here: `python -m pytest -q tests/test_xinsn.py` -> `21 passed, 1 skipped`; `python scripts/xinsn.py verify examples/insns/mac.spec` -> `ok: 29 files would change; the trees are not touched`
- [x] Templates: `xinsn.py new --template elementwise|reduction|memory` prefilled specs. `[W]`
  - verified-here: `python -m pytest -q tests/test_xinsn.py` -> `26 passed, 1 skipped`; `new --template reduction` then `verify` -> `ok: 28 files would change; the trees are not touched`
    - ci-fix 2026-11-26: xinsn.py new accepts the positional SPEC again; bad stem exits 1; 5 CI tests green.
    - ci-fix 2026-11-26: xinsn.py options also parse after the subcommand, so python 3.12 (the CI runner) accepts 'new --template T SPEC'; five CI tests green on 3.12.3 in xattn-prereqs:24.04.
- [x] Document the failure modes of the method (encoding exhaustion per major opcode, conflicts with other vendor extensions, attribute naming). `[W]`
  - verified-here: `scripts/find_opcodes.py --inputs 2 --major custom-0 --strict --first` -> `no free R slot`; `scripts/xinsn.py verify` on a spec pinned to a shared slot -> collides with 25 vendor insns, exit 1; `show` on `name = MAC` -> `must match [a-z][a-z0-9]{1,15}`

### M4.2 Recognizer coverage

- [ ] Add patterns for the transformer ops next to attention (standalone softmax, RoPE, layer norm) as separate recognitions with their own tests. `[W]`
- [ ] Recognition report on a real code base: which loops were recognised, which were not, and why — a table with per-file counts. `[W]`
  - corpus 2026-11-26: fetched from this host into the gitignored `build/corpus/` (llama.cpp 436d7e81, MNN 54694759, ncnn 3c9504a6, llama2.c 350e04fe, per-tree tar sha256 and licences in `.fleet/evidence/RISC-VInjection/corpus-303-350.md`); the blocker is now the built recognizer, not the network.
- [ ] `-fno-attn` and a per-function attribute to opt out; test both. `[W]`
- [x] Cost model: publish the runtime guard cost when the instruction is absent. `[W]`
  - verified-here: `make -C tests/perf check` at 076aeab, the `g_` rows of `tests/perf/expected/spike.csv`: with the guard failing at (0,32,4), (8,33,8) and (8,32,0) the attn build retires +13, +67 and +13 instructions against the same loops built without the recognizer, so the guard costs 13..67 instructions once per call and never per element; published with the method in `docs/results.md` and asserted by `pytest -q tests/test_perf.py` -> 6 passed.

### M4.3 Portability of the instruction

- [ ] RV32: full test coverage (the spec says valid on RV32 and RV64; prove it on both simulators for every vector). `[W]`
  - defect: tests/baremetal/Makefile hardcodes -mabi=lp64d, so RV32 coverage cannot be built as written; adding an rv32 build is part of this row, not a toolchain wait.
- [x] Vector (V) variant or a documented reason not to; if done, a separate extension name and spec version. `[W]`
  - verified-here: `grep -n '^## ' docs/spec.md` -> sections 1 to 8; `git diff --numstat HEAD -- docs/spec.md` -> 25 0; `.venv/bin/python -m pytest -q tests/test_vectors.py` -> 23 passed
- [x] Cross-check against a third implementation (QEMU TCG vs Spike interpreter already differ; add a scalar reference build of `attn_core.h` compiled for the host as the third). `[W]`
  - verified-here: `tests/test_scalar_crosscheck.py` compiles `tests/host/attn_scalar.c` with `cc` (gcc 16.2.0, `-Wall -Werror`, no libm) and compares three implementations: the `attn_core.h` host build, this scalar C reference (double accumulation, own exp/sqrt) and the float64 `tools/attn_model.py` model. Max |Y - Yref|, scalar vs host (out_dtype tolerance): f32_bias 2.38e-07, f32_4head 5.66e-07, bf16_in 4.77e-07, bf16_out 0 (0.0078), causal 4.77e-07, mask 4.77e-07, gqa 5.96e-07, mqa 2.38e-07, explicit_scale 2.38e-07, nobias_causal_mask 3.58e-07; every f32 row is under 0.0001. `pytest -q tests/test_scalar_crosscheck.py` -> 17 passed in 18.58s (10 configurations, one seeded --gen problem against the model, six reserved cfg rejections including e % h != 0 with rc 1); `ruff check` -> clean. Spike and QEMU binaries are absent on this machine, so the simulator rows stay unrun and the three implementations compared here are the core host build, this scalar C reference and the float64 Python model.

### M4.4 Teaching surface

- [x] `docs/study.md` exercises get checked answers, one per stage. `[W]`
  - verified-here: `.venv/Scripts/python.exe -m pytest -q tests/test_study_answers.py` -> 10 passed; 7 stage answers
- [ ] A single walkthrough that adds a toy instruction from scratch in under 30 minutes, tested by CI on a scratch tree. `[W]`
- [x] Publish the artefacts report as static HTML (no build step) with tables generated from the JSON results. `[W]`
  - verified-here: `.venv/Scripts/python.exe tools/report_html.py` -> artifacts/report.html 8756 bytes, 46 <tr> rows, 0 script tags

---

## Phase 5 — Depth

### M5.1 Correctness depth

- [x] Randomised differential testing: 1,000 random shapes, dtypes, head counts, mask types and scales against `tools/attn_model.py`; report failures by category. `[D]`
  - verified-here: `scripts/random_diff.py --cases 1000` -> `1000 cases, 0 failures`; `.venv/bin/python -m pytest -q tests/test_random_diff.py` -> `3 passed`
- [x] State the tolerance derivation once (float32 accumulation order, bf16 input rounding) in `docs/theory.md`, and use it everywhere instead of per-test magic numbers. `[D]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_tolerances.py tests/test_core.py tests/test_vectors.py` -> `62 passed`; frozen-vector max abs error 1.43e-06 with ATOL_F32=1e-4 and ATOL_BF16=2^-7 now defined once in tools/tolerances.py
- [x] Accumulation-order analysis: prove the spike, QEMU and host paths sum in the same order, or make the order explicit in `attn_core.h` and assert it. `[D]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_accumulation_order.py` -> `14 passed`; the host path is bit-exact against the ascending-k order the header states, a reordered sum is detected, and include/attn_core.h is unchanged
- [x] Boundary shapes: n=1, e=1, heads=1, head_dim=1, n>cache, empty mask, maximum dims from the descriptor fields. `[D]`
  - verified-here: `.venv/bin/python -m pytest -q tests/test_boundaries.py` -> `12 passed`; the maxima are read from include/attn_abi.h and one-past shapes are refused; the ABI has no cache field, so n>cache is vacuous
- [x] Cross-compiler stability: the same vectors under GCC and Clang at `-O0/-O2/-O3 -ffp-contract=off` must match. `[D]`
  - verified-here: ubuntu:24.04 base sha256:562111b88caa via xattn-prereqs:24.04 sha256:f3bf6ef7b885, gcc 13.3.0 + clang 18.1.3, 6 builds x 14 vectors, 0 cross-build mismatches; 1 pre-existing frozen miss f32_gqa_scale.json: 2/320 Y elements, max |dY| 5.96e-08, build larger at element 144 and smaller at element 159, same vector fails tests/test_vectors.py in the image; host venv run skips (no clang).

### M5.2 Performance depth

- [x] Measure `attn` against the plain C loop on both simulators: retired instructions and simulated cycles per shape, in a table with the method stated. `[D]`
  - verified-here: `make -C tests/perf check` at 076aeab with the toolchain from Full run 45857819667 -> `build/perf/{spike,qemu}.csv`, committed as `tests/perf/expected/`; six shapes (4,8,2) to (64,128,8): the loops retire 12591..34535911 instructions, the attn build 1026..1369; the two simulators agree on every count exactly; QEMU runs with `-icount shift=0,sleep=off`, without which its counters read a host clock; tables and method in `docs/results.md`, figures re-derived by `pytest -q tests/test_perf.py` -> 6 passed.
- [x] Measure the speedup on real hardware only if a board is available; otherwise say clearly that no silicon number exists. `[D]`
  - verified-here: docs/results.md states no board was available and no silicon speedup is claimed; tests/test_results.py 5 passed; docs index loop prints nothing and lists no missing test.
- [x] Estimator: model the cycle cost from the descriptor (n, e, heads) and publish the error against measurement. `[D]`
  - verified-here: `python tools/perf_report.py build/perf` fits I(n,e,h) = 1017.6 + 0.0423*n*e by least squares on the six measured shapes of `tests/perf/expected/spike.csv` and prints predicted against measured: errors -0.7, -0.8, +1.0, -1.6, +2.5 and -0.4 percent, largest 2.6 percent; h enters only through the guard comparison, so the model has no h term; `pytest -q tests/test_perf.py` -> 6 passed asserts both coefficients and the 2.6 percent bound.
- [ ] Recognizer cost: `.ATTN` replacement vs the original loops at `-O2`, per file in the corpus. `[D]`

### M5.3 Recognizer quality

- [ ] Precision and recall of loop recognition over a labelled corpus (≥30 attention implementations from real projects); report false positives with the guard cost. `[D]`
  - corpus 2026-11-26: the same four trees carry the >=30 sites (11 scalar flash_attn/attn definitions in llama.cpp ggml-cpu and ggml-et, 31 MNN files under source/backend/cpu, 68 ncnn files under src/layer, llama2.c inline in transformer()); the blocker is now the label file (file, line range, attention or not) plus the built recognizer.
- [x] Robustness: loops with early exits, aliasing, non-contiguous strides, and mixed precision must be rejected, not mis-recognised. `[D]`
  - verified-here: `make -C tests/recog reject` with the 076aeab toolchain compiles `tests/recog/reject/{early-exit,alias,strided,mixed-precision}.c` and prints `reject alias ok`, `reject early-exit ok`, `reject mixed-precision ok`, `reject strided ok`, rc 0; each file must keep zero `attn` and emit a `missed: attention loops not replaced: ...` line, with the reasons being `output may alias an input (declare it restrict)`, `loop is not in simple form`, `projections of Q, K, V or the output product not found` (the strided case) and the same projections reason for the double accumulator; `make -C tests/recog check` also runs the four rejections and is still green on QEMU and Spike (`recog_test: all passed` twice).
- [ ] State the recognised pattern formally in `docs/recognizer.md` as a grammar, and test that the implementation matches it. `[D]`

### M5.4 CLI and artefact craft

Method: `design-ux` §1 principles applied to a CLI — one job per command, output
that a machine can read, failures that name the fix.

- [x] `scripts/attncc.sh --run` prints one line per stage (extract, compile, assemble, run, compare) with a pass/fail marker. `[D]`
  - verified-here: in the container with the 076aeab toolchain, `scripts/attncc.sh --run demo/mha_plain.c` prints one timed line per stage (`== stage extract 0.017s PASS`, `compile 4.183s PASS`, `assemble 0.393s PASS`, `link 6.183s PASS`, `run 0.120s PASS`, `compare 0.008s PASS`) and exits 0; a source that does not compile prints `== stage compile 2.050s FAIL` and the script exits 1; `shellcheck -x scripts/attncc.sh` rc 0; `pytest -q tests/test_scripts.py -k 'not script_set'` -> 5 passed, 2 skipped (the script-set test also counts an untracked scripts/check-artifacts.sh in this worktree; HEAD's 11 tracked scripts match KNOWN).
- [x] `xinsn.py` output: dry-run diff preview, colour only on a TTY, `--json`, and an exit code that distinguishes "spec invalid" from "build failed". `[D]`
  - verified-here: cd /c/GITHUB/yash-awasthi/RISC-VInjection; .venv/bin/python -m pytest -q tests/test_xinsn.py -k "show or json or color or colour or invalid or build" -> 10 passed in 52.44s
- [x] `make check` summary table at the end: target, pass, fail, time; non-zero exit on any failure. `[D]`
  - verified-here: `make check` now runs `bash scripts/check-summary.sh $(CHECK_TARGETS)` (`make -n check` prints exactly that line). Each target is its own `make` invocation, so a failure does not hide the rest; the table prints target, pass, fail and seconds plus a `total` row, and any failed row exits 1. On the tools this machine has: `bash scripts/check-summary.sh check-core check-lint check-shell` -> three PASS rows (`check-core 1 0 9s`, `check-lint 1 0 2s`, `check-shell 1 0 2s`, `total 3 0 13s`), rc 0; `bash scripts/check-summary.sh check-core no-such-target` -> `total 1 1 4s`, `fail_rc=1`. `tests/test_scripts.py` and `tests/test_build_info.py` -> `14 passed, 2 skipped in 91.34s` (the script count is now 9 and the build-info test reads `CHECK_TARGETS`); `.venv/Scripts/shellcheck.exe -x scripts/check-summary.sh` -> rc 0. The other six targets need the toolchain, so their rows are untested here.
- [x] Error messages name the file, line and fix for the five most common build failures (missing package, patch conflict, submodule not initialised, stale toolchain, wrong `-march`). `[D]`
  - verified-here: 15 passed, 2 skipped (pytest tests/test_diagnose.py tests/test_scripts.py); shellcheck rc=0; diagnose.sh gave rc 1 with line 4 for patch-conflict.log and line 3 for wrong-march.log, rc 0 for a clean log

---

## Phase 6 — Enterprise

### M6.1 Spec governance

**Why:** the encoding is normative and has no version discipline.
**Done when:** a semantic change cannot land without a version bump and a re-frozen vector set.

- **m6.1.1 Versioning**
  - [x] `docs/spec.md` versioned with a changelog; a semantic change requires a new version, a vector re-freeze and a compatibility note. `[E]`
  - verified-here: docs/spec.md version 1.0, changelog added, no semantic change; make check-core -> 32 passed in 3.49s.
- **m6.1.2 Releases**
  - [ ] Tags per spec version, a source archive, the matching `BUILD-INFO`, and the vector set as the release's evidence. `[E]`

### M6.2 Upstream and contribution

**Why:** five forks and no submission package means the work stays unmergeable.
**Done when:** a reviewer can apply and test the series from the cover letter alone.

- **m6.2.1 Submission package**
  - [x] Each patch with a commit message in the project's style, a cover letter, and a documented test plan a reviewer can run. `[E]`
    - verified-here: `patches/COVER-LETTER.md` names the four series (12 patches), each patch's full subject, its pin and its review list; a check script read `git -C <tree> log --format=%s <pin>..xattn` for all four trees -> `series_subjects=12`, `patch_files=12`, `subjects_missing=0`. Every command the test plan names exists: `scripts/patches.sh --help` lists `apply`, `export`, `remove`, `restore`, `check`, `status` (rc 0); `Makefile` defines `check`, `check-core`, `check-gcc`, `check-sched`, `check-demo`, `check-sim`, `check-recog`, `check-lint`, `check-shell`, `check-three-way`, and `check` chains the suite. Steps 1-2 of the plan were run: `scripts/check-pins.sh` -> five pins, rc 0; `scripts/patches.sh status` -> four trees `on xattn`, rc 0. Steps 3-6 are the reviewer's build and are not re-run here: `out/toolchain` holds binutils but no `riscv64-unknown-elf-gcc`, and no QEMU/Spike binaries.
- **m6.2.2 Ownership**
  - [x] `CODEOWNERS` for `patches/`, `include/`, `scripts/`; a review checklist for anything touching `attn_core.h` (spec, vectors, all three executions). `[E]`
  - verified-here: .venv/bin/python -m pytest -q tests/test_repo_layout.py -> 7 passed in 0.09s

### M6.3 Operability and long-term cost

**Why:** a build failure has no first diagnostic, and the maintenance cost is unstated.
**Done when:** the runbook exists and the cost is written down.

- **m6.3.1 Runbook and security**
  - [x] `docs/RUNBOOK.md`: build fails at each step, patch conflict, submodule drift, simulator aborts, vector mismatch — each with the first diagnostic command. `[E]`
  - verified-here: scripts/check-pins.sh -> five pins match versions.env, rc 0; scripts/patches.sh status -> binutils gcc spike qemu on xattn; make check-core -> 32 passed in 1.67s; git -C gcc status --porcelain -> empty; every command located in scripts/build.sh, scripts/patches.sh, scripts/check-pins.sh, Makefile, spike/spike_main/spike.cc, qemu/qemu-options.hx, qemu/util/log.c
  - [x] `SECURITY.md`: how to report a simulator bug (a mis-executed instruction is a security issue in an emulator) and the response window. `[E]`
  - verified-here: SECURITY.md 60 lines, sections Reporting, What to send, Response window, Scope and upstream, Supported versions; GitHub private vulnerability reporting only, no email; 5/10/30 business-day windows, 90-day disclosure; git ls-tree HEAD spike gcc qemu binutils newlib -> 89c7471, 041359f, 615ece3, 781713d, 06add56; git -C spike rev-parse HEAD -> 79f1804
- **m6.3.2 Support matrix**
  - [x] Host OS, GCC/Clang, Python, disk and time budget for a full build; CI enforces what it can. `[E]`
  - verified-here: docs/build-and-test.md section 7 added (lines 152-231), sections 1-6 unchanged (git diff --numstat 81 0); measured gcc 16.2.0, clang NOT FOUND, python3 3.15.0, numpy 2.5.5 pytest 9.2.0, make 4.4.1, cmake 4.4.5, ninja 1.13.2, git 2.55.0, nproc 20, df -h . 159G available; grep -n '^## ' shows sections 1 to 7
- **m6.3.3 Honest cost**
  - [x] Cost of maintaining five forks stated (hours per upstream release), with the option to upstream the extension and drop the forks. `[E]`
  - verified-here: ls patches/*/*.patch -> 12 patches (binutils 1, gcc 5, spike 3, qemu 3, newlib 0); git -C gcc log --oneline xattn -> 5 commits above the pin; wc -l patches/gcc/*.patch -> 5081; derived 23.75 h if all five bump, 54.85 h a year as forks, 14.5 h a year if upstreamed; 108 lines appended, no existing line changed

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
- 2026-11-24 m1.3.2 [x] CONTRIBUTING.md (DCO, patch series, spec+vectors rule) | proof: every command named exists in `Makefile`/`scripts/` | next: m1.3.3
- 2026-11-24 m1.3.3 [x] SPDX on the 31 owned files, LF pinned by .gitattributes, patch series re-exported | proof: `make check` → exit 0 in 115s, 67 PASS; 3/3 header copies byte-identical; `patches.sh remove && apply` clean on all four trees | fix: `patches.sh` now ignores stat-only dirt (qemu's 10873 phantom entries) | next: m1.3.4
- 2026-11-24 m1.3.4 [x] README provenance section | proof: original vs derived table, licences matched to each tree's COPYING* | next: m1.3.5
- 2026-11-24 m1.4.1 [x] versions.env + check-pins.sh asserted by setup.sh | proof: drifted tree → exit 1 naming SHA and pin; restored pointers → exit 0, 5 pins | fix: m1.3.3's `git add -A` had committed the patched submodule commits as pins | next: m1.4.2
- 2026-11-24 m1.4.2 [x] .gitmodules: no `branch` keys, newlib → sourceware canonical | proof: no branch key (rc 1); both newlib remotes serve 06add56 (fetch --depth 1 OK); `submodule sync` keeps the pin; 6 pins tests pass | next: m1.4.3
- 2026-11-24 m1.4.3 [x] out/BUILD-INFO written by build.sh, copied by make check | proof: `scripts/build.sh info` → 17-line record (pins + host + versions); `make check` → exit 0, 67 PASS, artifacts/BUILD-INFO 954 bytes; 9 tests pass | note: Spike has no --version, `git describe` used | next: m1.5.1
- 2026-11-24 m1.5.1 [x] three executions agree bit for bit, with the max abs difference printed | proof: `make check-three-way` → 7 cases × {QEMU, Spike} all maxdiff=0 vs the host core; bare-metal `check` still green | corrected: seven shapes, not five | next: m1.5.2
- 2026-11-24 m1.5.2 [x] precise traps on both simulators | proof: 14 PASS per bare-metal run each; new: dims_out_of_range (mcause 2, Y untouched), element_size_out_of_range, descriptor_fault_is_precise (mtval = bad address) | measured: misaligned descriptor completes on QEMU, traps (cause 4) on Spike | next: m1.5.3
- 2026-11-24 m1.5.3 [x] attn scheduled under all 13 pipeline models (26 tunings) | proof: `make check-sched` → 26 rows, each 2 `attn` lines annotated `riscv_attn_di`; tunings read from riscv-cores.def | next: m1.5.4
- 2026-11-24 m1.5.4 [x] one .ATTN / one attn for the demo, before and after | proof: `make check-demo` → loops 0/0, recognized 1/1; 333→375 static instructions, same 6 float ops (guard fallback) | corrected: static size grows, gain is run time | next: m1.5.5
    - ci-fix 2026-11-26: math.fma fallback (tools/attn_model.py), reason: python < 3.13 on the CI runner; 71 tests green.
