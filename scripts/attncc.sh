#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Compile a C file or a bare code excerpt with the Xattn toolchain, stage by
# stage, and show what the compiler made of it.
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
# Every stage prints one line: "== stage <name> <seconds>s <verdict>".
# --run adds the link and a Spike run: both versions are called on the same
# random inputs (ATTN_N, ATTN_E, ATTN_H, default 16 32 4) and the stage
# reports the instructions each call executed and the largest difference.
# It expects the signature of demo/mha_plain.c.  Bare-metal Spike loads at
# 0x80000000, so --run adds -mcmodel=medany to every compile.
# Exit status 0 when at least one attn was generated (and, with --run,
# the two versions agree).

set -euo pipefail

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  TMPDIR     scratch dir (default: <repo>/build/tmp)\n'
  printf '  ATTN_N ATTN_E ATTN_H  sizes for --run (default 16 32 4)\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  --run) : ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
BIN=$REPO/out/toolchain/bin
CC=$BIN/riscv64-unknown-elf-gcc
OBJDUMP=$BIN/riscv64-unknown-elf-objdump
export TMPDIR=${TMPDIR:-$REPO/build/tmp}
export PATH=$REPO/out/host/bin:$PATH
mkdir -p "$TMPDIR"

RUN=0 MODEL=()
[ "${1:-}" = --run ] && { RUN=1; MODEL=(-mcmodel=medany); shift; }
[ $# -ge 1 ] || { usage; exit 2; }
SRC=$(realpath "$1")
OUT=${2:-$TMPDIR/$(basename "${SRC%.c}").o}
[ -x "$CC" ] || { echo "no toolchain at $BIN; run scripts/setup.sh" >&2; exit 1; }
"$CC" -fno-tree-loop-attn -E -x c /dev/null -o /dev/null 2> /dev/null || {
  echo "this toolchain has no Xattn (scripts/xattn.sh restore puts it back)" >&2
  exit 1; }

# One line per stage: name, wall time, verdict.
STAGE_T0=0
stage_begin() { STAGE_T0=$(date +%s%N); }
stage_end() { # NAME VERDICT
  local ns=$(( $(date +%s%N) - STAGE_T0 ))
  printf '== stage %-9s %d.%03ds %s\n' "$1" $((ns / 1000000000)) \
    $((ns % 1000000000 / 1000000)) "$2"
}

EXCERPT=$TMPDIR/attncc-excerpt.c
stage_begin
{ printf '#include <math.h>\n#include <stdlib.h>\n#line 1 "%s"\n' "$SRC"
  cat "$SRC"; } > "$EXCERPT"
stage_end extract PASS

# compile: ask GCC what it did, and compile the excerpt twice: once with the
# recognizer (the default) and once with it off, for the instruction counts.
ASS=${OUT%.o}.s
LOOPS_ASS=$TMPDIR/attncc-loops.s
stage_begin
if "$CC" -O2 "${MODEL[@]}" -fopt-info-loop-optimized -fopt-info-loop-missed \
     -S "$EXCERPT" -o "$ASS" 2> "$TMPDIR/attncc-report.txt" \
   && "$CC" -O2 "${MODEL[@]}" -fno-tree-loop-attn -S "$EXCERPT" \
     -o "$LOOPS_ASS"; then
  stage_end compile PASS
else
  stage_end compile FAIL
  sed 's/^/  /' "$TMPDIR/attncc-report.txt" >&2
  exit 1
fi
grep -E 'attention' "$TMPDIR/attncc-report.txt" || true

# assemble: the two .s files into .o files.
LOOPS_O=$TMPDIR/attncc-loops.o
stage_begin
if "$CC" "${MODEL[@]}" -c "$ASS" -o "$OUT" \
   && "$CC" "${MODEL[@]}" -c "$LOOPS_ASS" -o "$LOOPS_O"; then
  stage_end assemble PASS
else
  stage_end assemble FAIL
  exit 1
fi

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
    "$(count "$LOOPS_O" "$f" '^\s+[0-9a-f]+:\s')"
done

if [ "$total" -gt 0 ]; then
  echo
  echo "== disassembly around attn ($OUT)"
  "$OBJDUMP" -d "$OUT" | grep -B6 -A2 -P '\sattn\s'
  echo
  echo "The loops that remain run only when the sizes fail the guard"
  echo "(n or e outside the instruction's limits, e % h != 0); every valid"
  echo "size executes the single attn above."
else
  echo
  echo "no attn generated; the report above says which step did not match"
  exit 1
fi

[ $RUN = 1 ] || exit 0

# run: build the recognizer-off object under a second name, link both into
# the bare-metal driver, and execute it on Spike.
ELF=$TMPDIR/attncc-run.elf
RUN_LOOPS=$TMPDIR/attncc-run-loops.o
stage_begin
if "$CC" -O2 "${MODEL[@]}" -fno-tree-loop-attn -D"$fn=${fn}_loops" \
     -c "$EXCERPT" -o "$RUN_LOOPS" \
   && "$CC" -O2 "${MODEL[@]}" -DBM_SPIKE -DFN="$fn" \
     -I"$REPO/tests/baremetal" \
     -DATTN_N="${ATTN_N:-16}" -DATTN_E="${ATTN_E:-32}" \
     -DATTN_H="${ATTN_H:-4}" \
     -nostartfiles -T "$REPO/tests/baremetal/link.ld" -static \
     -Wl,--no-warn-rwx-segments "$REPO/tests/baremetal/crt.S" \
     "$REPO/tests/baremetal/bm.c" "$REPO/scripts/attncc-driver.c" \
     "$OUT" "$RUN_LOOPS" -lm -lc -lgcc -o "$ELF"; then
  stage_end link PASS
else
  stage_end link FAIL
  exit 1
fi
echo
echo "== run on Spike: $fn(n=${ATTN_N:-16}, e=${ATTN_E:-32}, h=${ATTN_H:-4})"
RUN_LOG=$TMPDIR/attncc-run.txt
stage_begin
if "$REPO/out/spike/bin/spike" --isa=rv64gc_xattn "$ELF" | tee "$RUN_LOG"; then
  stage_end run PASS
else
  stage_end run FAIL
  exit 1
fi
stage_begin
if grep -q 'PASS' "$RUN_LOG"; then
  stage_end compare PASS
else
  stage_end compare FAIL
  exit 1
fi

