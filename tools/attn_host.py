"""Run include/attn_core.h on the host, over an attn_model.Case image."""

import ctypes
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def build(out_dir):
    so = Path(out_dir) / "attn_host.so"
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Werror", "-shared",
                    "-fPIC", "-I", REPO / "include",
                    REPO / "tests/host/attn_host.c", "-o", so, "-lm"],
                   check=True)
    lib = ctypes.CDLL(str(so))
    lib.attn_host_run.argtypes = [ctypes.POINTER(ctypes.c_char),
                                  ctypes.c_uint64] + [ctypes.c_uint64] * 4 \
        + [ctypes.c_uint]
    return lib


def run(lib, case, xlen=64):
    """Execute case on the host core; returns (status, memory from base)."""
    base = case.image.base
    mem = ctypes.create_string_buffer(base + len(case.image.buf))
    mem[base:base + len(case.image.buf)] = bytes(case.image.buf)
    rc = lib.attn_host_run(mem, len(mem), case.y_addr, case.x_addr,
                           case.w_addr, case.c_addr, xlen)
    return rc, mem.raw[base:]
