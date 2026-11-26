#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Regenerate artifacts/: the demo excerpt and everything the toolchain makes
# of it, with the attention recognizer on and off.  Every file gets a line in
# artifacts/PROVENANCE naming the command and the commit that produced it.
#
#   scripts/artifacts.sh [--build-info FILE] [--sha SHA] [--from DIR]
#
#   --build-info FILE  BUILD-INFO to copy (default: <repo>/out/BUILD-INFO)
#   --sha SHA          commit to record; default: --from's CI-TRACE.txt, else HEAD
#   --from DIR         copy DIR/artifacts/ exactly as CI made it; no build
#
# Build mode needs a built toolchain and Spike (scripts/setup.sh); --from
# needs only DIR, normally the root of a CI artefact.

set -euo pipefail

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  PYTHON  interpreter for tools/report_html.py (default: python3)\n'
  printf '  TMPDIR and PATH are set by this script\n'
}

BUILD_INFO='' SHA='' FROM=''
while [ $# -gt 0 ]; do
  case $1 in
    -h|--help) usage; exit 0 ;;
    --build-info|--sha|--from)
      if [ $# -lt 2 ]; then
        printf 'error: %s needs a value\n' "$1" >&2
        exit 2
      fi
      case $1 in
        --build-info) BUILD_INFO=$2 ;;
        --sha) SHA=$2 ;;
        --from) FROM=$2 ;;
      esac
      shift 2 ;;
    -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
    *) printf 'error: unexpected argument: %s\n' "$1" >&2; usage; exit 2 ;;
  esac
done

REPO=$(cd "$(dirname "$0")/.." && pwd)
A=$REPO/artifacts
BIN=$REPO/out/toolchain/bin
CC=$BIN/riscv64-unknown-elf-gcc
OBJDUMP=$BIN/riscv64-unknown-elf-objdump
if [ -z "$BUILD_INFO" ]; then
  BUILD_INFO=$REPO/out/BUILD-INFO
fi
if [ -n "$FROM" ]; then
  if [ ! -d "$FROM" ]; then
    printf 'error: no such directory: %s\n' "$FROM" >&2
    exit 1
  fi
  FROM=$(cd "$FROM" && pwd)
  if [ "$FROM/artifacts" = "$A" ]; then
    printf 'error: --from source and destination are the same: %s\n' "$A" >&2
    exit 1
  fi
fi

# One sha for every line, resolved before anything is written: the option
# wins, then the CI trace, then this checkout.
if [ -n "$SHA" ]; then
  sha=$SHA
else
  sha=
  if [ -n "$FROM" ] && [ -f "$FROM/build/CI-TRACE.txt" ]; then
    sha=$(awk '/^commit:/ { print $2; exit }' "$FROM/build/CI-TRACE.txt")
  fi
  if [ -z "$sha" ]; then
    sha=$(git -C "$REPO" rev-parse HEAD 2> /dev/null || true)
  fi
fi
if [ -z "$sha" ]; then
  printf 'error: no commit SHA: pass --sha, supply DIR/build/CI-TRACE.txt, or run in a git checkout\n' >&2
  exit 1
fi
case $sha in
  *[!0-9a-f]*)
    printf 'error: SHA is not lowercase hex: %s\n' "$sha" >&2
    exit 1 ;;
esac
if [ ${#sha} -lt 7 ] || [ ${#sha} -gt 40 ]; then
  printf 'error: SHA must be 7 to 40 hex characters: %s\n' "$sha" >&2
  exit 1
fi

PROV_HEADER='# artifacts/PROVENANCE: one line per file, written by scripts/artifacts.sh'
PROV_NOTE='# BUILD-INFO is the build record itself (date, toolchain shas); make check-info refreshes it.'

# emit PATH CMD... : one line for the file at PATH, whose command is CMD.
# The command is quoted from its own argv, never typed separately.
emit() {
  local path=$1 rel quoted
  shift
  case $path in
    "$A"/*) rel=${path#"$A"/} ;;
    *) rel=$path ;;
  esac
  printf -v quoted '%q ' "$@"
  quoted=${quoted//"$REPO/"/}
  printf '%s\tproduced by %s at %s\n' "$rel" "${quoted% }" "$sha" \
    >> "$A/PROVENANCE"
}

# run PATH ARGV... : run the command, then record it.  RUN_CD, when set, is
# the directory the command runs in.
run() {
  local path=$1
  shift
  if [ -n "${RUN_CD:-}" ]; then
    (cd "$RUN_CD" && "$@")
  else
    "$@"
  fi
  emit "$path" "$@"
}

# run_shell PATH 'shell text' : for pipelines only.  Both the shell and the
# recorded line get the same text.
run_shell() {
  local path=$1 text=$2
  sh -c "$text"
  emit "$path" "$text"
}

build() { # build DIR EXTRA-FLAGS...
  local d=$1
  shift
  RUN_CD=$TMPDIR run "$d/excerpt.s" "$CC" -O2 "$@" -S "$full" -o "$d/excerpt.s"
  RUN_CD=$TMPDIR run "$d/excerpt.o" "$CC" -O2 "$@" -c "$full" -o "$d/excerpt.o"
  run_shell "$d/excerpt.dis" \
    "\"$OBJDUMP\" -d \"$d/excerpt.o\" | sed \"s|$d/||\" > \"$d/excerpt.dis\""
}

# One gcc command writes both dumps; copy each to its artefact name and
# record the compiler invocation that made it.
dumps() {
  local argv=("$CC" -O2 -fdump-tree-attn_recog -fdump-rtl-expand \
    -S "$full" -o /dev/null)
  rm -f "$TMPDIR"/artifacts-full.c.*
  (cd "$TMPDIR" && "${argv[@]}")
  cp "$TMPDIR"/artifacts-full.c.*t.attn_recog "$A/dumps/attn_recog.gimple"
  cp "$TMPDIR"/artifacts-full.c.*r.expand "$A/dumps/expand.rtl"
  emit "$A/dumps/attn_recog.gimple" "${argv[@]}"
  emit "$A/dumps/expand.rtl" "${argv[@]}"
}

summary() {
  local f files=0 bytes=0
  shopt -s globstar nullglob
  for f in "$A"/**/*; do
    [ -f "$f" ] || continue
    [ "${f##*/}" = PROVENANCE ] && continue
    [ "${f##*/}" = BUILD-INFO ] && continue
    files=$((files + 1))
    bytes=$((bytes + $(wc -c < "$f")))
  done
  du -sh "$A"
  printf 'artifacts: %s files, %s bytes\n' "$files" "$bytes"
}

from_artifacts() { # copy DIR/artifacts/ and its provenance; never compile
  local src=$FROM/artifacts rel f line path rest cmd
  local -a files=() missing=() lines=()
  local -A prov=()
  if [ ! -d "$src" ]; then
    printf 'error: no %s\n' "$src" >&2
    exit 1
  fi
  if [ ! -f "$src/BUILD-INFO" ]; then
    printf 'error: no %s (the CI artefact must include it)\n' \
      "$src/BUILD-INFO" >&2
    exit 1
  fi
  if [ -f "$src/PROVENANCE" ]; then
    while IFS= read -r line; do
      case $line in
        ''|'#'*) continue ;;
      esac
      path=${line%%$'\t'*}
      rest=${line#*$'\t'}
      rest=${rest%$'\r'}
      prov["$path"]=$rest
    done < "$src/PROVENANCE"
  fi

  # List and validate everything first: a bad source leaves artifacts/ as it
  # was, because nothing here writes until every entry has passed.
  shopt -s globstar nullglob
  for f in "$src"/**/*; do
    [ -f "$f" ] || continue
    rel=${f#"$src"/}
    [ "$rel" = PROVENANCE ] && continue
    files+=("$rel")
  done
  for rel in ${files[@]+"${files[@]}"}; do
    [ "$rel" = BUILD-INFO ] && continue
    rest=${prov["$rel"]:-}
    case $rest in
      'produced by '*) ;;
      *)
        printf 'error: %s has no provenance line in %s\n' "$rel" "$FROM" >&2
        missing+=("$rel")
        continue ;;
    esac
    if ! printf '%s' "$rest" | grep -Eq ' at [0-9a-f]{7,40}$'; then
      printf 'error: %s has no provenance line in %s\n' "$rel" "$FROM" >&2
      missing+=("$rel")
      continue
    fi
    cmd=${rest% at *}
    cmd=${cmd#produced by }
    if [ -z "$cmd" ]; then
      printf 'error: %s has no provenance line in %s\n' "$rel" "$FROM" >&2
      missing+=("$rel")
      continue
    fi
    lines+=("$(printf '%s\tproduced by %s at %s' "$rel" "$cmd" "$sha")")
  done
  if [ ${#missing[@]} -ne 0 ]; then
    printf 'error: %d file(s) above have no provenance line in %s\n' \
      "${#missing[@]}" "$FROM" >&2
    exit 1
  fi

  rm -rf "$A"
  mkdir -p "$A"
  for rel in ${files[@]+"${files[@]}"}; do
    mkdir -p "$A/$(dirname "$rel")"
    cp -p "$src/$rel" "$A/$rel"
  done
  {
    printf '%s\n' "$PROV_HEADER"
    printf '%s\n' "$PROV_NOTE"
    for line in ${lines[@]+"${lines[@]}"}; do
      printf '%s\n' "$line"
    done
  } > "$A/PROVENANCE"
}

build_artifacts() {
  local full
  if [ ! -f "$BUILD_INFO" ]; then
    printf 'error: no %s (run scripts/build.sh)\n' "$BUILD_INFO" >&2
    exit 1
  fi
  export TMPDIR=$REPO/build/tmp PATH=$REPO/out/host/bin:$PATH
  mkdir -p "$TMPDIR"
  rm -rf "$A"
  mkdir -p "$A/attn" "$A/loops" "$A/dumps"
  printf '%s\n' "$PROV_HEADER" > "$A/PROVENANCE"
  printf '%s\n' "$PROV_NOTE" >> "$A/PROVENANCE"

  run_shell excerpt.c \
    "grep -v '^#include' \"$REPO/demo/mha_plain.c\" | tr -d '\r' > \"$A/excerpt.c\""

  # The same completion attncc.sh does: standard headers, line numbers kept.
  full=$TMPDIR/artifacts-full.c
  { printf '#include <math.h>\n#include <stdlib.h>\n#line 1 "excerpt.c"\n'
    cat "$A/excerpt.c"; } > "$full"

  build "$A/attn"
  build "$A/loops" -fno-tree-loop-attn

  # The pass and expansion dumps of the attn build.
  dumps

  export REPO
  # The text is for sh -c, so $REPO must survive this shell.
  # shellcheck disable=SC2016
  run_shell attncc-run.txt \
    'cd "$REPO" && scripts/attncc.sh --run artifacts/excerpt.c build/tmp/artifacts-run.o | sed "s|$REPO/||g" > artifacts/attncc-run.txt'

  # scripts/build.sh writes the record; copy it in, but it is the build record
  # itself, not an artefact, so it gets no provenance line.
  cp "$BUILD_INFO" "$A/BUILD-INFO"

  count() { grep -cP "$1" "$2" || true; }
  cat > "$A/README.md" <<EOF
# Artifacts

Generated by \`scripts/artifacts.sh\` from \`demo/mha_plain.c\` with the
toolchain built from this repository. The input is the bare excerpt, and
every compile is plain \`-O2\`. Each file's producing command and commit
are in \`PROVENANCE\` next to it.

| File | Content |
|------|---------|
| \`excerpt.c\` | the input: \`demo/mha_plain.c\` without its \`#include\` lines |
| \`attn/excerpt.s\`, \`.o\`, \`.dis\` | assembly, object and disassembly with the recognizer on (the default) |
| \`loops/excerpt.s\`, \`.o\`, \`.dis\` | the same with \`-fno-tree-loop-attn\`: the loops as written |
| \`dumps/attn_recog.gimple\` | GIMPLE after the recognizer: descriptors, guard and the \`.ATTN\` call |
| \`dumps/expand.rtl\` | RTL after expansion: the \`(attn ...)\` insn |
| \`attncc-run.txt\` | \`scripts/attncc.sh --run\`: both versions executed on Spike |

attn instructions in the disassembly: $(count '\sattn\s' "$A/attn/excerpt.dis") with the
recognizer, $(count '\sattn\s' "$A/loops/excerpt.dis") without. Executed on Spike for n = 16, e = 32,
h = 4:

\`\`\`
$(grep 'instructions executed\|largest' "$A/attncc-run.txt")
\`\`\`

The loops still present in \`attn/excerpt.dis\` run only when the runtime
guard fails (sizes the instruction would reject); every valid size runs
the single \`attn\`.
EOF
  # README.md is written by this script, so this script's invocation is its
  # producer.
  emit "$A/README.md" "$0"

  RUN_CD=$REPO run "$A/report.html" "${PYTHON:-python3}" \
    tools/report_html.py --out artifacts/report.html
}

if [ -n "$FROM" ]; then
  from_artifacts
else
  build_artifacts
fi
summary
