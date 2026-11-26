#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Assert that versions.env names the commits the superproject actually pins.
#
#   scripts/check-pins.sh              check versions.env
#   VERSIONS_FILE=other.env scripts/check-pins.sh
#
# Exit 0 and one line per submodule when the two agree; exit 1 with the two
# SHAs printed when they do not.  It never fetches and never changes a
# submodule: a pin differs only because a person changed something.

set -euo pipefail

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  VERSIONS_FILE  pins file to check (default: <repo>/versions.env)\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
FILE=${VERSIONS_FILE:-$REPO/versions.env}

if [ ! -f "$FILE" ]; then
  echo "error: no $FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
. "$FILE"

rc=0
for c in binutils gcc newlib qemu spike; do
  var=$(printf '%s_SHA' "$c" | tr '[:lower:]' '[:upper:]')
  want=${!var:-}
  pin=$(git -C "$REPO" ls-tree HEAD -- "$c" | awk '{print $3}')
  if [ -z "$pin" ]; then
    echo "error: $c is not a submodule of $REPO at HEAD" >&2
    rc=1
  elif [ -z "$want" ]; then
    echo "error: $FILE does not define $var" >&2
    rc=1
  elif [ "$want" != "$pin" ]; then
    echo "error: $var in $FILE is $want but the superproject pins $pin" >&2
    rc=1
  else
    printf '%-8s %s\n' "$c" "$pin"
  fi
done

exit $rc
