#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the host core three times: once plain, once under AddressSanitizer,
# once under UndefinedBehaviorSanitizer, and run every frozen vector through
# each.  All three use -ffp-contract=off -O1 -g.
#
#   scripts/sanitize.sh
#
# One row per vector per sanitizer:
#
#   asan  f32_baseline                OK
#   ubsan f32_baseline                OK
#
# OK means the sanitizer's Y is bit-identical to the plain build's and to the
# frozen hash.  LIBC means it is bit-identical to the plain build but the
# plain build itself differs from the frozen hash: one frozen value
# (f32_gqa_scale) was recorded on a C library whose expf rounds differently,
# so the divergence is named, not hidden.  MISMATCH means a sanitizer changed
# the arithmetic, and that fails.
#
# Exit 0 when no sanitizer build changed a bit, printed no report, and exited
# cleanly; exit 1 otherwise.  A missing compiler or interpreter exits 2.
# This is a hand-run proof, not the CI job: it downloads nothing and uses the
# compiler already present.

set -euo pipefail

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  CLANG             C compiler (default: clang)\n'
  printf '  PYTHON            case writer (default: python3)\n'
  printf '  SANITIZE_OUT_DIR  keep the Y files here (default: temporary)\n'
}

case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if [ $# -ne 0 ]; then
  printf 'error: no arguments expected\n' >&2
  usage >&2
  exit 2
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
CLANG=${CLANG:-clang}
PYTHON=${PYTHON:-python3}
for tool in "$CLANG" "$PYTHON"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'error: not on PATH: %s\n' "$tool" >&2
    exit 2
  fi
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ydir=${SANITIZE_OUT_DIR:-$tmp/y}
mkdir -p "$tmp/case" "$ydir"

# The driver parses attn_abi.h structs only; this step writes each vector's
# guest image and its frozen output hash as raw bytes.
"$PYTHON" - "$REPO" "$tmp" <<'PY'
import struct
import sys
from pathlib import Path

repo = Path(sys.argv[1])
tmp = Path(sys.argv[2])
sys.path.insert(0, str(repo / "tools"))
import vectors  # noqa: E402

stems = []
for name in vectors.read_manifest()["vectors"]:
    v = vectors.load_vector(vectors.VECTORS / name)
    img = v.build_image()
    # attn_host_run sees the whole buffer, base included.
    blob = bytes(img.image.base) + bytes(img.image.buf)
    header = struct.pack("<8s5QII", b"SANCASE1", len(blob), img.x_addr,
                         img.w_addr, img.c_addr, img.y_addr, 64, 0)
    stem = Path(name).stem
    (tmp / "case" / (stem + ".case")).write_bytes(header + blob)
    (tmp / "case" / (stem + ".sha")).write_text(
        v.expected["sha256"] + "\n", encoding="ascii")
    stems.append(stem)
(tmp / "stems").write_text("\n".join(stems) + "\n", encoding="ascii")
PY

if [ ! -s "$tmp/stems" ]; then
  printf 'error: no vectors in tests/vectors/MANIFEST.json\n' >&2
  exit 1
fi

INCLUDES=(-I "$REPO/include")
SOURCES=("$REPO/tests/host/attn_sanitize_driver.c"
         "$REPO/tests/host/attn_host.c")

"$CLANG" -std=c11 -Wall -Wextra -ffp-contract=off -O1 -g \
  "${INCLUDES[@]}" "${SOURCES[@]}" -o "$tmp/baseline" -lm
"$CLANG" -std=c11 -Wall -Wextra -ffp-contract=off -O1 -g \
  -fsanitize=address "${INCLUDES[@]}" "${SOURCES[@]}" -o "$tmp/asan" -lm
"$CLANG" -std=c11 -Wall -Wextra -ffp-contract=off -O1 -g \
  -fsanitize=undefined -fno-sanitize-recover=all \
  "${INCLUDES[@]}" "${SOURCES[@]}" -o "$tmp/ubsan" -lm

runs=0
exact=0
libc=0
mismatches=0
reports=0
errors=0
libc_names=""

while IFS= read -r stem; do
  [ -n "$stem" ] || continue
  case_file=$tmp/case/$stem.case
  want=$(cat "$tmp/case/$stem.sha")
  base_err=$tmp/baseline-$stem.err
  rc=0
  "$tmp/baseline" "$case_file" "$ydir/baseline-$stem.y" 2>"$base_err" \
    || rc=$?
  got_base=$(sha256sum "$ydir/baseline-$stem.y" 2>/dev/null \
    | awk '{print $1}' || true)
  if [ "$rc" -ne 0 ] || [ -z "$got_base" ]; then
    printf '%-8s %-28s ERROR rc=%s\n' baseline "$stem" "$rc"
    errors=$((errors + 1))
  fi
  for san in asan ubsan; do
    y=$ydir/$san-$stem.y
    err=$tmp/$san-$stem.err
    rc=0
    "$tmp/$san" "$case_file" "$y" 2>"$err" || rc=$?
    runs=$((runs + 1))
    got=""
    if [ -f "$y" ]; then
      got=$(sha256sum "$y" | awk '{print $1}')
    fi
    verdict=OK
    if [ "$rc" -ne 0 ]; then
      errors=$((errors + 1))
      verdict="ERROR rc=$rc"
    fi
    if grep -qE 'AddressSanitizer|LeakSanitizer|runtime error:' "$err"; then
      reports=$((reports + 1))
      verdict=SANITIZER
      printf '%s %s: sanitizer report\n' "$san" "$stem" >&2
      sed -n '1,20p' "$err" >&2
    fi
    if [ -n "$got_base" ] && [ "$got" != "$got_base" ]; then
      mismatches=$((mismatches + 1))
      verdict=MISMATCH
    elif [ "$got" != "$want" ]; then
      libc=$((libc + 1))
      verdict=LIBC
      case " $libc_names " in
        *" $stem "*) ;;
        *) libc_names="$libc_names $stem" ;;
      esac
    elif [ "$verdict" = OK ]; then
      exact=$((exact + 1))
    fi
    printf '%-5s %-28s %s\n' "$san" "$stem" "$verdict"
  done
done <"$tmp/stems"

printf 'summary: %d runs, %d frozen exact, %d libc, %d mismatch, ' \
  "$runs" "$exact" "$libc" "$mismatches"
printf '%d sanitizer reports, %d errors\n' "$reports" "$errors"
if [ -n "$libc_names" ]; then
  printf 'libc: frozen hash not reproducible here (same Y from plain, asan ' 
  printf 'and ubsan builds):%s\n' "$libc_names"
fi

if [ $((mismatches + reports + errors)) -eq 0 ]; then
  exit 0
fi
exit 1
