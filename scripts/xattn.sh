#!/usr/bin/env bash
# Remove Xattn from the toolchain and simulators, or put it back.
#
#   scripts/xattn.sh remove    upstream sources, rebuild: no attn anywhere
#   scripts/xattn.sh restore   branch xattn again, rebuild
#   scripts/xattn.sh status    which one is built
#
# Nothing is deleted: the work stays on branch xattn in each submodule and
# in patches/.  After "remove", GCC rejects -march=..._xattn, the assembler
# does not know attn, Spike and QEMU have no Xattn, and plain C attention
# compiles to loops.  The default -march follows (rv64gc / rv64gc_xattn).

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
P=$REPO/scripts/patches.sh

case ${1:-} in
  remove|restore)
    "$P" "$1"
    "$REPO/scripts/build.sh" binutils gcc libgcc spike qemu
    "$0" status ;;
  status)
    "$P" status
    if "$REPO/out/toolchain/bin/riscv64-unknown-elf-gcc" -march=rv64gc_xattn \
	 -E -x c /dev/null -o /dev/null 2> /dev/null; then
      echo "built toolchain: Xattn present"
    else
      echo "built toolchain: Xattn absent"
    fi ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
