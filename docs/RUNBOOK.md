# Runbook

Commands in this runbook were verified against the pinned sources in this tree: the steps in `scripts/build.sh`, the patch flow in `scripts/patches.sh`, the pin check in `scripts/check-pins.sh`, the Spike flags in `spike/spike_main/spike.cc` and the QEMU flags in `qemu/qemu-options.hx`. Paths are relative to the repository root.

## 1. A build step fails
The failing step is the one named by the last `== <step>` line printed and by the `failed, full log:` line. `run_logged` writes the command output to `DIR/LOG`, and on failure prints `tail -30` of it plus `failed, full log: <dir>/<log>` and exits 1, so the build stops at the first failing step and later steps did not run. The first diagnostic is always `tail -40` of that log.

| Step | First diagnostic | Log it writes | Re-run |
|------|------------------|---------------|--------|
| binutils | `tail -40 build/binutils/make.log` | `build/binutils/make.log`, `build/binutils/install.log` | `scripts/build.sh binutils` |
| gcc | `tail -40 build/gcc/make.log` | `build/gcc/make.log`, `build/gcc/install.log` | `scripts/build.sh gcc` |
| newlib | `tail -40 build/newlib/make.log` | `build/newlib/make.log`, `build/newlib/install.log` | `scripts/build.sh newlib` |
| libgcc | `tail -40 build/gcc/libgcc.log` | `build/gcc/libgcc.log`, `build/gcc/libgcc-install.log` | `scripts/build.sh libgcc` |
| dtc | `tail -40 build/dtc.log` | `build/dtc.log` (no install log) | `scripts/build.sh dtc` |
| spike | `tail -40 build/spike/make.log` | `build/spike/make.log`, `build/spike/install.log` | `scripts/build.sh spike` |
| qemu | `tail -40 build/qemu/make.log` | `build/qemu/make.log` only | `scripts/build.sh qemu` |

A configure failure is different: `configure_once` prints `configure failed, see <dir>/configure.log` (for example `build/gcc/configure.log`), so read that file instead of the make log. If the configure arguments differ from the recorded `build/<step>/configure.args`, it prints `configure arguments changed, reconfiguring <dir>` and deletes the directory, so that run is a full rebuild.

The default order, used when `scripts/build.sh` gets no arguments, is binutils gcc newlib libgcc dtc spike qemu. `scripts/build.sh <step>` rebuilds one step.

### binutils
Read the first `error:` line in the tail; it names the source or tool that failed. Re-run `scripts/build.sh binutils` after fixing it.

### gcc
Read the first `error:` or `internal compiler error` line. A configure failure means `build/gcc/configure.log` instead.

### newlib
Read the first `error:` line. Missing headers or a bad `-mcmodel` show up here.

### libgcc
This step logs to `build/gcc/libgcc.log` because it runs in the gcc build directory; there is no `build/libgcc` directory. Read the first `error:` line.

### dtc
The command runs inside `qemu/subprojects/dtc` and its log argument is `$B/dtc.log`, which is `build/dtc.log`. If `dtc` is already on `PATH`, the step prints `using <path>` and does nothing. There is no install log; the binary is copied to `out/host/bin/dtc`.

### spike
Read the first `error:` line. Re-run `scripts/build.sh spike`.

### qemu
There is no install log: the build only writes `build/qemu/make.log` and leaves the binary at `build/qemu/qemu-system-riscv64`.

## 2. A patch fails to apply
`scripts/patches.sh apply gcc` checks out the pinned base on branch `xattn` and runs `git am -q --3way patches/gcc/*.patch`. When `git am` stops, the first diagnostics are:

```bash
scripts/patches.sh status
git -C gcc status
git -C gcc am --show-current-patch
```

`--show-current-patch` prints the patch being applied; the variant `--show-current-patch=diff` or `--show-current-patch=raw` also exists in git 2.55.0.windows.5, next to `--continue`, `--skip`, `--abort` and `--quit`.

A message "You are in the middle of an am session" means a previous `git am` stopped, `.git/rebase-apply/` is present under the gcc tree, and it has not been aborted or continued. No new series can start until the old one is resolved: `git -C gcc am --abort` returns the tree to the pre-am state, or `git -C gcc am --continue` after fixing the conflict. Then re-apply and prove the series:

```bash
git -C gcc am --abort
scripts/patches.sh apply gcc
scripts/patches.sh check
```

`scripts/patches.sh check` proves the series in a temporary worktree (apply --check per patch, `git am` twice, export comparison) and never touches the repository's own worktree.

`git -C gcc status --porcelain` can show thousands of `M` entries on Windows that are stat-only dirt: the blob is identical to the index because of the CRLF checkout. Content decides, not stat data; `git diff --quiet` is the test. `scripts/patches.sh remove` refuses only when the tree has real uncommitted content changes, and ignores the stat-only entries.

## 3. A submodule is the wrong commit
Drift means the checkout is not the commit that produced the build: built != pinned. `scripts/check-pins.sh` compares `versions.env` with the pin recorded in the superproject (`git ls-tree HEAD`), not with the checkout. On success it prints one line per submodule, `<name> <sha>`, and exits 0. On mismatch it prints to stderr `error: <NAME>_SHA in <file> is <want> but the superproject pins <pin>` and exits 1. It never fetches and never changes a submodule.

```bash
scripts/check-pins.sh
git -C gcc rev-parse HEAD
git ls-tree HEAD gcc
git -C gcc log --oneline -3
git -C gcc status --porcelain
```

`git ls-tree HEAD gcc` prints `mode type sha<TAB>name`; that sha is the pinned commit. `out/BUILD-INFO` records the same pair per component, with lines of the form `  gcc      pinned <sha>  built <sha>`. It is written by `write_build_info` at the end of every build and lists binutils, gcc, newlib, qemu and spike; an absent checkout shows `built no git checkout`.

| State | Meaning | Action |
|-------|---------|--------|
| built == pinned, branch `xattn` | expected | none |
| built = pinned + local patches on `xattn` | expected after `scripts/patches.sh apply` | none; `scripts/patches.sh check` proves the series |
| built != pinned and not an ancestor of `xattn` | drift | re-run `scripts/patches.sh apply gcc` |
| `BUILD-INFO` built differs from `git rev-parse HEAD` | stale record | re-run `scripts/build.sh info` |

Local commits on `xattn` are the patches; `git -C gcc log --oneline -3` shows them above the pinned base.

## 4. The simulator aborts
Both commands below need the simulator built first on this host: `scripts/build.sh spike` or `scripts/build.sh qemu`.

### Spike
```bash
out/spike/bin/spike --isa=rv64gc_xattn prog.elf
```

First diagnostic: rerun with logging enabled. The flags come from the help text in `spike/spike_main/spike.cc` lines 36-61: `-d` interactive debug, `-l` log of execution, `--log=<name>` file name for `-l`, `--isa=<name>`, `--log-commits` commits info. `--log-commits` reaches `proc->enable_log_commits()` at `spike/riscv/sim.cc:414`.

```bash
out/spike/bin/spike --isa=rv64gc_xattn -l --log=spike.log --log-commits prog.elf
grep -n trap spike.log
```

### QEMU
```bash
build/qemu/qemu-system-riscv64 -M virt -bios none -nographic -cpu rv64,xattn=on -kernel prog.elf
```

First diagnostic: add `-d in_asm,int -D qemu.log`, then search the log. `-d item1,...` and `-D logfile` are in `qemu/qemu-options.hx` lines 5142 and 5151; `in_asm` is defined at `qemu/util/log.c:487` ("show target assembly code for each compiled TB") and `int` at `qemu/util/log.c:499` ("show interrupts/exceptions in short format"). `-d help` lists the items.

```bash
build/qemu/qemu-system-riscv64 -M virt -bios none -nographic -cpu rv64,xattn=on -d in_asm,int -D qemu.log -kernel prog.elf
grep -n -i 'exception\|illegal' qemu.log
```

### Reading the trap
`trap_illegal_instruction` in Spike, or an illegal-instruction exception in QEMU, on an `attn` means the extension is not enabled: `--isa` lacks `_xattn`, or `-cpu` lacks `xattn=on`. The other cause is a reserved configuration, listed in `docs/spec.md` section 4 (n == 0, e == 0, h == 0, e % h != 0, h % h_kv != 0, an extra flag bit or reserved != 0, in_dtype > 1 or out_dtype > 1, a null wq/wk/wv/wo, RV32 upper-half pointers, n > 4096, e > 2048).

A misaligned load (cause 4) on Spike with a correct result on QEMU is the descriptor-alignment case in `docs/spec.md` section 5: QEMU completes the unaligned access, Spike raises the fault. Fix the program by placing the descriptors on their natural boundary with `_Alignas(8)`.

## 5. The results do not match
The comparison targets, in order of cost:

```bash
make check-core
make check-three-way
make -C tests/baremetal check
python3 tests/run_dg.py gcc/gcc/testsuite/gcc.target/riscv/xattn-*.c
```

`make check-core` compares `attn_core.h` with the float64 host model and builds nothing. `make check-three-way` sets `XATTN_SIM=1` and runs `tests/test_three_way.py`; it needs a full `scripts/build.sh`. `make -C tests/baremetal check` needs `CC=out/toolchain/bin/riscv64-unknown-elf-gcc` plus the SPIKE/QEMU paths. `python3 tests/run_dg.py gcc/gcc/testsuite/gcc.target/riscv/xattn-*.c` is the check-gcc command and needs the built cross gcc.

First diagnostic: the case name that fails names the target to re-run. For the bare-metal cases the per-case line is ` maxdiff=<16 hex digits>`, printed by `tests/baremetal/attn_test.c:126` (` maxdiff=` followed by the largest absolute difference as a 64-bit value, high nibble first). `maxdiff=0000000000000000` means all zeros, which is bit-exact; any other value is the largest absolute difference for that case. `check-three-way` prints the case/QEMU/Spike/verdict table, so a difference is visible rather than only fatal.

When the numbers disagree, suspect the pinned source (the `attn_core.h` copy or the simulator implementation), not the test. The arithmetic order that all implementations must follow is in `docs/spec.md` section 3.

## 6. What this machine can run right now
- `make check-core`, `scripts/check-pins.sh` and `scripts/patches.sh status` need no build.
- Anything that uses `out/toolchain/bin/riscv64-unknown-elf-gcc`, `out/spike/bin/spike` or `build/qemu/*` needs `scripts/build.sh` first (`scripts/build.sh gcc`, `scripts/build.sh spike`, `scripts/build.sh qemu`). On this host binutils is built, but there is no cross gcc, no `out/spike/bin/spike` and no `build/qemu/qemu-system-riscv64`.
