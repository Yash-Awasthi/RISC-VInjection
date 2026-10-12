#!/usr/bin/env python3
"""Independent model of the attn instruction (docs/01-instruction-spec.md).

Written from the specification in float64 with NumPy, without looking at
include/attn_core.h, so the tests can compare the two.  Also owns the
instruction encoding and the byte layout of the rs2/rs3 descriptors, which
tests/test_core.py checks against the C structs.
"""

import struct

import numpy as np

ATTN_MATCH = 0x0600107B
ATTN_MASK = 0x0600707F
DT_F32, DT_BF16 = 0, 1
F_CAUSAL, F_SCALE = 1, 2

WEIGHTS_FMT = "<8Q"          # wq wk wv wo bq bk bv bo
CFG_FMT = "<5I2H2IQ"         # n e h h_kv flags in_dtype out_dtype scale_bits reserved mask
WEIGHTS_FIELDS = ["wq", "wk", "wv", "wo", "bq", "bk", "bv", "bo"]
CFG_FIELDS = ["n", "e", "h", "h_kv", "flags", "in_dtype", "out_dtype",
              "scale_bits", "reserved", "mask"]


def encode(rd, rs1, rs2, rs3):
    return ATTN_MATCH | rd << 7 | rs1 << 15 | rs2 << 20 | rs3 << 27


def decode(word):
    if word & ATTN_MASK != ATTN_MATCH:
        raise ValueError("not attn: 0x%08x" % word)
    return dict(rd=word >> 7 & 31, rs1=word >> 15 & 31,
                rs2=word >> 20 & 31, rs3=word >> 27 & 31)


def bf16_bits(a):
    """float32 array -> uint16 bf16 bits, round to nearest even."""
    u = np.asarray(a, np.float32).view(np.uint32).astype(np.uint64)
    r = ((u + 0x7FFF + ((u >> 16) & 1)) >> 16).astype(np.uint16)
    nan = (u & 0x7FFFFFFF) > 0x7F800000
    r[nan] = ((u[nan] >> 16) | 0x40).astype(np.uint16)
    return r


def from_bf16_bits(b):
    return (np.asarray(b, np.uint16).astype(np.uint32) << 16).view(np.float32)


def round_dtype(a, dt):
    a = np.asarray(a, np.float32)
    return from_bf16_bits(bf16_bits(a)) if dt == DT_BF16 else a


def reference(x, wq, wk, wv, wo, bq=None, bk=None, bv=None, bo=None,
              h=1, h_kv=0, causal=False, mask=None, scale=None):
    """Multi-head self-attention in float64.  Weights are [in][out]."""
    f = lambda a: None if a is None else np.asarray(a, np.float64)
    x, wq, wk, wv, wo = map(f, (x, wq, wk, wv, wo))
    bq, bk, bv, bo, mask = map(f, (bq, bk, bv, bo, mask))
    n, e = x.shape
    h_kv = h_kv or h
    d = e // h
    q = x @ wq + (0 if bq is None else bq)
    k = x @ wk + (0 if bk is None else bk)
    v = x @ wv + (0 if bv is None else bv)
    scale = 1 / np.sqrt(d) if scale is None else scale
    heads = []
    for j in range(h):
        g = j // (h // h_kv)
        s = q[:, j * d:(j + 1) * d] @ k[:, g * d:(g + 1) * d].T * scale
        if mask is not None:
            s = s + mask
        if causal:
            s = np.where(np.tri(n, dtype=bool), s, -np.inf)
        with np.errstate(invalid="ignore"):
            p = np.exp(s - s.max(axis=1, keepdims=True))
            p = p / p.sum(axis=1, keepdims=True)
        heads.append(p @ v[:, g * d:(g + 1) * d])
    return np.concatenate(heads, axis=1) @ wo + (0 if bo is None else bo)


class Image:
    """Flat little-endian guest memory with a bump allocator."""

    def __init__(self, base=0x1000):
        self.base = base
        self.buf = bytearray()

    def put(self, data, align=16):
        pad = -len(self.buf) % align
        self.buf += bytes(pad)
        addr = self.base + len(self.buf)
        self.buf += data
        return addr

    def array(self, a, dt):
        a = np.ascontiguousarray(a, np.float32)
        return self.put((bf16_bits(a) if dt == DT_BF16 else a).tobytes())

    def reserve(self, nbytes):
        return self.put(bytes(nbytes))


def scale_bits(scale):
    return struct.unpack("<I", struct.pack("<f", scale))[0]


class Case:
    """A random attn problem laid out in an Image, plus its expected Y."""

    def __init__(self, rng, n, e, h, h_kv=0, flags=0, in_dt=DT_F32,
                 out_dt=DT_F32, bias=True, mask=False, scale=None,
                 base=0x1000):
        self.n, self.e, self.h, self.h_kv = n, e, h, h_kv
        self.flags, self.in_dt, self.out_dt = flags, in_dt, out_dt
        kv = (h_kv or h) * (e // h)
        g = lambda *s: rng.standard_normal(s).astype(np.float32)
        w = 1 / np.sqrt(e)
        self.x = g(n, e)
        self.wq, self.wk, self.wv, self.wo = (g(e, e) * w, g(e, kv) * w,
                                              g(e, kv) * w, g(e, e) * w)
        self.b = [g(e), g(kv), g(kv), g(e)] if bias else [None] * 4
        self.mask = None
        if mask:
            self.mask = np.where(rng.random((n, n)) < 0.2, -np.inf,
                                 g(n, n)).astype(np.float32)
            self.mask[:, 0] = 0  # keep every row alive
        if scale is not None:
            self.flags |= F_SCALE
        self.scale = scale

        im = self.image = Image(base)
        self.x_addr = im.array(self.x, in_dt)
        wp = [im.array(a, in_dt) for a in (self.wq, self.wk, self.wv, self.wo)]
        bp = [0 if b is None else im.array(b, DT_F32) for b in self.b]
        mp = 0 if self.mask is None else im.array(self.mask, DT_F32)
        self.w_addr = im.put(struct.pack(WEIGHTS_FMT, *wp, *bp))
        self.c_addr = im.put(struct.pack(
            CFG_FMT, n, e, h, h_kv, self.flags, in_dt, out_dt,
            scale_bits(scale) if scale is not None else 0, 0, mp))
        self.y_addr = im.reserve(n * e * (2 if out_dt == DT_BF16 else 4))

    def expected(self):
        r = lambda a: round_dtype(a, self.in_dt)
        return reference(r(self.x), r(self.wq), r(self.wk), r(self.wv),
                         r(self.wo), *self.b, h=self.h, h_kv=self.h_kv,
                         causal=bool(self.flags & F_CAUSAL), mask=self.mask,
                         scale=self.scale)

    def read_y(self, mem):
        off = self.y_addr - self.image.base
        cnt = self.n * self.e
        if self.out_dt == DT_BF16:
            raw = np.frombuffer(bytes(mem[off:off + 2 * cnt]), np.uint16)
            y = from_bf16_bits(raw)
        else:
            y = np.frombuffer(bytes(mem[off:off + 4 * cnt]), np.float32)
        return y.reshape(self.n, self.e)

    def tolerance(self):
        """Absolute tolerance for comparing Y with expected()."""
        return 2.0 ** -7 if self.out_dt == DT_BF16 else 1e-4
