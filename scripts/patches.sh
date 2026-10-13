#!/usr/bin/env bash
# Keep the Xattn changes to the upstream trees as patch files in patches/.
#
#   scripts/patches.sh apply  [component...]   check out the pinned upstream
#                                              commit on branch xattn, then
#                                              git am patches/<component>/*
#   scripts/patches.sh export [component...]   rewrite patches/<component>/
#                                              from the commits on xattn
#   scripts/patches.sh remove [component...]   leave branch xattn intact and
#                                              check out the pinned upstream
#                                              commit: the tree has no Xattn
#   scripts/patches.sh restore [component...]  check out branch xattn again
#   scripts/patches.sh status                  show pinned commit and branch
#
# Components: binutils gcc spike qemu (default: all).  The pinned commit is
# the one the superproject records for the submodule.

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
ALL=(binutils gcc spike qemu)
BRANCH=xattn

pinned() {
  git -C "$REPO" ls-files -s -- "$1" | awk '$1 == "160000" { print $2 }'
}

base_of() {
  local c=$1 pin
  pin=$(pinned "$c")
  if [ -z "$pin" ]; then
    echo "error: $c is not a submodule of $REPO at HEAD" >&2
    exit 1
  fi
  echo "$pin"
}

do_apply() {
  local c=$1 base
  base=$(base_of "$c")
  git -C "$REPO/$c" checkout -q -B "$BRANCH" "$base"
  shopt -s nullglob
  local p=("$REPO/patches/$c"/*.patch)
  if [ ${#p[@]} -eq 0 ]; then
    echo "$c: no patches"
    return
  fi
  git -C "$REPO/$c" am -q --3way "${p[@]}"
  echo "$c: applied ${#p[@]} patch(es) on ${base:0:12}"
}

do_export() {
  local c=$1 base
  base=$(base_of "$c")
  rm -rf "$REPO/patches/$c"
  mkdir -p "$REPO/patches/$c"
  git -C "$REPO/$c" format-patch -q --no-signature --zero-commit \
    -o "$REPO/patches/$c" "$base..$BRANCH"
  echo "$c: $(ls "$REPO/patches/$c" | wc -l) patch(es) from ${base:0:12}"
}

clean_or_die() {
  if [ -n "$(git -C "$REPO/$1" status --porcelain --untracked-files=no)" ]; then
    echo "error: $1 has uncommitted changes; commit or stash them first" >&2
    exit 1
  fi
}

do_remove() {
  local c=$1 base
  base=$(base_of "$c")
  clean_or_die "$c"
  git -C "$REPO/$c" checkout -q --detach "$base"
  echo "$c: upstream ${base:0:12}, Xattn removed (branch $BRANCH kept)"
}

do_restore() {
  local c=$1
  clean_or_die "$c"
  git -C "$REPO/$c" checkout -q "$BRANCH"
  echo "$c: back on branch $BRANCH"
}

do_status() {
  local c=$1
  printf '%-9s pinned %s  on %s\n' "$c" "$(pinned "$c" | cut -c1-12)" \
    "$(git -C "$REPO/$c" rev-parse --abbrev-ref HEAD)"
}

cmd=${1:-}
shift || true
comps=("$@")
[ ${#comps[@]} -eq 0 ] && comps=("${ALL[@]}")

case $cmd in
  apply) for c in "${comps[@]}"; do do_apply "$c"; done ;;
  export) for c in "${comps[@]}"; do do_export "$c"; done ;;
  remove) for c in "${comps[@]}"; do do_remove "$c"; done ;;
  restore) for c in "${comps[@]}"; do do_restore "$c"; done ;;
  status) for c in "${comps[@]}"; do do_status "$c"; done ;;
  *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
