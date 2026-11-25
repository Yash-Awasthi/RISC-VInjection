#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Name the file, line and fix for the five most common build failures.
#
#   scripts/diagnose.sh LOG
#
# Print the first known failure in LOG and exit 1:
#
#   <file>:<line>: <what>: <fix>
#
# A clean log prints "no known failure in <file>" and exits 0.
# The patterns and fixes are listed in docs/troubleshooting.md.
#
# Exit: 0 clean, 1 known failure, 2 usage or unreadable file.

set -euo pipefail

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  none; the log path is the only input\n'
}

case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if [ $# -ne 1 ]; then
  printf 'error: expected one log file\n' >&2
  usage >&2
  exit 2
fi
log=$1
if [ ! -f "$log" ]; then
  printf 'error: not a readable file: %s\n' "$log" >&2
  usage >&2
  exit 2
fi

shopt -s nocasematch

RE_MARCH_ARG='unrecognized argument in option .?-march='
RE_MARCH_CANNOT='-march=[^[:space:]]*: cannot'
RE_MARCH_ISA='unsupported ISA extension'
RE_PATCH_AT='patch failed at'
RE_PATCH_ERR='error: patch failed:'
RE_PATCH_AM='error: could not apply'
RE_PATCH_HINT='git am --continue'
RE_GIT='not a git repository'
RE_SUBMODULE_URL='no url found for submodule path'
RE_NOENT='no such file or directory'
RE_SUBMODULE_PATH='(^|[^[:alnum:]_])(gcc|binutils|spike|qemu|newlib)/'
RE_TOOL_MISSING='riscv64-unknown-elf-(gcc|g\+\+|as|ld|objdump|ar|ranlib|nm|readelf):? (command )?not found'
RE_VERSION='(riscv64|toolchain|binutils|gcc|g\+\+).*(version mismatch|does not match the pinned|older than the pinned|newer than the pinned)'
RE_APT='unable to locate package'
RE_APT_CANDIDATE='e: package .* has no installation candidate'
RE_PKG_MISSING='(flex|bison|gperf|texinfo|makeinfo): (command )?not found'

# Print the category of one log line, or nothing.
classify() {
  local line=$1
  if [[ $line =~ $RE_MARCH_ARG ]] ||
     [[ $line =~ $RE_MARCH_CANNOT ]] ||
     [[ $line =~ $RE_MARCH_ISA ]]; then
    printf 'march'
  elif [[ $line =~ $RE_PATCH_AT ]] ||
       [[ $line =~ $RE_PATCH_ERR ]] ||
       [[ $line =~ $RE_PATCH_AM ]] ||
       [[ $line =~ $RE_PATCH_HINT ]]; then
    printf 'patch'
  elif [[ $line =~ $RE_GIT ]] ||
       [[ $line =~ $RE_SUBMODULE_URL ]] ||
       { [[ $line =~ $RE_NOENT ]] &&
         [[ $line =~ $RE_SUBMODULE_PATH ]]; }; then
    printf 'submodule'
  elif [[ $line =~ $RE_TOOL_MISSING ]] ||
       [[ $line =~ $RE_VERSION ]]; then
    printf 'stale'
  elif [[ $line =~ $RE_APT ]] ||
       [[ $line =~ $RE_APT_CANDIDATE ]] ||
       [[ $line =~ $RE_PKG_MISSING ]]; then
    printf 'missing'
  fi
  return 0
}

n=0
while IFS= read -r line || [ -n "$line" ]; do
  n=$((n + 1))
  case $(classify "$line") in
    march)
      what='wrong -march'
      fix='pass the gcc -march=rv64gc_xattn flag as docs/build-and-test.md section 5 shows'
      ;;
    patch)
      what='patch conflict'
      fix='rerun scripts/patches.sh apply on the pinned commit as docs/build-and-test.md section 2 says'
      ;;
    submodule)
      what='submodule not initialised'
      fix='run git submodule update --init gcc binutils spike qemu newlib as docs/build-and-test.md section 2 says'
      ;;
    stale)
      what='stale toolchain'
      fix='rebuild it with scripts/build.sh and check versions.env as docs/build-and-test.md section 3 says'
      ;;
    missing)
      what='missing package'
      fix='install the package list in docs/build-and-test.md section 1 or run scripts/setup.sh'
      ;;
    *) continue ;;
  esac
  printf '%s:%s: %s: %s\n' "$log" "$n" "$what" "$fix"
  exit 1
done < "$log"

printf 'no known failure in %s\n' "$log"
exit 0
