# Implementation, layer by layer

Each upstream project is a git submodule pinned to an official commit. The
Xattn changes to it are a patch series in `patches/<project>/`.
`scripts/patches.sh apply` turns them into a local branch `xattn`, and
`scripts/patches.sh export` writes them back. Every file below is
relative to its submodule.

| Submodule | Upstream | Branch at the pinned commit |
|-----------|----------|-----------------------------|
| `binutils` | github.com/gnutools/binutils-gdb (mirror of sourceware) | `binutils-2_47-branch` |
| `gcc` | github.com/gcc-mirror/gcc (mirror of gcc.gnu.org) | `releases/gcc-16` (GCC 16.2.1) |
| `spike` | github.com/riscv-software-src/riscv-isa-sim | `master` |
| `qemu` | github.com/qemu/qemu (official mirror) | `master` |
| `newlib` | github.com/cygwin/cygwin (newlib and cygwin share a repository) | `master` |

Do not use the archived `riscvarchive/riscv-gcc` and
`riscvarchive/riscv-binutils-gdb` (formerly `riscv/riscv-gcc` and
`riscv/riscv-binutils-gdb`). Those forks stopped in 2022/2023. RISC-V
development now happens directly in GCC and binutils, and
riscv-gnu-toolchain points at the repositories above.

## The shared definition

`include/attn_abi.h` holds the encoding, flags, limits and descriptor
structs. `include/attn_core.h` holds the arithmetic. It reaches guest
memory only through a small table of load and store callbacks, so the
same file runs in three places:

| Copy | Memory callbacks | A fault becomes |
|------|------------------|-----------------|
| `spike/riscv/attn_core.h` | `mmu_t::load/store` | a C++ exception (`trap_t`) |
| `qemu/target/riscv/attn_core.h` | `cpu_ld*/st*_data_ra` | `cpu_loop_exit_restore` (longjmp) |
| `include/attn_core.h` on the host | a flat byte array | a status code |

A fault can leave the function at any load. That is why the core owns no
resources: the caller provides the scratch memory, and Spike and QEMU keep
a grow-only per-thread buffer. It also contains
`#pragma GCC optimize ("fp-contract=off")` (or the clang equivalent), so
no compiler can fuse a multiply and an add and change the result.
`tests/test_core.py` fails if the copies drift from `include/`.

## binutils

| File | Change |
|------|--------|
| `include/opcode/riscv-opc.h` | `MATCH_ATTN`, `MASK_ATTN`, `DECLARE_INSN(attn, ...)` |
| `include/opcode/riscv.h` | `INSN_CLASS_XATTN` |
| `opcodes/riscv-opc.c` | `{"attn", 0, INSN_CLASS_XATTN, "d,s,t,r", ...}` among the vendor tables. `d,s,t,r` means rd, rs1, rs2, rs3 |
| `bfd/elfxx-riscv.c` | `xattn` version 1.0 in the vendor extension table, plus its two cases in `riscv_multi_subset_supports` and `riscv_multi_subset_supports_ext` |
| `gas/testsuite/gas/riscv/x-attn*.{s,d,l}` | encodings on rv64 and rv32, and the error without the extension |

Because the instruction belongs to `INSN_CLASS_XATTN` and not to the base
ISA, the assembler accepts it only with `_xattn` in `-march`. objdump
shows it whenever the ELF attributes say the object uses Xattn.

## GCC

| File | Change |
|------|--------|
| `config/riscv/riscv-ext-xattn.def` | the extension: name, version 1.0, flag group. `riscv-ext.opt` and `doc/riscv-ext.texi` are regenerated from it (`make riscv-regen`, or by hand with `gen-riscv-ext-opt` / `gen-riscv-ext-texi`) |
| `config/riscv/riscv-ext.def`, `t-riscv` | include the new `.def`, list it in `RISCV_EXT_DEFS` |
| `config/riscv/xattn.md` | `riscv_attn_<mode>`: `unspec_volatile:X` over four register operands plus `(clobber (mem:BLK (scratch)))`. Also insn type `attn` with a tune-independent reservation |
| `config/riscv/riscv.md` | `UNSPECV_XATTN`, the `attn` type, `(include "xattn.md")` |
| `config/riscv/riscv-ftypes.def` | `void (void *, const void *, const void *, const void *)` |
| `config/riscv/xattn.def`, `riscv-builtins.cc` | `__builtin_riscv_attn` for RV32 and RV64 (`AVAIL attn32/attn64`), and `riscv_attn_builtin_decl ()` for the recognizer |
| `config/riscv/riscv-attn-recog.cc` | the recognizer (see `recognizer.md`) |
| `config/riscv/riscv-passes.def`, `riscv-protos.h`, `riscv.opt`, `config.gcc` | register the pass after `pass_tree_loop_init`; add `-mattn-recognize`; build `riscv-attn-recog.o` |
| `testsuite/gcc.target/riscv/xattn-*.c` | builtin, feature macro, missing extension, several `-mtune` models, and the recognizer cases |

`__riscv_xattn` needs no code of its own. GCC defines `__riscv_<ext>` for
every enabled extension.

**Why an `attn` insn type?** The RISC-V scheduler asserts that every
instruction has a known type with a reservation in the active pipeline
model (`riscv_sched_variable_issue`). Type `unknown` crashes the compiler
with an internal error as soon as scheduling is on. The earlier version of
this project hid that with `-fno-schedule-insns`. Vendor types such as
`sf_vc` are not covered by every model either. The fix copies how `ghost`
works: one `define_insn_reservation` that reserves no unit and so applies
under every `-mtune`. `xattn-3.c` to `xattn-5.c` compile with three
different pipeline models.

**Why `unspec_volatile` with a memory clobber?** The registers carry only
addresses. Through the descriptors, the instruction reads memory nobody
can name in RTL. The clobber makes it a full memory barrier, so no load or
store moves across it. At GIMPLE level the builtin is an ordinary call
whose pointer arguments escape, so alias analysis already treats it
conservatively.

## Spike

| File | Change |
|------|--------|
| `riscv/xattn.cc` | `extension_t` named `attn`, with one `insn_desc_t` (MATCH/MASK, the same function for every XLEN/RVE/logging variant) and a disassembler entry. RVE: registers above x15 trap |
| `riscv/extensions.cc` | a built-in table entry `{"attn", xattn_create}`. Spike maps `--isa=..._xattn` to extension `attn` |
| `riscv/riscv.mk.in` | compile `xattn.cc` into libriscv |

The usual `REGISTER_EXTENSION` macro relies on a static constructor. The
linker drops an object file from `libriscv.a` when nothing references it,
and then Spike falls back to `dlopen("libcustomext.so")`. That loads a
second copy of libriscv and aborts with "Plugin imsic_mmio already
registered". Naming the factory in `extensions.cc` keeps the object
linked.

## QEMU

| File | Change |
|------|--------|
| `target/riscv/xattn.decode` | decodetree pattern `attn ..... 11 ..... ..... 001 ..... 1111011` |
| `target/riscv/tcg/insn_trans/trans_xattn.c.inc` | `trans_attn`: checks `ext_xattn`, saves the opcode for `mtval` (`decode_save_opc`), calls the helper with the four zero-extended registers |
| `target/riscv/tcg/attn_helper.c` | `helper_attn`: runs `attn_core.h` through `cpu_ld*/st*_data_ra`. Addresses go through `adjust_addr` for pointer masking. Reserved configurations raise `RISCV_EXCP_ILLEGAL_INST` |
| `target/riscv/{cpu.c,cpu_cfg.h,cpu_cfg_fields.h.inc}` | the `ext_xattn` flag, its predicate and `ISA_EXT_DATA_ENTRY(xattn, ...)`, which also creates the `xattn=on` CPU property and puts `xattn` in the device-tree ISA string |
| `target/riscv/{helper.h,meson.build,tcg/meson.build,tcg/translate.c}` | helper prototype, decoder generation, decoder table entry |
| `disas/riscv-xattn.{c,h}`, `disas/riscv.{c,h}`, `disas/meson.build` | disassembly for `-d in_asm` and the gdbstub. Includes a new format character `9` for an integer rs3 (the existing `6` prints a float register) |

## Tests and tools

| Path | Purpose |
|------|---------|
| `tools/attn_model.py` | independent float64 model, descriptor packing, encoding |
| `tools/attn_host.py`, `tests/host/attn_host.c` | `attn_core.h` on the host through ctypes |
| `tests/test_core.py` | core vs model on 13 configurations, reserved configurations, layout, determinism, copies in sync |
| `tests/baremetal/` | start-up code, HTIF/UART output, trap handler. `attn_test.c` checks every byte of `Y` against the host core on Spike and QEMU, plus the illegal trap, a precise load fault (`mtval`), re-execution, and a trap without the extension |
| `tests/recog/` | recognized vs plain loops at run time |
| `tests/run_dg.py` | runs GCC testsuite directives without DejaGnu |
| `scripts/find_opcodes.py`, `scripts/xinsn.py` | see `new-instruction.md` |
