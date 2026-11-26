# Build and test, step by step

These steps take a fresh machine to a verified `attn` instruction on both
simulators. They were run as written on Arch Linux (16 cores, NVMe).
Ubuntu package names are given too.

`scripts/setup.sh` runs sections 1 to 4 in one go and then compiles and
runs the demo with `scripts/attncc.sh --run demo/mha_plain.c`. The
sections below are the same steps by hand.

## 1. Packages

Arch:

```bash
sudo pacman -S --needed base-devel git python gmp mpfr libmpc texinfo \
    bison flex gawk zlib expat dtc pixman glib2 ninja meson patchutils bc \
    clang lld
```

Ubuntu 24.04:

```bash
sudo apt-get install -y build-essential git python3 python3-venv \
    libgmp-dev libmpfr-dev libmpc-dev texinfo bison flex gawk zlib1g-dev \
    libexpat-dev device-tree-compiler libpixman-1-dev libglib2.0-dev \
    ninja-build meson patchutils bc clang lld
```

`dtc` is optional: `scripts/build.sh dtc` builds it from QEMU's bundled
copy. `clang`/`lld` are optional too: they build the bare-metal tests with
`.insn` before GCC exists. Disk: about 15 GB, most of it the full GCC
history.

### Container image

`container/Dockerfile` installs the Ubuntu packages above plus the host
build tools (gperf, dejagnu, the autotools, gettext, libisl-dev,
libzstd-dev, libfdt-dev, libslirp-dev, ccache). The base is pinned by
digest:

```
FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b
```

Build it once; the context is `container/` only:

```bash
DOCKER_BUILDKIT=0 docker build --memory 4g --cpu-period 100000 \
    --cpu-quota 400000 -t xattn-prereqs:24.04 container/
```

The legacy builder has no `--cpus` flag in engine 29; `--cpu-quota` and
`--cpu-period` cap it at 4 CPUs. Local image id:
`sha256:f3bf6ef7b8858349782b5e00366c3972cbe7c251081a66b11ff4b35b15c19f0f`.

Run it with the repository mounted read-only:

```bash
docker run --rm --memory 4g --cpus 4 \
    -v "$PWD:/src:ro" -w /src xattn-prereqs:24.04 bash
```

Probes inside that container: cc 13.3.0, clang 18.1.3, flex 2.6.4,
bison 3.8.2, gperf 3.1, GNU Make 4.3, Python 3.12.3, dtc 1.7.0.
`tests/host/attn_host.c` builds as a shared object with both compilers at
`-std=c11 -O2 -Wall -Werror -ffp-contract=off -shared -fPIC -I include
... -lm`: `cc` exits 0 and `clang` exits 0.

The image holds prerequisites only. There is no RISC-V cross compiler, no
Spike and no QEMU inside it: sections 2 and 3 build those from the mounted
repository.

## 2. Sources

```bash
git clone https://github.com/Yash-Awasthi/RISC-VInjection.git
cd RISC-VInjection
git submodule update --init gcc binutils spike qemu newlib   # full history, ~6 GB
scripts/patches.sh apply                                     # branch xattn in each
scripts/patches.sh status
```

`apply` checks out the commit the repository pins, creates branch
`xattn` there and applies `patches/<project>/*.patch` with `git am`. To
see what a patch changes: `git -C gcc log -p xattn -1`.

## 3. Build

```bash
make            # = scripts/build.sh
```

The script runs these steps, each configured once and rebuilt
incrementally afterwards:

| Step | Result | Time measured here |
|------|--------|--------------------|
| `binutils` | `out/toolchain/bin/riscv64-unknown-elf-{as,ld,objdump,...}` | ~3 min |
| `gcc` | the C compiler only (`all-gcc`), no bootstrap | 5.3 min |
| `newlib` | newlib + libgloss, `-mcmodel=medany` | 13 s |
| `libgcc` | libgcc, `-mcmodel=medany` | ~1 min |
| `dtc` | `out/host/bin/dtc` if none is installed | seconds |
| `spike` | `out/spike/bin/spike` | 2.5 min |
| `qemu` | `build/qemu/qemu-system-riscv64`, `qemu-riscv64` | under 1 min |

After editing a source file, rebuild one step, for example
`scripts/build.sh gcc`: 1–2 minutes for a change in the RISC-V back end.

Notes that save time:

- Building only the compiler avoids the two-hour full riscv-gnu-toolchain
  build (GCC built twice plus glibc). Bare-metal programs need only
  newlib and libgcc.
- newlib and libgcc are built with `-mcmodel=medany` because the test
  images live at `0x80000000`. With the default `medlow`, linking fails
  with "relocation truncated to fit: R_RISCV_HI20".
- GCC writes multi-megabyte temporaries. The scripts point `TMPDIR` at
  `build/tmp`, so a small or quota-limited `/tmp` does not break the
  build.

Each step also has its own target, so a change in one tree rebuilds only
that tree: `make build-binutils build-gcc build-newlib build-libgcc
build-dtc build-spike build-qemu` (and `make build-info` for the record).
`make build` runs all of them in order. A configured build directory is
reused, so a second run of the same target is incremental.

### 3.1 Targets that only name a script

Each of these targets runs exactly one existing script, so the command is
also visible from `make`:

| Target | Runs |
|--------|------|
| `make setup` | `scripts/setup.sh` |
| `make artifacts` | `scripts/artifacts.sh` |
| `make patches-apply` | `scripts/patches.sh apply` |
| `make patches-export` | `scripts/patches.sh export` |
| `make patches-remove` | `scripts/patches.sh remove` |
| `make patches-restore` | `scripts/patches.sh restore` |
| `make patches-check` | `scripts/patches.sh check` |
| `make patches-status` | `scripts/patches.sh status` |

The six `patches-*` targets are one static pattern rule and cover every
component; for one component run the script directly, for example
`scripts/patches.sh apply gcc`. The shell scripts stay: they probe the
environment (packages, `versions.env` pins, `TMPDIR`, the toolchain paths)
and print the distribution-specific fix, which make cannot do without a
second copy of that logic. `tests/test_make_targets.py` checks what each
target runs with `make -n`; no toolchain is needed.

## 4. Test

```bash
make check
```

| Target | What it proves | Count |
|--------|----------------|-------|
| `check-core` | `attn_core.h` matches the independent float64 model on 13 configurations (f32, bf16 in/out, causal, mask, GQA, MQA, explicit scale, no bias); reserved configurations are rejected; the C structs match the Python layout; the Spike, QEMU and libgcc copies are identical | 32 |
| `check-gcc` | builtins on rv32/rv64 under three pipeline models, `__builtin_attn` with and without Xattn, error without Xattn, `__riscv_xattn`, the five recognized forms (one with no flags at all), the six rejected forms with their reasons, the `attn` RTL code (four register uses, scheduling across it) | 25 |
| `check-sim` | on QEMU and on Spike (bare metal), 14 checks each: every byte of `Y` equals the host core for 7 configurations; reserved configuration traps with `mcause 2` (bad `e % h`, `n > 4096`, `e > 2048`); a load fault and a descriptor fault trap with `mtval` = the bad address and `Y` untouched; re-execution completes; a misaligned descriptor either traps or completes with identical bytes; `attn` without Xattn traps. On QEMU Linux user mode (`qemu-riscv64`): the 7 configurations again | 2 x 15 + 7 |
| `check-recog` | recognized `attn` vs plain loops at run time on both simulators, for three source forms; libgcc `__attn` (`__builtin_attn` without Xattn) vs the loops; guard-failing cases run the loops bit-exactly | 7 + 6 |
| `check-three-way` | the same bare-metal image on QEMU and on Spike, compared with the host core case by case: prints the largest absolute difference and requires it to be exactly 0 for all 7 configurations | 1 |
| `check-sched` | `attn` is scheduled under every pipeline model of this GCC port — 13 models, 26 `-mtune` names read from `gcc/gcc/config/riscv/riscv-cores.def`; for each, both `attn` lines carry the `riscv_attn_di` annotation in `-dp` output | 26 |
| `check-demo` | `demo/mha_plain.c` at `-O2`: with `-fno-tree-loop-attn` the loops stay (`.ATTN` 0, `attn` 0); with the default the GIMPLE has one `.ATTN` and the assembly one `attn`, and the loops survive only as the guard's fallback (same 6 float ops, 333 → 375 instructions; the gain is run time: 508421 → 991 instructions executed) | 1 |

`make check` runs each target through `scripts/check-summary.sh`, so the last
thing printed is one row per target (name, pass, fail, seconds) and a `total`
row. A failing target does not stop the rest, and any failed row makes the
whole target exit non-zero:

```
target               pass fail   time
------------------   ---- ---- ------
check-build-info        1    0     0s
...
total                  10    0   112s
```

Expected tail of the output:

```
attn_test: all passed
PASS attn_without_xattn_is_illegal
recog_test: all passed
```

`check-three-way` prints the comparison it asserts, so a difference is visible
rather than only fatal:

```
case                               QEMU        Spike  verdict
bf16_bf16_causal                      0            0  PASS
f32_causal_mask                       0            0  PASS
f32_gqa                               0            0  PASS
```

## 5. Use it

```bash
T=out/toolchain/bin
# builtin
cat > t.c <<'EOF'
#include "attn.h"
void f (float *y, const float *x, const struct attn_weights *w,
        const struct attn_cfg *c) { attn_mha (y, x, w, c); }
EOF
$T/riscv64-unknown-elf-gcc -march=rv64gc_xattn -O2 -Iinclude -S t.c -o - | grep attn

# recognizer
$T/riscv64-unknown-elf-gcc -O2 -fopt-info-loop -S demo/mha_plain.c -o - | grep -w attn

# run a bare-metal ELF
out/spike/bin/spike --isa=rv64gc_xattn prog.elf
build/qemu/qemu-system-riscv64 -M virt -bios none -nographic \
    -cpu rv64,xattn=on -kernel prog.elf
```

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `internal compiler error: in riscv_sched_variable_issue` | an instruction pattern with type `unknown` | give it a type that has a reservation (`xattn.md` does) |
| `relocation truncated to fit: R_RISCV_HI20` | libraries built for `medlow`, image at `0x80000000` | `scripts/build.sh newlib libgcc` |
| `Plugin "imsic_mmio" already registered` (Spike) | extension object dropped by the linker, Spike loaded `libcustomext.so` | register the factory in `riscv/extensions.cc` |
| `configure: error: device-tree-compiler not found` | no `dtc` | install it or `scripts/build.sh dtc` |
| `Disk quota exceeded` writing `/tmp/cc*.s` | small `/tmp` | `export TMPDIR=$PWD/build/tmp` |
| assembler: `extension 'xattn' required` | `-march` lacks `_xattn` | add it |
| attn traps with `mcause 2` | Xattn disabled in the simulator, or a reserved configuration | `--isa=..._xattn` / `-cpu ...,xattn=on`; check `docs/spec.md` section 4 |
| recognizer says `exponential is not a const call` | explicit `-fmath-errno` | drop it |
| recognizer says `output may alias an input` | aliasing not provable | `restrict` on the pointers |

## 7. Support matrix

What works where. "Tested" means the command runs in CI or was run on the
machine named; everything else is untested or not supported.

| Host OS | Status | Evidence |
|---------|--------|----------|
| Linux x86_64 | supported and tested | CI runner `ubuntu-24.04` in `.github/workflows/ci.yml` (job `fast`) and `.github/workflows/full.yml` (job `build`) |
| Windows / MSYS2 | documented only, not CI-tested | measured on this machine (section 7.2); no CI job runs on Windows |
| macOS | untested, unprovable here | no machine available; no CI job runs on macOS |
| RISC-V silicon | not supported | simulator-only: Spike and QEMU as built from the submodules; the project ships no hardware path |

### 7.1 Toolchain

| Compiler | Use |
|----------|-----|
| GCC from the pinned submodule | builds all target code; `versions.env` pins `GCC_SHA=041359f347cb1d48622a2c96934d06d514de7a36`; installed at `out/toolchain/bin/riscv64-unknown-elf-gcc` |
| host `gcc` | not used to build target code |
| host `clang` | only for the bare-metal `.insn` path: `tests/baremetal/Makefile` defaults to `CC ?= clang` with `--target=riscv64-unknown-elf -fuse-ld=lld` |

`make check-sim` does not use the host compiler: it passes
`CC=$(CURDIR)/out/toolchain/bin/riscv64-unknown-elf-gcc`.

### 7.2 Measured on this host

Windows / MSYS2, 20 cores. Re-run for this section:

| Command | Output |
|---------|--------|
| `gcc --version` | `gcc.exe (Rev7, Built by MSYS2 project) 16.2.0` |
| `clang --version` | NOT FOUND: no `clang` binary on PATH or in `/c/msys64/ucrt64/bin`, `/c/msys64/mingw64/bin`, `/c/Program Files/LLVM/bin` |
| `python3 --version` | `Python 3.15.0` |
| `.venv/bin/python -c 'import numpy, pytest; print(numpy.__version__, pytest.__version__)'` | `2.5.5 9.2.0` |
| `make --version` | `GNU Make 4.4.1` |
| `cmake --version` | `4.4.5` |
| `ninja --version` | `1.13.2.git.kitware.jobserver-pipe-1` |
| `git --version` | `2.55.0.windows.5` |
| `nproc` | `20` |
| `df -h .` | size `476G`, available `159G` |
| `uname -srm` | `MSYS_NT-10.0-26300 3.6.10-5a1665c8.x86_64 x86_64` |

### 7.3 Python

The tests need `numpy` and `pytest`; the lint and shell checks need `ruff`,
`mypy` and `shellcheck-py`. The `$(PY)` rule in the `Makefile` installs all
of them from `requirements.lock` with `--require-hashes`, so a version or a
hash that moves fails the install instead of the test run, then installs the
package itself with `-e . --no-deps`. Regenerate the lock with the commands
in its header after changing a pin in `pyproject.toml`. CI uses the runner's
`python3` and pip-installs `numpy` and `pytest`
(`.github/workflows/ci.yml`); its Ubuntu wheels are not in this
Windows-generated lock. The pinned QEMU `configure` requires
Python 3.12 or newer (comment in `.github/workflows/full.yml` lines 73-74;
section 1 targets Ubuntu 24.04), so CI's runner image supplies 3.12 or
newer and 3.12 is the enforced floor.

### 7.4 Disk budget

About 15 GB of build output plus about 6 GB of sources, so about 21 GB peak.
Section 1 says "about 15 GB, most of it the full GCC history"; section 2
says the full history is "~6 GB". Split: submodule git objects about 6 GB,
`build/` plus `out/` about 15 GB. This is derived from the document, not
remeasured: a `du` over the trees was killed after several minutes on
Windows because it was not cheap there, so no measured figure is claimed.

### 7.5 Time budget

The per-step times in section 3 add up to about 13 minutes (binutils ~3 min,
gcc 5.3 min, newlib 13 s, libgcc ~1 min, dtc seconds, spike 2.5 min, qemu
under 1 min), and the README says "about 15 minutes on 16 cores". The total
is DERIVED from the documented per-step times on this 20-core host, not
remeasured: only binutils was actually built here (`out/toolchain/bin/riscv64-unknown-elf-as`
exists; there is no cross gcc, no spike and no qemu binary).

### 7.6 What CI enforces

| Workflow | Job | `runs-on` | `timeout-minutes` | Commands |
|----------|-----|-----------|-------------------|----------|
| `.github/workflows/ci.yml` | `fast` | `ubuntu-24.04` | `15` | `scripts/patches.sh apply binutils gcc spike qemu`, `scripts/patches.sh status`, `python3 -m pytest -q tests/`, `shellcheck -x scripts/*.sh`; no toolchain build |
| `.github/workflows/full.yml` | `build` | `ubuntu-24.04` | `120` | `scripts/patches.sh apply`, `scripts/build.sh` (six steps), `make check`, artifact upload |

CI does not enforce: Windows or MSYS2, macOS, a clang-only build (full.yml
installs no clang and `make check-sim` uses the built gcc), RISC-V silicon,
or any build time or disk budget.

See also: `README.md` for the quick start, `docs/spec.md` for the ISA.
