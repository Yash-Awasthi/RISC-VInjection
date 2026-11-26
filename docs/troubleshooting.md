# Troubleshooting

`scripts/diagnose.sh LOG` reads a build log, finds the first known failure
and prints one line:

```
<file>:<line>: <what>: <fix>
```

Exit 0 means no known failure, 1 means it reported one, 2 is a usage or
file error. The fixtures in `tests/data/failures/` pin each pattern and
`tests/test_diagnose.py` pins the exact output.

| Message pattern | File:line it comes from | Fix |
|-----------------|-------------------------|-----|
| `Unable to locate package`, `E: Package ... has no installation candidate`, or `command not found` for flex, bison, gperf, texinfo or makeinfo | `scripts/setup.sh:40` | Install the list in `docs/build-and-test.md` section 1, or run `scripts/setup.sh`; it prints the package command for apt, dnf, pacman, zypper or brew. |
| `Patch failed at`, `error: patch failed:`, `error: could not apply`, or the `git am --continue` hint | `scripts/patches.sh:53` | Reset the component to the pinned commit and rerun `scripts/patches.sh apply`; `docs/build-and-test.md` section 2 gives the sequence. |
| `not a git repository`, or `No such file or directory` naming a `gcc/`, `binutils/`, `spike/`, `qemu/` or `newlib/` path | `scripts/setup.sh:86` | Run `git submodule update --init gcc binutils spike qemu newlib`; `docs/build-and-test.md` section 2. |
| `riscv64-unknown-elf-gcc: not found` (also as, ld, objdump, ar, ranlib, nm or readelf), or a toolchain version-mismatch message | `scripts/build.sh:33` | Rebuild with `scripts/build.sh` and check the pins in `versions.env`; `docs/build-and-test.md` section 3. |
| `unrecognized argument in option '-march=`, `-march=...: cannot`, or `unsupported ISA extension` | `docs/build-and-test.md:170` | Pass the gcc `-march=rv64gc_xattn` flag; `docs/build-and-test.md` section 5 shows the full command. |
