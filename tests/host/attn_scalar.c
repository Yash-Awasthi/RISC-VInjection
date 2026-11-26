/* SPDX-License-Identifier: GPL-3.0-or-later */
/* attn_scalar.c -- an independent scalar reference for the attn instruction.

   Written from docs/01-instruction-spec.md.  It includes attn_abi.h only for
   the cfg/weights layout and the flag constants, never attn_core.h, and it
   shares no arithmetic with the core: every product and sum is accumulated in
   double and rounded to binary32 at each store, and exp/sqrt are implemented
   here.  The binary32 core rounds after every operation instead, so the two
   agree only within the shared tolerance; that is the point of a third
   implementation.

   CLI, little-endian host only:

     attn_scalar gen FILE [options]   write a random problem from --seed
     attn_scalar run FILE OUT         execute the problem stored in FILE

   Options for gen: --n N --e E --h H --hkv K --in-dt 0|1 --out-dt 0|1
   --flags MASK --scale BITS --nobias --nomask --seed S.

   Input FILE: 48-byte header of twelve little-endian u32 --
     magic "XATS", n, e, h, h_kv, flags, in_dtype, out_dtype, scale_bits,
     bias_mask (bit i selects bq, bk, bv, bo), has_mask, reserved --
   then binary32 X[n][e], Wq[e][e], Wk[e][kv], Wv[e][kv], Wo[e][e], the biases
   named by bias_mask in that field order, and the mask[n][n] when has_mask.
   Output: 16-byte header (magic "XATY", n, e, out_dtype, 0) then Y, as
   binary32 bits or bf16 bits.  A reserved configuration exits 1 and writes
   nothing.  */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attn_abi.h"

#define SC_MAGIC   0x58544153u /* "XATS" */
#define SC_MAGIC_Y 0x58415459u /* "XATY" */
#define SC_HDR_U32 12u
#define SC_YHDR_U32 4u

struct attn_scalar_job
{
  uint32_t n, e, h, h_kv, flags, in_dtype, out_dtype, scale_bits;
  unsigned bias_mask;
  unsigned has_mask;
};

enum
{
  SC_X, SC_WQ, SC_WK, SC_WV, SC_WO,
  SC_BQ, SC_BK, SC_BV, SC_BO, SC_MASK, SC_NIN
};

/* ---- binary64 helpers, no libm ---- */

static double
double_from_u64 (uint64_t u)
{
  union { double d; uint64_t u; } c;
  c.u = u;
  return c.d;
}

static double
sc_inf (void)
{
  return double_from_u64 (0x7ff0000000000000ull);
}

static double
sc_nan (void)
{
  return double_from_u64 (0x7ff8000000000000ull);
}

/* Newton from a bit-trick seed; seven steps take the ~6% seed below 2**-53.  */
static double
sc_sqrt (double x)
{
  union { double d; uint64_t u; } c;
  double g;

  if (x != x)
    return x;
  if (x < 0.0)
    return sc_nan ();
  if (x == 0.0 || x == sc_inf ())
    return x;
  c.d = x;
  c.u = (c.u >> 1) + 0x1ff8000000000000ull;
  g = c.d;
  for (int i = 0; i < 7; i++)
    g = 0.5 * (g + x / g);
  return g;
}

static double
sc_pow2 (long long k)
{
  union { double d; uint64_t u; } c;

  if (k > 1023)
    return sc_inf ();
  if (k < -1074)
    return 0.0;
  if (k >= -1022)
    {
      c.u = (uint64_t) (k + 1023) << 52;
      return c.d;
    }
  /* Subnormal range: split off 2**-1000, which is a normal double.  */
  c.u = (uint64_t) (k + 1000 + 1023) << 52;
  return c.d * double_from_u64 (0x0170000000000000ull);
}

/* exp(x) = 2**k * sum r**i/i! with x = k*ln2 + r, |r| <= ln2/2.  */
static double
sc_exp (double x)
{
  static const double ln2 = 0.693147180559945309417232121458;
  double k, r, p;

  if (x != x)
    return x;
  if (x > 709.782712893384)
    return sc_inf ();
  if (x < -745.1332191019411)
    return 0.0;
  k = (x / ln2 >= 0.0) ? (long long) (x / ln2 + 0.5)
                       : (long long) (x / ln2 - 0.5);
  r = x - k * ln2;
  p = 1.0 / 6227020800.0;               /* 1/13! */
  p = p * r + 1.0 / 479001600.0;        /* 1/12! */
  p = p * r + 1.0 / 39916800.0;
  p = p * r + 1.0 / 3628800.0;
  p = p * r + 1.0 / 362880.0;
  p = p * r + 1.0 / 40320.0;
  p = p * r + 1.0 / 5040.0;
  p = p * r + 1.0 / 720.0;
  p = p * r + 1.0 / 120.0;
  p = p * r + 1.0 / 24.0;
  p = p * r + 1.0 / 6.0;
  p = p * r + 0.5;
  p = p * r + 1.0;
  p = p * r + 1.0;
  return p * sc_pow2 ((long long) k);
}

/* ---- binary32 helpers ---- */

static float
f32_from_bits (uint32_t u)
{
  union { uint32_t u; float f; } c;
  c.u = u;
  return c.f;
}

static uint32_t
bits_from_f32 (float f)
{
  union { uint32_t u; float f; } c;
  c.f = f;
  return c.u;
}

/* Round to nearest, ties to even; NaNs stay NaN and become quiet.  */
static float
sc_bf16_round (float f)
{
  uint32_t u = bits_from_f32 (f);

  if ((u & 0x7fffffffu) > 0x7f800000u)
    return f32_from_bits ((u & 0xffff0000u) | 0x00400000u);
  return f32_from_bits ((u + 0x7fffu + ((u >> 16) & 1u)) & 0xffff0000u);
}

static float
sc_load (float v, unsigned dt)
{
  return dt == ATTN_DT_BF16 ? sc_bf16_round (v) : v;
}

/* ---- the arithmetic ---- */

static int
sc_valid (const struct attn_scalar_job *j)
{
  uint64_t hkv = j->h_kv ? j->h_kv : j->h;

  if (j->n == 0 || j->e == 0 || j->h == 0
      || j->n > ATTN_MAX_N || j->e > ATTN_MAX_E)
    return 0;
  if (j->e % j->h || j->h % hkv || (j->flags & ~ATTN_F_ALL))
    return 0;
  if (j->in_dtype > ATTN_DT_BF16 || j->out_dtype > ATTN_DT_BF16)
    return 0;
  if (j->bias_mask & ~15u || j->has_mask > 1)
    return 0;
  return 1;
}

/* out[r][c] = sum_k in[r][k] * w[k][c] + b[c], in double, stored as float.  */
static void
sc_matmul (const float *in, const float *w, const float *b, float *out,
           uint64_t rows, uint64_t inner, uint64_t cols)
{
  for (uint64_t r = 0; r < rows; r++)
    for (uint64_t c = 0; c < cols; c++)
      {
        double acc = 0.0;
        for (uint64_t k = 0; k < inner; k++)
          acc += (double) in[r * inner + k] * (double) w[k * cols + c];
        if (b)
          acc += (double) b[c];
        out[r * cols + c] = (float) acc;
      }
}

/* Entry point: the caller supplies the ten array pointers named by SC_*.
   Y is n*e binary32 values already rounded to out_dtype when it is bf16.
   Returns 0, or 1 for a reserved configuration.  */
int
attn_scalar_run (const struct attn_scalar_job *j,
                 const float *const in[SC_NIN], float *y)
{
  uint64_t n = j->n, e = j->e, h = j->h;
  uint64_t hkv = j->h_kv ? j->h_kv : j->h;
  uint64_t d = e / h, kv = hkv * d, group = h / hkv;
  uint64_t xf = n * e, wq = e * e, wk = e * kv, wv = e * kv, wo = e * e;
  double scale;
  float *q = NULL, *k = NULL, *v = NULL, *c = NULL;
  float *x = NULL, *mwq = NULL, *mwk = NULL, *mwv = NULL, *mwo = NULL;
  const float *bq = NULL, *bk = NULL, *bv = NULL, *bo = NULL, *m = NULL;
  double *p = NULL;
  int rc = 3;

  if (!sc_valid (j))
    return 1;
  scale = (j->flags & ATTN_F_SCALE)
          ? (double) f32_from_bits (j->scale_bits)
          : 1.0 / sc_sqrt ((double) d);
  q = malloc (n * e * sizeof *q);
  k = malloc (n * kv * sizeof *k);
  v = malloc (n * kv * sizeof *v);
  c = malloc (n * e * sizeof *c);
  p = malloc (n * sizeof *p);
  x = malloc (xf * sizeof *x);
  mwq = malloc (wq * sizeof *mwq);
  mwk = malloc (wk * sizeof *mwk);
  mwv = malloc (wv * sizeof *mwv);
  mwo = malloc (wo * sizeof *mwo);
  if (!q || !k || !v || !c || !p || !x || !mwq || !mwk || !mwv || !mwo)
    goto out;

  for (uint64_t i = 0; i < xf; i++)
    x[i] = sc_load (in[SC_X][i], j->in_dtype);
  for (uint64_t i = 0; i < wq; i++)
    mwq[i] = sc_load (in[SC_WQ][i], j->in_dtype);
  for (uint64_t i = 0; i < wk; i++)
    mwk[i] = sc_load (in[SC_WK][i], j->in_dtype);
  for (uint64_t i = 0; i < wv; i++)
    mwv[i] = sc_load (in[SC_WV][i], j->in_dtype);
  for (uint64_t i = 0; i < wo; i++)
    mwo[i] = sc_load (in[SC_WO][i], j->in_dtype);
  if (j->bias_mask & 1u)
    bq = in[SC_BQ];
  if (j->bias_mask & 2u)
    bk = in[SC_BK];
  if (j->bias_mask & 4u)
    bv = in[SC_BV];
  if (j->bias_mask & 8u)
    bo = in[SC_BO];
  if (j->has_mask)
    m = in[SC_MASK];

  sc_matmul (x, mwq, bq, q, n, e, e);
  sc_matmul (x, mwk, bk, k, n, e, kv);
  sc_matmul (x, mwv, bv, v, n, e, kv);

  for (uint64_t hd = 0; hd < h; hd++)
    {
      uint64_t qo = hd * d, ko = (hd / group) * d;
      for (uint64_t i = 0; i < n; i++)
        {
          uint64_t lim = (j->flags & ATTN_F_CAUSAL) ? i + 1 : n;
          double mx = -sc_inf (), l = 0.0;
          for (uint64_t jj = 0; jj < lim; jj++)
            {
              double acc = 0.0;
              for (uint64_t t = 0; t < d; t++)
                acc += (double) q[i * e + qo + t]
                       * (double) k[jj * kv + ko + t];
              acc = acc * scale;
              if (m)
                acc = acc + (double) m[i * n + jj];
              p[jj] = acc;
              if (acc > mx)
                mx = acc;
            }
          for (uint64_t jj = 0; jj < lim; jj++)
            {
              p[jj] = sc_exp (p[jj] - mx);
              l = l + p[jj];
            }
          for (uint64_t t = 0; t < d; t++)
            {
              double acc = 0.0;
              for (uint64_t jj = 0; jj < lim; jj++)
                acc += p[jj] * (double) v[jj * kv + ko + t];
              c[i * e + qo + t] = (float) (acc / l);
            }
        }
    }

  sc_matmul (c, mwo, bo, q, n, e, e);
  for (uint64_t i = 0; i < n * e; i++)
    y[i] = (j->out_dtype == ATTN_DT_BF16)
           ? sc_bf16_round (q[i]) : q[i];
  rc = 0;
out:
  free (q); free (k); free (v); free (c); free (p);
  free (x); free (mwq); free (mwk); free (mwv); free (mwo);
  return rc;
}

/* ---- file format and CLI ---- */

static uint32_t
rd32 (const unsigned char *p)
{
  return (uint32_t) p[0] | (uint32_t) p[1] << 8
         | (uint32_t) p[2] << 16 | (uint32_t) p[3] << 24;
}

static void
wr32 (unsigned char *p, uint32_t v)
{
  p[0] = (unsigned char) v;
  p[1] = (unsigned char) (v >> 8);
  p[2] = (unsigned char) (v >> 16);
  p[3] = (unsigned char) (v >> 24);
}

static uint64_t
sc_float_count (const struct attn_scalar_job *j)
{
  uint64_t hkv = j->h_kv ? j->h_kv : j->h;
  uint64_t kv = hkv * (j->e / j->h);
  uint64_t t = (uint64_t) j->n * j->e + (uint64_t) j->e * j->e
               + 2 * (uint64_t) j->e * kv + (uint64_t) j->e * j->e;

  if (j->bias_mask & 1u)
    t += j->e;
  if (j->bias_mask & 2u)
    t += kv;
  if (j->bias_mask & 4u)
    t += kv;
  if (j->bias_mask & 8u)
    t += j->e;
  if (j->has_mask)
    t += (uint64_t) j->n * j->n;
  return t;
}

static unsigned char *
slurp (const char *path, size_t *len)
{
  FILE *f = fopen (path, "rb");
  long sz;
  unsigned char *buf;

  if (!f)
    return NULL;
  if (fseek (f, 0, SEEK_END) != 0 || (sz = ftell (f)) < 0
      || fseek (f, 0, SEEK_SET) != 0)
    {
      fclose (f);
      return NULL;
    }
  buf = malloc (sz ? (size_t) sz : 1);
  if (!buf || fread (buf, 1, (size_t) sz, f) != (size_t) sz)
    {
      fclose (f);
      free (buf);
      return NULL;
    }
  fclose (f);
  *len = (size_t) sz;
  return buf;
}

static int
do_run (const char *in_path, const char *out_path)
{
  size_t len = 0, at;
  unsigned char *buf = slurp (in_path, &len);
  struct attn_scalar_job j;
  const float *in[SC_NIN] = { 0 };
  float *y = NULL;
  int rc = 0;

  if (!buf || len < SC_HDR_U32 * 4)
    {
      fprintf (stderr, "attn_scalar: cannot read %s\n", in_path);
      free (buf);
      return 2;
    }
  if (rd32 (buf) != SC_MAGIC)
    {
      fprintf (stderr, "attn_scalar: bad input magic\n");
      free (buf);
      return 2;
    }
  j.n = rd32 (buf + 4);
  j.e = rd32 (buf + 8);
  j.h = rd32 (buf + 12);
  j.h_kv = rd32 (buf + 16);
  j.flags = rd32 (buf + 20);
  j.in_dtype = rd32 (buf + 24);
  j.out_dtype = rd32 (buf + 28);
  j.scale_bits = rd32 (buf + 32);
  j.bias_mask = rd32 (buf + 36);
  j.has_mask = rd32 (buf + 40);
  if (!sc_valid (&j))
    {
      fprintf (stderr, "attn_scalar: reserved configuration\n");
      free (buf);
      return 1;
    }
  if (len != SC_HDR_U32 * 4 + 4 * sc_float_count (&j))
    {
      fprintf (stderr, "attn_scalar: input size does not match shape\n");
      free (buf);
      return 2;
    }

  at = SC_HDR_U32 * 4;
  {
    uint64_t kv = (uint64_t) (j.h_kv ? j.h_kv : j.h) * (j.e / j.h);
    const float *p = (const float *) (void *) (buf + at);
    in[SC_X] = p; p += (uint64_t) j.n * j.e;
    in[SC_WQ] = p; p += (uint64_t) j.e * j.e;
    in[SC_WK] = p; p += (uint64_t) j.e * kv;
    in[SC_WV] = p; p += (uint64_t) j.e * kv;
    in[SC_WO] = p; p += (uint64_t) j.e * j.e;
    if (j.bias_mask & 1u) { in[SC_BQ] = p; p += j.e; }
    if (j.bias_mask & 2u) { in[SC_BK] = p; p += kv; }
    if (j.bias_mask & 4u) { in[SC_BV] = p; p += kv; }
    if (j.bias_mask & 8u) { in[SC_BO] = p; p += j.e; }
    if (j.has_mask) { in[SC_MASK] = p; }
  }

  y = malloc ((uint64_t) j.n * j.e * sizeof *y);
  if (!y)
    {
      free (buf);
      return 3;
    }
  rc = attn_scalar_run (&j, in, y);
  if (rc == 0)
    {
      unsigned char hdr[SC_YHDR_U32 * 4];
      FILE *f = fopen (out_path, "wb");
      if (!f)
        {
          fprintf (stderr, "attn_scalar: cannot write %s\n", out_path);
          rc = 2;
        }
      else
        {
          wr32 (hdr, SC_MAGIC_Y);
          wr32 (hdr + 4, j.n);
          wr32 (hdr + 8, j.e);
          wr32 (hdr + 12, j.out_dtype);
          fwrite (hdr, 1, sizeof hdr, f);
          for (uint64_t i = 0; i < (uint64_t) j.n * j.e; i++)
            {
              unsigned char b[4];
              if (j.out_dtype == ATTN_DT_BF16)
                {
                  uint16_t v = (uint16_t) (bits_from_f32 (y[i]) >> 16);
                  b[0] = (unsigned char) v;
                  b[1] = (unsigned char) (v >> 8);
                  fwrite (b, 1, 2, f);
                }
              else
                {
                  wr32 (b, bits_from_f32 (y[i]));
                  fwrite (b, 1, 4, f);
                }
            }
          if (fclose (f) != 0)
            rc = 2;
        }
    }
  free (y);
  free (buf);
  return rc;
}

static uint32_t rng_state;

static uint32_t
rng_next (void)
{
  uint32_t x = rng_state;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  rng_state = x;
  return x;
}

/* Uniform in [-1, 1).  */
static double
rng_sym (void)
{
  return 2.0 * ((double) (rng_next () >> 8) / 16777216.0) - 1.0;
}

static int
do_gen (const char *path, struct attn_scalar_job j, uint32_t seed)
{
  uint64_t hkv = j.h_kv ? j.h_kv : j.h;
  uint64_t kv = hkv * (j.e / j.h);
  uint64_t count;
  float *a;
  FILE *f;
  int rc = 0;

  if (!sc_valid (&j))
    {
      fprintf (stderr, "attn_scalar: reserved configuration\n");
      return 1;
    }
  count = sc_float_count (&j);
  a = malloc (count * sizeof *a);
  if (!a)
    return 3;
  rng_state = seed ? seed : 1u;
  {
    uint64_t i = 0;
    double w = 1.0 / sc_sqrt ((double) j.e);
    for (uint64_t x = 0; x < (uint64_t) j.n * j.e; x++)
      a[i++] = (float) rng_sym ();
    for (uint64_t x = 0; x < (uint64_t) j.e * j.e; x++)
      a[i++] = (float) (rng_sym () * w);
    for (uint64_t x = 0; x < (uint64_t) j.e * kv; x++)
      a[i++] = (float) (rng_sym () * w);
    for (uint64_t x = 0; x < (uint64_t) j.e * kv; x++)
      a[i++] = (float) (rng_sym () * w);
    for (uint64_t x = 0; x < (uint64_t) j.e * j.e; x++)
      a[i++] = (float) (rng_sym () * w);
    if (j.bias_mask & 1u)
      for (uint64_t x = 0; x < j.e; x++)
        a[i++] = (float) (0.1 * rng_sym ());
    if (j.bias_mask & 2u)
      for (uint64_t x = 0; x < kv; x++)
        a[i++] = (float) (0.1 * rng_sym ());
    if (j.bias_mask & 4u)
      for (uint64_t x = 0; x < kv; x++)
        a[i++] = (float) (0.1 * rng_sym ());
    if (j.bias_mask & 8u)
      for (uint64_t x = 0; x < j.e; x++)
        a[i++] = (float) (0.1 * rng_sym ());
    if (j.has_mask)
      for (uint64_t x = 0; x < (uint64_t) j.n * j.n; x++)
        a[i++] = (float) (0.5 * rng_sym ());
    if (i != count)
      rc = 3;
  }
  f = fopen (path, "wb");
  if (!f)
    {
      fprintf (stderr, "attn_scalar: cannot write %s\n", path);
      free (a);
      return 2;
    }
  {
    unsigned char hdr[SC_HDR_U32 * 4];
    wr32 (hdr, SC_MAGIC);
    wr32 (hdr + 4, j.n);
    wr32 (hdr + 8, j.e);
    wr32 (hdr + 12, j.h);
    wr32 (hdr + 16, j.h_kv);
    wr32 (hdr + 20, j.flags);
    wr32 (hdr + 24, j.in_dtype);
    wr32 (hdr + 28, j.out_dtype);
    wr32 (hdr + 32, j.scale_bits);
    wr32 (hdr + 36, j.bias_mask);
    wr32 (hdr + 40, j.has_mask);
    wr32 (hdr + 44, 0);
    fwrite (hdr, 1, sizeof hdr, f);
  }
  if (rc == 0 && fwrite (a, 4, count, f) != count)
    rc = 2;
  if (fclose (f) != 0)
    rc = 2;
  free (a);
  return rc;
}

static int
parse_u32 (const char *s, uint32_t *out)
{
  char *end;
  unsigned long v;

  if (!s)
    return 0;
  v = strtoul (s, &end, 0);
  if (*s == '\0' || *end != '\0' || v > 0xfffffffful)
    return 0;
  *out = (uint32_t) v;
  return 1;
}

static void
usage (void)
{
  fprintf (stderr,
           "usage: attn_scalar gen FILE [--n N --e E --h H --hkv K"
           " --in-dt 0|1 --out-dt 0|1 --flags M --scale BITS --nobias"
           " --nomask --seed S]\n"
           "       attn_scalar run FILE OUT\n");
}

int
main (int argc, char **argv)
{
  struct attn_scalar_job j = { 4, 8, 2, 0, 0, 0, 0, 0, 15u, 0u };
  uint32_t seed = 1;
  int gen;

  if (argc < 3)
    {
      usage ();
      return 2;
    }
  gen = strcmp (argv[1], "gen") == 0;
  if (!gen && strcmp (argv[1], "run") != 0)
    {
      usage ();
      return 2;
    }
  if (!gen)
    {
      if (argc != 4)
        {
          usage ();
          return 2;
        }
      return do_run (argv[2], argv[3]);
    }

  for (int i = 3; i < argc; i++)
    {
      if (strcmp (argv[i], "--nobias") == 0)
        j.bias_mask = 0u;
      else if (strcmp (argv[i], "--nomask") == 0)
        j.has_mask = 0u;
      else if (i + 1 < argc)
        {
          const char *v = argv[++i];
          if (strcmp (argv[i - 1], "--n") == 0)
            { if (!parse_u32 (v, &j.n)) goto bad; }
          else if (strcmp (argv[i - 1], "--e") == 0)
            { if (!parse_u32 (v, &j.e)) goto bad; }
          else if (strcmp (argv[i - 1], "--h") == 0)
            { if (!parse_u32 (v, &j.h)) goto bad; }
          else if (strcmp (argv[i - 1], "--hkv") == 0)
            { if (!parse_u32 (v, &j.h_kv)) goto bad; }
          else if (strcmp (argv[i - 1], "--flags") == 0)
            { if (!parse_u32 (v, &j.flags)) goto bad; }
          else if (strcmp (argv[i - 1], "--in-dt") == 0)
            { if (!parse_u32 (v, &j.in_dtype)) goto bad; }
          else if (strcmp (argv[i - 1], "--out-dt") == 0)
            { if (!parse_u32 (v, &j.out_dtype)) goto bad; }
          else if (strcmp (argv[i - 1], "--scale") == 0)
            { if (!parse_u32 (v, &j.scale_bits)) goto bad; }
          else if (strcmp (argv[i - 1], "--seed") == 0)
            { if (!parse_u32 (v, &seed)) goto bad; }
          else
            goto bad;
        }
      else
        goto bad;
    }
  return do_gen (argv[2], j, seed);
bad:
  usage ();
  return 2;
}
