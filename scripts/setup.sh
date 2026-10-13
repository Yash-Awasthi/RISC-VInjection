#!/usr/bin/env bash
# One command from a fresh clone to a working Xattn toolchain:
#
#   scripts/setup.sh
#
#  1. checks the build tools and, if some are missing, prints the package
#     command for this distribution (apt, dnf, pacman, zypper, brew) and runs
#     it after asking;
#  2. fetches the upstream submodules (gcc, binutils, spike, qemu, newlib);
#  3. applies patches/ (skipped for a submodule already on branch xattn);
#  4. builds binutils, GCC, newlib, libgcc, Spike and QEMU (scripts/build.sh);
#  5. runs every test (make check);
#  6. compiles demo/mha_plain.c with plain -O2 and runs it on Spike
#     (scripts/attncc.sh --run).
#
# Re-running is cheap: every step is incremental.  JOBS sets parallelism.

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

step() { printf '\n==== %s\n' "$*"; }

step "1/6 build tools"
need=()
for t in git make gcc g++ python3 bison flex makeinfo gawk ninja pkg-config; do
  command -v "$t" > /dev/null || need+=("$t")
done
for h in gmp.h mpfr.h mpc.h zlib.h; do
  echo "#include <$h>" | cc -E -x c - > /dev/null 2>&1 || need+=("$h")
done
for p in glib-2.0; do
  pkg-config --exists "$p" 2> /dev/null || need+=("$p")
done
python3 -c 'import venv' 2> /dev/null || need+=(python3-venv)

if [ ${#need[@]} -gt 0 ]; then
  echo "missing: ${need[*]}"
  if command -v apt-get > /dev/null; then
    cmd="sudo apt-get install -y build-essential git python3 python3-venv \
libgmp-dev libmpfr-dev libmpc-dev texinfo bison flex gawk zlib1g-dev \
libglib2.0-dev ninja-build pkg-config"
  elif command -v dnf > /dev/null; then
    cmd="sudo dnf install -y gcc gcc-c++ make git python3 gmp-devel \
mpfr-devel libmpc-devel texinfo bison flex gawk zlib-devel glib2-devel \
ninja-build pkgconf"
  elif command -v pacman > /dev/null; then
    cmd="sudo pacman -S --needed base-devel git python gmp mpfr libmpc \
texinfo bison flex gawk zlib glib2 ninja pkgconf"
  elif command -v zypper > /dev/null; then
    cmd="sudo zypper install -y gcc gcc-c++ make git python3 gmp-devel \
mpfr-devel mpc-devel texinfo bison flex gawk zlib-devel glib2-devel \
ninja pkg-config"
  elif command -v brew > /dev/null; then
    cmd="brew install gmp mpfr libmpc texinfo bison flex gawk zlib glib \
ninja pkg-config"
  else
    echo "unknown package manager; install the tools above and re-run" >&2
    exit 1
  fi
  echo "install with: $cmd"
  read -r -p "run it now? [y/N] " ans
  [ "$ans" = y ] || [ "$ans" = Y ] || exit 1
  $cmd
fi
echo "ok"

step "2/6 upstream sources"
# Only fetch missing ones: "update" would detach a submodule that is
# already on branch xattn back to the pinned upstream commit.
for c in gcc binutils spike qemu newlib; do
  if [ -e "$c/.git" ]; then
    echo "$c: present"
  else
    git submodule update --init "$c"
  fi
done

step "3/6 Xattn patches"
for c in binutils gcc spike qemu; do
  if [ "$(git -C "$c" rev-parse --abbrev-ref HEAD)" = xattn ]; then
    echo "$c: already on branch xattn"
  else
    scripts/patches.sh apply "$c"
  fi
done

step "4/6 build (about 15 minutes on 16 cores the first time)"
scripts/build.sh

step "5/6 tests"
make check

step "6/6 demo: plain C excerpt to one attn"
scripts/attncc.sh --run demo/mha_plain.c

printf '\ndone.  Compile your own code with: scripts/attncc.sh FILE.c\n'
