#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the make check targets one at a time and print one summary table.
#
#   scripts/check-summary.sh                 every target that make check runs
#   scripts/check-summary.sh check-core ...  just these targets
#
# Each target is its own make invocation, so one failure does not stop the
# rest.  The table names the target, its pass and fail counts and the seconds
# it took; the exit status is 1 when any target failed.

set -euo pipefail

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  MAKE  make binary to use (default: make)\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
MAKE=${MAKE:-make}

targets=("$@")
if [ ${#targets[@]} -eq 0 ]; then
  targets=(check-build-info check-info check-core check-gcc check-sched
           check-demo check-sim check-recog check-lint check-shell
           check-artifacts)
fi

fails=0
started=$SECONDS
rows=()
for target in "${targets[@]}"; do
  t0=$SECONDS
  if "$MAKE" --no-print-directory "$target"; then
    rows+=("$(printf '%-18s %4d %4d %5ds' "$target" 1 0 $((SECONDS - t0)))")
  else
    rows+=("$(printf '%-18s %4d %4d %5ds' "$target" 0 1 $((SECONDS - t0)))")
    fails=$((fails + 1))
  fi
done

echo
printf '%-18s %4s %4s %6s\n' target pass fail time
printf '%-18s %4s %4s %6s\n' ------------------ ---- ---- ------
for row in ${rows[@]+"${rows[@]}"}; do
  printf '%s\n' "$row"
done
printf '%-18s %4d %4d %5ds\n' total "$(( ${#targets[@]} - fails ))" "$fails" \
  "$((SECONDS - started))"

[ "$fails" -eq 0 ] || exit 1