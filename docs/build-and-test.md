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

## 4. Test

```bash
make check
```

| Target | What it proves | Count |
|--------|----------------|-------|
| `check-core` | `attn_core.h` matches the independent float64 model on 13 configurations (f32, bf16 in/out, causal, mask, GQA, MQA, explicit scale, no bias); reserved configurations are rejected; the C structs match the Python layout; the Spike, QEMU and libgcc copies are identical | 32 |
| `check-gcc` | builtins on rv32/rv64 under three pipeline models, `__builtin_attn` with and without Xattn, error without Xattn, `__riscv_xattn`, the five recognized forms (one with no flags at all), the six rejected forms with their reasons, the `attn` RTL code (four register uses, scheduling across it) | 25 |
| `check-sim` | on QEMU and on Spike (bare metal): every byte of `Y` equals the host core for 7 configurations; reserved configuration traps with `mcause 2`; a load fault traps with `mcause 5` and the right `mtval`, `Y` untouched; re-execution completes; `attn` without Xattn traps. On QEMU Linux user mode (`qemu-riscv64`): the 7 configurations again | 2 x 11 + 7 |
| `check-recog` | recognized `attn` vs plain loops at run time on both simulators, for three source forms; libgcc `__attn` (`__builtin_attn` without Xattn) vs the loops; guard-failing cases run the loops bit-exactly | 7 + 6 |

Expected tail of the output:

```
attn_test: all passed
PASS attn_without_xattn_is_illegal
recog_test: all passed
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
