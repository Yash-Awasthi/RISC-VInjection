#!/usr/bin/env bash
# Compile a C file or a bare code excerpt with the Xattn toolchain and show
# what the compiler made of it.
#
#   scripts/attncc.sh [--run] FILE.c [OUT.o]
#
# FILE may be a bare excerpt: no #include lines and no main().  The script
# puts <math.h> and <stdlib.h> in front of it (standard headers only, line
# numbers unchanged), compiles at plain -O2 with no other flags, then prints
#   - the compiler's report (replaced with attn, or why not),
#   - the disassembly of every function that contains attn,
#   - per function: attn count and total instruction count, compared with
#     the same code compiled with the recognizer off.
# --run also links both versions into one bare-metal program for Spike,
# calls them on the same random inputs (ATTN_N, ATTN_E, ATTN_H, default
# 16 32 4) and prints the instructions each call executed (minstret) and
# the largest difference between their outputs.  It expects the
# signature of demo/mha_plain.c.  Bare-metal Spike loads at 0x80000000,
# so --run adds -mcmodel=medany to every compile.
# Exit status 0 when at least one attn was generated (and, with --run,
# the two versions agree).

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
BIN=$REPO/out/toolchain/bin
CC=$BIN/riscv64-unknown-elf-gcc
OBJDUMP=$BIN/riscv64-unknown-elf-objdump
export TMPDIR=${TMPDIR:-$REPO/build/tmp}
export PATH=$REPO/out/host/bin:$PATH
mkdir -p "$TMPDIR"

RUN=0 MODEL=()
[ "${1:-}" = --run ] && { RUN=1; MODEL=(-mcmodel=medany); shift; }
[ $# -ge 1 ] || { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
SRC=$(realpath "$1")
OUT=${2:-$TMPDIR/$(basename "${SRC%.c}").o}
[ -x "$CC" ] || { echo "no toolchain at $BIN; run scripts/setup.sh" >&2; exit 1; }
"$CC" -fno-tree-loop-attn -E -x c /dev/null -o /dev/null 2> /dev/null || {
  echo "this toolchain has no Xattn (scripts/xattn.sh restore puts it back)" >&2
  exit 1; }

compile() { # compile OUT EXTRA-FLAGS...
  local out=$1
  shift
  { printf '#include <math.h>\n#include <stdlib.h>\n#line 1 "%s"\n' "$SRC"
    cat "$SRC"; } | "$CC" -O2 "${MODEL[@]}" "$@" -x c -c - -o "$out"
}

echo "== compile: riscv64-unknown-elf-gcc -O2 $(basename "$SRC")"
compile "$OUT" -fopt-info-loop-optimized -fopt-info-loop-missed 2>&1 \
  | grep -E 'attention' || true
compile "$TMPDIR/attncc-loops.o" -fno-tree-loop-attn

run_on_spike() {
  local bm=$REPO/tests/baremetal elf=$TMPDIR/attncc-run.elf
  compile "$TMPDIR/attncc-run-loops.o" -fno-tree-loop-attn -D"$fn=${fn}_loops"
  "$CC" -O2 -mcmodel=medany -DBM_SPIKE -DFN="$fn" -I"$bm" \
    -DATTN_N="${ATTN_N:-16}" -DATTN_E="${ATTN_E:-32}" -DATTN_H="${ATTN_H:-4}" \
    -nostartfiles -T "$bm/link.ld" -static -Wl,--no-warn-rwx-segments \
    "$bm/crt.S" "$bm/bm.c" "$REPO/scripts/attncc-driver.c" \
    "$OUT" "$TMPDIR/attncc-run-loops.o" -lm -lc -lgcc -o "$elf"
  echo
  echo "== run on Spike: $fn(n=${ATTN_N:-16}, e=${ATTN_E:-32}, h=${ATTN_H:-4})"
  "$REPO/out/spike/bin/spike" --isa=rv64gc_xattn "$elf"
}

count() { # count OBJ FUNC PATTERN
  "$OBJDUMP" -d --no-show-raw-insn "$1" \
    | awk -v f="<$2>:" '$2 == f { on = 1; next } /^[0-9a-f]+ <[^.]/ { on = 0 } on' \
    | grep -cP "$3" || true
}

funcs=$("$OBJDUMP" -t "$OUT" | awk '$3 == "F" { print $NF }')
total=0
fn=
echo
echo "== result"
printf '%-24s %6s %18s %18s\n' function attn "insns (attn on)" "insns (attn off)"
for f in $funcs; do
  n=$(count "$OUT" "$f" '^\s+[0-9a-f]+:\s+attn\s')
  total=$((total + n))
  [ "$n" -gt 0 ] && [ -z "$fn" ] && fn=$f
  printf '%-24s %6s %18s %18s\n' "$f" "$n" \
    "$(count "$OUT" "$f" '^\s+[0-9a-f]+:\s')" \
    "$(count "$TMPDIR/attncc-loops.o" "$f" '^\s+[0-9a-f]+:\s')"
done

if [ "$total" -gt 0 ]; then
  echo
  echo "== disassembly around attn ($OUT)"
  "$OBJDUMP" -d "$OUT" | grep -B6 -A2 -P '\sattn\s'
  echo
  echo "The loops that remain run only when the sizes fail the guard"
  echo "(n or e outside the instruction's limits, e % h != 0); every valid"
  echo "size executes the single attn above."
  [ $RUN = 1 ] || exit 0
  run_on_spike
  exit $?
fi
echo
echo "no attn generated; the report above says which step did not match"
exit 1
