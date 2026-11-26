#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Assert that out/BUILD-INFO exists, is current, and names the pinned sources.
#
#   scripts/check-build-info.sh
#   XATTN_OUT=other scripts/check-build-info.sh
#
# Exit 0 when out/BUILD-INFO exists, is at least as new as every file under
# patches/, and its five pinned SHAs match versions.env.  Exit 1 otherwise,
# naming the file or submodule at fault.  It never builds and never fetches:
# run scripts/build.sh to refresh the record.

set -euo pipefail

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  XATTN_OUT  output dir holding BUILD-INFO (default: <repo>/out)\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${XATTN_OUT:-$REPO/out}
INFO=$OUT/BUILD-INFO

if [ ! -f "$INFO" ]; then
  echo "error: no $INFO (run scripts/build.sh)" >&2
  exit 1
fi

# A patch newer than the record means the build predates its own sources.
# Bash globs, not find and sort: Windows puts its own find.exe and sort.exe
# ahead of the ones this script needs.
if [ -d "$REPO/patches" ]; then
  newest=
  shopt -s globstar nullglob
  for f in "$REPO"/patches/**/*; do
    [ -f "$f" ] || continue
    [ "$f" -nt "$INFO" ] || continue
    if [ -z "$newest" ] || [ "$f" -nt "$newest" ]; then
      newest=$f
    fi
  done
  if [ -n "$newest" ]; then
    echo "error: $newest is newer than $INFO (re-run scripts/build.sh)" >&2
    exit 1
  fi
fi

for c in binutils gcc newlib qemu spike; do
  var=$(printf '%s_SHA' "$c" | tr '[:lower:]' '[:upper:]')
  want=$(sed -n "s/^${var}=//p" "$REPO/versions.env" 2> /dev/null | head -1)
  have=$(awk -v n="$c" '$1==n && $2=="pinned" {print $3}' "$INFO")
  if [ -z "$want" ]; then
    echo "error: versions.env does not define $var (cannot check $c)" >&2
    exit 1
  fi
  if [ -z "$have" ]; then
    echo "error: $INFO has no pinned $c (re-run scripts/build.sh)" >&2
    exit 1
  fi
  if [ "$have" != "$want" ]; then
    echo "error: $c pinned $have in $INFO but $want in versions.env" \
      "(re-run scripts/build.sh)" >&2
    exit 1
  fi
done

echo "BUILD-INFO is current: $INFO"
