#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
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
#   scripts/patches.sh check   [component...]  prove the series: every patch
#                                              applies to the pinned commit in
#                                              order, and export on xattn
#                                              reproduces patches/<c>/ exactly
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
  local n
  n=$(find "$REPO/patches/$c" -maxdepth 1 -name '*.patch' | wc -l)
  echo "$c: $n patch(es) from ${base:0:12}"
}

# A tree may report stat-only dirt: on Windows with a CRLF-filtered checkout
# `git diff-files` says "M" for thousands of files whose blob is identical to
# the index (qemu shows 10873 of them).  Content decides, not the stat data: if
# `git diff` is silent, the tree is clean and a forced checkout loses nothing.
clean_or_die() {
  if ! git -C "$REPO/$1" diff --quiet -- . ||
     [ -n "$(git -C "$REPO/$1" ls-files --others --exclude-standard)" ]; then
    echo "error: $1 has uncommitted changes; commit or stash them first" >&2
    exit 1
  fi
}

do_checkout() {
  local c=$1
  shift
  git -C "$REPO/$c" checkout -q "$@" 2>/dev/null ||
    git -C "$REPO/$c" checkout -q -f "$@"
}

do_remove() {
  local c=$1 base
  base=$(base_of "$c")
  clean_or_die "$c"
  do_checkout "$c" --detach "$base"
  echo "$c: upstream ${base:0:12}, Xattn removed (branch $BRANCH kept)"
}

do_restore() {
  local c=$1
  clean_or_die "$c"
  do_checkout "$c" "$BRANCH"
  echo "$c: back on branch $BRANCH"
}

do_status() {
  local c=$1
  printf '%-9s pinned %s  on %s\n' "$c" "$(pinned "$c" | cut -c1-12)" \
    "$(git -C "$REPO/$c" rev-parse --abbrev-ref HEAD)"
}

# The series is replayed the way it is shipped: a temporary worktree at the
# pinned commit, each patch checked with `git apply --check` and then applied in
# order (no three-way fallback), then the same series replayed twice with
# `git am` and the resulting tree compared with branch xattn.  Re-applying from
# the same pin must give the same tree, which is what "idempotent" means here;
# the branch is re-exported and compared with the committed patch files.
# Patches are read from the index, not from the checkout, so a CRLF checkout
# cannot change the result.  Nothing in the repository's own worktree is touched.
do_check() {
  local c=$1 base tmp n rc=0 b p tree branch_tree again
  base=$(base_of "$c")
  shopt -s nullglob
  local patches=("$REPO/patches/$c"/*.patch)
  n=${#patches[@]}
  if [ "$n" -eq 0 ]; then
    echo "$c: no patches"
    return
  fi

  tmp=$(mktemp -d)
  if ! git -C "$REPO/$c" worktree add -q --detach "$tmp/w" "$base" \
       2> "$tmp/wt.log"; then
    echo "error: $c: cannot make a worktree at ${base:0:12}" >&2
    sed 's/^/    /' "$tmp/wt.log" >&2
    rm -rf "$tmp"
    return 1
  fi

  # The committed blobs, byte for byte, whatever the checkout did to them.
  mkdir -p "$tmp/series"
  for p in "${patches[@]}"; do
    b=$(basename "$p")
    git -C "$REPO" show ":patches/$c/$b" > "$tmp/series/$b"
  done
  local series=("$tmp/series"/*.patch)

  # The plan's literal gate, one patch at a time so that files created by an
  # earlier patch exist when the next one is checked.
  for p in "${series[@]}"; do
    if git -C "$tmp/w" apply --check "$p" > "$tmp/apply.log" 2>&1 &&
       git -C "$tmp/w" apply "$p" >> "$tmp/apply.log" 2>&1; then
      continue
    fi
    echo "error: $c: $(basename "$p") does not apply to ${base:0:12}" >&2
    sed 's/^/    /' "$tmp/apply.log" >&2
    rc=1
    break
  done
  # The applied files are untracked, so reset --hard alone leaves them behind
  # and the `git am` below would refuse to overwrite them.  Scratch worktree
  # only, never the repository's own.
  git -C "$tmp/w" reset -q --hard "$base"
  git -C "$tmp/w" clean -qfd

  if ! git -C "$tmp/w" am -q --3way "${series[@]}" > "$tmp/am.log" 2>&1
  then
    echo "error: $c: the series does not apply to ${base:0:12}" >&2
    sed 's/^/    /' "$tmp/am.log" >&2
    rc=1
  else
    tree=$(git -C "$tmp/w" rev-parse "HEAD^{tree}")
    branch_tree=$(git -C "$REPO/$c" rev-parse "$BRANCH^{tree}")
    if [ "$tree" != "$branch_tree" ]; then
      echo "error: $c: the series builds $tree, branch $BRANCH holds" \
	   "$branch_tree" >&2
      rc=1
    else
      git -C "$tmp/w" reset -q --hard "$base"
      if ! git -C "$tmp/w" am -q --3way "${series[@]}" \
	   > "$tmp/am2.log" 2>&1; then
	echo "error: $c: the second application failed" >&2
	sed 's/^/    /' "$tmp/am2.log" >&2
	rc=1
      else
	again=$(git -C "$tmp/w" rev-parse "HEAD^{tree}")
	[ "$again" = "$tree" ] || {
	  echo "error: $c: re-applying gave $again, not $tree" >&2
	  rc=1
	}
      fi

      # patches/ must be exactly what the branch exports.
      mkdir -p "$tmp/exp" "$tmp/committed"
      git -C "$REPO/$c" format-patch -q --no-signature --zero-commit \
	-o "$tmp/exp" "$base..$BRANCH" > /dev/null 2>&1
      cp "${series[@]}" "$tmp/committed/"
      # The abbreviated blob hashes in "index <a>..<b>" depend on core.abbrev;
      # they are informational, so the comparison ignores them.  A trailing CR
      # is a checkout artifact and not part of the patch, so it is ignored too.
      sed -i -e 's/^index [0-9a-f]*\.\.[0-9a-f]*/index/' -e 's/\r$//' \
	"$tmp/exp"/*.patch "$tmp/committed"/*.patch
      if ! diff -r -q "$tmp/committed" "$tmp/exp" > /dev/null; then
	echo "error: $c: patches/$c is not what $BRANCH exports" >&2
	diff -r "$tmp/committed" "$tmp/exp" | sed 's/^/    /' >&2 || true
	rc=1
      fi
    fi
  fi

  git -C "$REPO/$c" worktree remove --force "$tmp/w" 2> /dev/null || true
  rm -rf "$tmp"
  [ "$rc" -eq 0 ] && echo "$c: $n patch(es) apply to ${base:0:12}," \
    "re-apply the same tree, export matches"
  return $rc
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
  check)
    rc=0
    for c in "${comps[@]}"; do do_check "$c" || rc=1; done
    exit $rc
    ;;
  status) for c in "${comps[@]}"; do do_status "$c"; done ;;
  *) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
