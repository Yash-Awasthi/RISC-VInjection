#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Assert that every file under artifacts/ names the command and commit that
# produced it in artifacts/PROVENANCE.
#
#   scripts/check-artifacts.sh
#   XATTN_ARTIFACTS=other scripts/check-artifacts.sh
#
# Exit 0 when artifacts/PROVENANCE exists, has one well-formed entry per
# regular file under artifacts/ (PROVENANCE itself excepted), and every
# entry names a file that exists.  Exit 1 otherwise, naming every offender.

set -euo pipefail

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  XATTN_ARTIFACTS  directory to check (default: <repo>/artifacts)\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
A=${XATTN_ARTIFACTS:-$REPO/artifacts}
if [ -d "$A" ]; then
  A=$(cd "$A" && pwd)
fi
PROV=$A/PROVENANCE

# MINGW can put the Windows find.exe ahead of the GNU one; prefer the latter.
FIND='find'
if ! "$FIND" --version > /dev/null 2>&1 && [ -x /usr/bin/find ]; then
  FIND=/usr/bin/find
fi

if [ ! -f "$PROV" ]; then
  echo "error: no $PROV (run scripts/artifacts.sh)" >&2
  exit 1
fi

declare -A seen=()
errors=()

# Each line after the header comments: PATH<TAB>produced by COMMAND at SHA.
while IFS= read -r line; do
  line=${line%$'\r'}
  case $line in
    '#'*) continue ;;
  esac
  path=${line%%$'\t'*}
  rest=${line#*$'\t'}
  if [ -n "${seen["$path"]+x}" ]; then
    errors+=("${path:-<empty line>}: two provenance lines")
  fi
  seen["$path"]=1
  case $rest in
    'produced by '*) ;;
    *)
      errors+=("${path:-<empty line>}: no 'produced by ' after the path")
      continue ;;
  esac
  if ! printf '%s' "$rest" | grep -Eq ' at [0-9a-f]{7,40}$'; then
    errors+=("$path: no trailing ' at <sha>'")
    continue
  fi
  cmd=${rest% at *}
  cmd=${cmd#produced by }
  if [ -z "$cmd" ]; then
    errors+=("$path: empty command")
  fi
  if [ ! -f "$A/$path" ]; then
    errors+=("$path: listed but missing")
  fi
done < "$PROV"

files=0
while IFS= read -r f; do
  rel=${f#"$A"/}
  [ "$rel" = PROVENANCE ] && continue
  # BUILD-INFO is the build record, not an artefact; it needs no entry.
  [ "$rel" = BUILD-INFO ] && continue
  files=$((files + 1))
  if [ -z "${seen["$rel"]+x}" ]; then
    errors+=("$rel: no provenance line")
  fi
done < <("$FIND" "$A" -type f)

if [ ${#errors[@]} -ne 0 ]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 1
fi

printf 'artifacts: %d files, every one with a provenance line\n' "$files"
