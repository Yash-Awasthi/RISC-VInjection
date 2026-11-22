#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Remove Xattn from the toolchain and simulators, or put it back.
#
#   scripts/xattn.sh remove    upstream sources, rebuild: no attn anywhere
#   scripts/xattn.sh restore   branch xattn again, rebuild
#   scripts/xattn.sh status    which one is built
#
#   --no-rebuild skips scripts/build.sh and the toolchain check (used by
#   tests/test_xattn.py).
#
# Nothing is deleted: the work stays on branch xattn in each submodule and
# in patches/.  After "remove", GCC rejects -march=..._xattn, the assembler
# does not know attn, Spike and QEMU have no Xattn, and plain C attention
# compiles to loops.  The default -march follows (rv64gc / rv64gc_xattn).
# Removing an already-removed tree is an error, not a no-op; after a
# successful remove every submodule must be clean, or the change leaked
# outside branch xattn.

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
P=$REPO/scripts/patches.sh
COMPONENTS=(binutils gcc spike qemu)

case ${1:-} in
  remove|restore)
    verb=$1
    [ "${2:-}" = "--no-rebuild" ] && rebuild=0 || rebuild=1
    "$P" "$verb"
    if [ "$verb" = remove ]; then
      # Content, not stat data: a CRLF checkout reports stat-only "M" for
      # files whose blob is the index's, which is not a leaked change.
      for c in "${COMPONENTS[@]}"; do
        untracked=$(git -C "$REPO/$c" ls-files --others --exclude-standard)
        if [ -n "$untracked" ] || ! git -C "$REPO/$c" diff --quiet -- .; then
          echo "error: $c is dirty after remove; the change leaked" \
            "outside branch xattn" >&2
          [ -z "$untracked" ] || printf '%s\n' "$untracked" >&2
          git -C "$REPO/$c" diff --stat >&2
          exit 1
        fi
      done
    fi
    if [ "$rebuild" -eq 1 ]; then
      "$REPO/scripts/build.sh" binutils gcc libgcc spike qemu
      "$0" status
    fi ;;
  status)
    "$P" status
    if "$REPO/out/toolchain/bin/riscv64-unknown-elf-gcc" -march=rv64gc_xattn \
	 -E -x c /dev/null -o /dev/null 2> /dev/null; then
      echo "built toolchain: Xattn present"
    else
      echo "built toolchain: Xattn absent"
    fi ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
