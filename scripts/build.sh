#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Xattn toolchain and simulators from the submodules.
#
#   scripts/build.sh [step...]
#
# Steps (default: all, in this order):
#   binutils  riscv64-unknown-elf binutils        -> out/toolchain
#   gcc       C compiler only, no bootstrap       -> out/toolchain
#   newlib    newlib + libgloss (medany)          -> out/toolchain
#   libgcc    libgcc (medany)                     -> out/toolchain
#   dtc       device-tree compiler Spike needs    -> out/host/bin
#   spike     Spike with Xattn                    -> out/spike
#   qemu      QEMU riscv64/riscv32 system + user  -> build/qemu
#   info      write out/BUILD-INFO, build nothing  -> out/BUILD-INFO
#
# Every step configures once and rebuilds incrementally afterwards, so
# re-running after a source edit only recompiles what changed.  JOBS sets
# the parallelism (default: all cores).

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
B=$REPO/build
OUT=${XATTN_OUT:-$REPO/out}   # XATTN_OUT lets a test write BUILD-INFO elsewhere
TC=$OUT/toolchain
JOBS=${JOBS:-$(nproc)}
TARGET=riscv64-unknown-elf

# GCC writes large temporaries; keep them off a small /tmp.
export TMPDIR=$B/tmp
mkdir -p "$TMPDIR"
export PATH=$TC/bin:$OUT/host/bin:$PATH

log() { printf '\n== %s\n' "$*"; }

# Host-side objects (GCC's build tools, Spike, QEMU) go through ccache when it
# is installed; without it the build runs exactly as before.
if command -v ccache > /dev/null 2>&1; then
  export CCACHE_DIR="$B/ccache"
  export CCACHE_BASEDIR="$REPO"
  export CCACHE_NOHASHDIR=1
  export CCACHE_COMPRESS=1
  export CC="ccache ${CC:-cc}"
  export CXX="ccache ${CXX:-c++}"
  log "ccache $(ccache --version | head -1)"
fi

# The record of what produced out/: five submodule SHAs, host tools, versions.
# Written at the end of every build and by `scripts/build.sh info`; `make
# check` copies it into artifacts/ so a result always names its inputs.
write_build_info() {
  local file=$OUT/BUILD-INFO c var
  mkdir -p "$OUT"
  {
    printf 'xattn build information\n'
    printf 'date:     %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'host:     %s, %s core(s), JOBS=%s\n' \
      "$(uname -sm)" "$(nproc)" "$JOBS"
    printf 'host cc:  %s\n' "$(cc --version 2> /dev/null | head -1)"
    printf 'host c++: %s\n' "$(c++ --version 2> /dev/null | head -1)"
    printf 'python:   %s (floor %s)\n' \
      "$(python3 --version 2>&1 | head -1)" "$(pin_of PYTHON_VERSION)"
    printf 'pylock:   %s\n' "$(pin_of PYTHON_LOCK)"
    printf 'numpy:    %s\n' \
      "$(python3 -c 'import numpy; print(numpy.__version__)' 2> /dev/null || echo none)"
    printf '\nsubmodules (pinned = versions.env, built = what is checked out):\n'
    for c in binutils gcc newlib qemu spike; do
      var=$(printf '%s_SHA' "$c" | tr '[:lower:]' '[:upper:]')
      local built
      if [ -e "$REPO/$c/.git" ]; then
        built=$(git -C "$REPO/$c" rev-parse HEAD 2> /dev/null || echo unknown)
      else
        built='no git checkout'
      fi
      printf '  %-8s pinned %s  built %s\n' "$c" "$(pin_of "$var")" "$built"
    done
    printf '\noutputs:\n'
    printf '  gcc    %s\n' \
      "$("$TC"/bin/riscv64-unknown-elf-gcc --version 2> /dev/null | head -1 || echo none)"
    # Spike has no --version; its configure-time stamp is the next best record.
    printf '  spike  %s\n' \
      "$(git -C "$REPO/spike" describe --always --dirty 2> /dev/null || echo none)"
    printf '  qemu   %s\n' \
      "$("$B"/qemu/qemu-system-riscv64 --version 2> /dev/null | head -1 || echo none)"
  } > "$file"
  log "$file"
  sed 's/^/   /' "$file"
}

pin_of() {
  local var=$1 value
  value=$(sed -n "s/^$var=//p" "$REPO/versions.env" 2> /dev/null | head -1)
  printf '%s' "${value:-none}"
}

# configure_once DIR CONFIGURE ARGS... : run configure for a new DIR, or
# from scratch when ARGS differ from the last run (e.g. after Xattn was
# removed and the default -march changed).
configure_once() {
  local dir=$1
  shift
  # Build trees from before this check are assumed current.
  [ -f "$dir/Makefile" ] || [ -f "$dir/build.ninja" ] &&
    [ ! -f "$dir/configure.args" ] && echo "$*" > "$dir/configure.args"
  if [ -f "$dir/configure.args" ] && [ "$(cat "$dir/configure.args")" != "$*" ]; then
    echo "configure arguments changed, reconfiguring $dir"
    rm -rf "$dir"
  fi
  mkdir -p "$dir"
  if [ ! -f "$dir/Makefile" ] && [ ! -f "$dir/build.ninja" ]; then
    echo "$*" > "$dir/configure.args"
    (cd "$dir" && "$@" > configure.log 2>&1) || {
      echo "configure failed, see $dir/configure.log" >&2
      exit 1
    }
  fi
}

# run_logged DIR LOG CMD... : run in DIR, keep output in LOG, show its tail
# on failure.
run_logged() {
  local dir=$1 log=$2
  shift 2
  (cd "$dir" && "$@" > "$log" 2>&1) || {
    tail -30 "$dir/$log" >&2
    echo "failed, full log: $dir/$log" >&2
    exit 1
  }
}

step_binutils() {
  log binutils
  configure_once "$B/binutils" "$REPO/binutils/configure" \
    --target=$TARGET --prefix="$TC" --disable-gdb --disable-gdbserver \
    --disable-sim --disable-werror --disable-nls
  run_logged "$B/binutils" make.log make -j"$JOBS"
  run_logged "$B/binutils" install.log make install
}

step_gcc() {
  log gcc
  # Xattn is the default extension whenever the tree has it.
  local ARCH=rv64gc
  [ -f "$REPO/gcc/gcc/config/riscv/riscv-ext-xattn.def" ] && ARCH=rv64gc_xattn
  configure_once "$B/gcc" "$REPO/gcc/configure" \
    --target=$TARGET --prefix="$TC" --enable-languages=c \
    --disable-bootstrap --disable-multilib --with-arch="$ARCH" \
    --with-abi=lp64d --without-headers --with-newlib --disable-shared \
    --disable-threads --disable-libssp --disable-libgomp \
    --disable-libquadmath --disable-libatomic --disable-nls --disable-werror
  run_logged "$B/gcc" make.log make -j"$JOBS" all-gcc
  run_logged "$B/gcc" install.log make install-gcc
}

step_newlib() {
  log newlib
  configure_once "$B/newlib" "$REPO/newlib/configure" \
    --target=$TARGET --prefix="$TC" --disable-multilib --disable-nls \
    --enable-newlib-io-long-double --enable-newlib-io-long-long \
    --enable-newlib-io-c99-formats CFLAGS_FOR_TARGET="-O2 -mcmodel=medany"
  run_logged "$B/newlib" make.log make -j"$JOBS" all-target-newlib \
    all-target-libgloss
  run_logged "$B/newlib" install.log make install-target-newlib \
    install-target-libgloss
}

step_libgcc() {
  log libgcc
  run_logged "$B/gcc" libgcc.log make -j"$JOBS" all-target-libgcc \
    CFLAGS_FOR_TARGET="-O2 -mcmodel=medany"
  run_logged "$B/gcc" libgcc-install.log make install-target-libgcc
}

step_dtc() {
  log dtc
  if command -v dtc > /dev/null; then
    echo "using $(command -v dtc)"
    return
  fi
  # QEMU vendors dtc as a meson subproject; fetch it if needed.
  [ -d "$REPO/qemu/subprojects/dtc" ] ||
    (cd "$REPO/qemu" && meson subprojects download dtc > /dev/null)
  run_logged "$REPO/qemu/subprojects/dtc" "$B/dtc.log" \
    make -j"$JOBS" NO_PYTHON=1 NO_YAML=1 NO_VALGRIND=1 dtc
  mkdir -p "$OUT/host/bin"
  cp "$REPO/qemu/subprojects/dtc/dtc" "$OUT/host/bin/"
}

step_spike() {
  log spike
  configure_once "$B/spike" "$REPO/spike/configure" --prefix="$OUT/spike"
  run_logged "$B/spike" make.log make -j"$JOBS"
  run_logged "$B/spike" install.log make install
}

step_qemu() {
  log qemu
  configure_once "$B/qemu" "$REPO/qemu/configure" \
    --target-list=riscv64-softmmu,riscv64-linux-user,riscv32-softmmu \
    --prefix="$OUT/qemu" --without-default-features --enable-tcg \
    --disable-werror
  run_logged "$B/qemu" make.log make -j"$JOBS"
}

usage() {
  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
  printf 'env:\n'
  printf '  JOBS       parallelism (default: all cores)\n'
  printf '  XATTN_OUT  install prefix (default: <repo>/out)\n'
  printf '  TMPDIR     set to build/tmp by this script\n'
}
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) printf 'error: unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
esac

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(binutils gcc newlib libgcc dtc spike qemu)
for s in "${steps[@]}"; do
  case $s in
    binutils|gcc|newlib|libgcc|dtc|spike|qemu) "step_$s" ;;
    info) : ;;  # nothing to build; the final write_build_info records the run
    *) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
  esac
done
write_build_info
log "done"
