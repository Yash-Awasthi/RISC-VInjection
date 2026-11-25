FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b

# Prerequisites only: no RISC-V cross compiler, no simulator is built here.
# The repository is mounted at run time, never copied into the image.

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# Section 1 of docs/build-and-test.md, plus host build tools for QEMU,
# Spike, binutils and GCC (gperf, dejagnu, autotools, gettext).
RUN apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=60 update \
    && apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=60 install -y --no-install-recommends \
        build-essential \
        gawk \
        meson \
        patchutils \
        python3 \
        python3-pip \
        python3-venv \
        bc \
        bison \
        flex \
        gperf \
        texinfo \
        dejagnu \
        autoconf \
        automake \
        libtool \
        gettext \
        pkg-config \
        device-tree-compiler \
        libexpat1-dev \
        libfdt-dev \
        libgmp-dev \
        libisl-dev \
        libmpc-dev \
        libmpfr-dev \
        libpixman-1-dev \
        libglib2.0-dev \
        libslirp-dev \
        libzstd-dev \
        zlib1g-dev \
        clang \
        lld \
        llvm \
        ccache \
        git \
        ninja-build \
        cpio \
        file \
        patch \
        rsync \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
