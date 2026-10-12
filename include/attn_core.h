/* attn_core.h -- the one executable definition of the attn instruction.

   Included unchanged by the Spike and QEMU execution models and by the host
   reference used in tests, so all three produce bit-identical results.
   Guest memory is reached only through struct attn_mem; a load or store
   callback may trap (C++ throw or longjmp), so this code owns no resources:
   the caller supplies the scratch buffer.  */

#ifndef ATTN_CORE_H
#define ATTN_CORE_H

#include <math.h>
#include <stdint.h>
#include "attn_abi.h"

/* Separate rounding of every product and sum is part of the definition.  */
#if defined(__clang__)
#pragma clang fp contract(off)
#elif defined(__GNUC__)
#pragma GCC push_options
#pragma GCC optimize("fp-contract=off")
#endif

struct attn_mem
{
  void *ctx;
  uint16_t (*ld16) (void *ctx, uint64_t addr);
  uint32_t (*ld32) (void *ctx, uint64_t addr);
  uint64_t (*ld64) (void *ctx, uint64_t addr);
  void (*st16) (void *ctx, uint64_t addr, uint16_t val);
  void (*st32) (void *ctx, uint64_t addr, uint32_t val);
};

static inline float
attn_f32_from_bits (uint32_t u)
{
  union { uint32_t u; float f; } c;
  c.u = u;
  return c.f;
}

static inline uint32_t
attn_bits_from_f32 (float f)
{
  union { uint32_t u; float f; } c;
  c.f = f;
  return c.u;
}

/* Round to nearest, ties to even; NaNs stay NaN and become quiet.  */
static inline uint16_t
attn_bf16_from_f32 (float f)
{
  uint32_t u = attn_bits_from_f32 (f);
  if ((u & 0x7fffffffu) > 0x7f800000u)
    return (uint16_t) ((u >> 16) | 0x0040u);
  return (uint16_t) ((u + 0x7fffu + ((u >> 16) & 1u)) >> 16);
}

static inline void
attn_read_desc (const struct attn_mem *m, uint64_t wa, uint64_t ca,
		struct attn_weights *w, struct attn_cfg *c)
{
  w->wq = m->ld64 (m->ctx, wa + 0);
  w->wk = m->ld64 (m->ctx, wa + 8);
  w->wv = m->ld64 (m->ctx, wa + 16);
  w->wo = m->ld64 (m->ctx, wa + 24);
  w->bq = m->ld64 (m->ctx, wa + 32);
  w->bk = m->ld64 (m->ctx, wa + 40);
  w->bv = m->ld64 (m->ctx, wa + 48);
  w->bo = m->ld64 (m->ctx, wa + 56);
  c->n = m->ld32 (m->ctx, ca + 0);
  c->e = m->ld32 (m->ctx, ca + 4);
  c->h = m->ld32 (m->ctx, ca + 8);
  c->h_kv = m->ld32 (m->ctx, ca + 12);
  c->flags = m->ld32 (m->ctx, ca + 16);
  {
    uint32_t dt = m->ld32 (m->ctx, ca + 20);
    c->in_dtype = (uint16_t) dt;
    c->out_dtype = (uint16_t) (dt >> 16);
  }
  c->scale_bits = m->ld32 (m->ctx, ca + 24);
  c->reserved = m->ld32 (m->ctx, ca + 28);
  c->mask = m->ld64 (m->ctx, ca + 32);
}

/* Number of binary32 scratch elements the instruction needs, or 0 when the
   configuration is reserved (the instruction then raises illegal-instruction).
   On RV32 (xlen 32) every pointer in the weights descriptor must fit in
   32 bits.  */
static inline uint64_t
attn_scratch_floats (const struct attn_cfg *c, const struct attn_weights *w,
		     unsigned xlen)
{
  uint64_t n = c->n, e = c->e, h = c->h;
  uint64_t hkv = c->h_kv ? c->h_kv : c->h;
  uint64_t kv;

  if (n == 0 || e == 0 || h == 0 || n > ATTN_MAX_N || e > ATTN_MAX_E)
    return 0;
  if (e % h || h % hkv || (c->flags & ~ATTN_F_ALL) || c->reserved)
    return 0;
  if (c->in_dtype > ATTN_DT_BF16 || c->out_dtype > ATTN_DT_BF16)
    return 0;
  if (w->wq == 0 || w->wk == 0 || w->wv == 0 || w->wo == 0)
    return 0;
  if (xlen == 32
      && ((w->wq | w->wk | w->wv | w->wo | w->bq | w->bk | w->bv | w->bo
	   | c->mask) >> 32))
    return 0;
  kv = hkv * (e / h);
  /* X, Wq, Wk, Wv, Wo, Q, K, V, concat, one score row, biases, mask.  */
  return n * e + e * e + 2 * e * kv + e * e + n * e + 2 * n * kv + n * e + n
	 + 2 * e + 2 * kv + (c->mask ? n * n : 0);
}

static inline float
attn_ld_elem (const struct attn_mem *m, uint64_t base, uint64_t i,
	      unsigned dt)
{
  if (dt == ATTN_DT_BF16)
    return attn_f32_from_bits ((uint32_t) m->ld16 (m->ctx, base + 2 * i)
			       << 16);
  return attn_f32_from_bits (m->ld32 (m->ctx, base + 4 * i));
}

static inline void
attn_ld_vec (const struct attn_mem *m, uint64_t base, uint64_t count,
	     unsigned dt, float *dst)
{
  for (uint64_t i = 0; i < count; i++)
    dst[i] = attn_ld_elem (m, base, i, dt);
}

/* out[r][c] = sum_k in[r][k] * w[k][c] + b[c], accumulated in k order.  */
static inline void
attn_matmul (const float *in, const float *w, const float *b, float *out,
	     uint64_t rows, uint64_t inner, uint64_t cols)
{
  for (uint64_t r = 0; r < rows; r++)
    for (uint64_t c = 0; c < cols; c++)
      {
	float acc = 0.0f;
	for (uint64_t k = 0; k < inner; k++)
	  acc = acc + in[r * inner + k] * w[k * cols + c];
	out[r * cols + c] = b ? acc + b[c] : acc;
      }
}

/* Execute attn.  w and c come from attn_read_desc; the caller has checked
   attn_scratch_floats (c, w, xlen) != 0 and passes that many floats.  */
static inline void
attn_execute (const struct attn_mem *m, uint64_t y_addr, uint64_t x_addr,
	      const struct attn_weights *w, const struct attn_cfg *c,
	      float *s)
{
  uint64_t n = c->n, e = c->e, h = c->h;
  uint64_t hkv = c->h_kv ? c->h_kv : c->h;
  uint64_t d = e / h, kv = hkv * d, group = h / hkv;
  unsigned dt = c->in_dtype;
  float scale = (c->flags & ATTN_F_SCALE)
		? attn_f32_from_bits (c->scale_bits)
		: 1.0f / sqrtf ((float) d);

  float *X = s;
  float *Wq = X + n * e;
  float *Wk = Wq + e * e;
  float *Wv = Wk + e * kv;
  float *Wo = Wv + e * kv;
  float *Q = Wo + e * e;
  float *K = Q + n * e;
  float *V = K + n * kv;
  float *C = V + n * kv;
  float *P = C + n * e;
  float *bq = P + n;
  float *bk = bq + e;
  float *bv = bk + kv;
  float *bo = bv + kv;
  float *M = bo + e;

  /* Every load happens before the first store, so a trap on any input
     leaves Y untouched and the instruction can simply be re-executed.  */
  attn_ld_vec (m, x_addr, n * e, dt, X);
  attn_ld_vec (m, w->wq, e * e, dt, Wq);
  attn_ld_vec (m, w->wk, e * kv, dt, Wk);
  attn_ld_vec (m, w->wv, e * kv, dt, Wv);
  attn_ld_vec (m, w->wo, e * e, dt, Wo);
  if (w->bq) attn_ld_vec (m, w->bq, e, ATTN_DT_F32, bq);
  if (w->bk) attn_ld_vec (m, w->bk, kv, ATTN_DT_F32, bk);
  if (w->bv) attn_ld_vec (m, w->bv, kv, ATTN_DT_F32, bv);
  if (w->bo) attn_ld_vec (m, w->bo, e, ATTN_DT_F32, bo);
  if (c->mask) attn_ld_vec (m, c->mask, n * n, ATTN_DT_F32, M);

  attn_matmul (X, Wq, w->bq ? bq : 0, Q, n, e, e);
  attn_matmul (X, Wk, w->bk ? bk : 0, K, n, e, kv);
  attn_matmul (X, Wv, w->bv ? bv : 0, V, n, e, kv);

  for (uint64_t hd = 0; hd < h; hd++)
    {
      uint64_t qo = hd * d, ko = (hd / group) * d;
      for (uint64_t i = 0; i < n; i++)
	{
	  uint64_t lim = (c->flags & ATTN_F_CAUSAL) ? i + 1 : n;
	  float mx = -INFINITY, l = 0.0f;
	  for (uint64_t j = 0; j < lim; j++)
	    {
	      float acc = 0.0f;
	      for (uint64_t t = 0; t < d; t++)
		acc = acc + Q[i * e + qo + t] * K[j * kv + ko + t];
	      acc = acc * scale;
	      if (c->mask)
		acc = acc + M[i * n + j];
	      P[j] = acc;
	      if (acc > mx)
		mx = acc;
	    }
	  /* Plain softmax: a row whose every score is -inf yields NaN, exactly
	     as the equivalent C loops do (and as PyTorch does).  */
	  for (uint64_t j = 0; j < lim; j++)
	    {
	      P[j] = expf (P[j] - mx);
	      l = l + P[j];
	    }
	  for (uint64_t t = 0; t < d; t++)
	    {
	      float acc = 0.0f;
	      for (uint64_t j = 0; j < lim; j++)
		acc = acc + P[j] * V[j * kv + ko + t];
	      C[i * e + qo + t] = acc / l;
	    }
	}
    }

  /* Q is dead here; reuse it for Y before rounding to out_dtype.  */
  attn_matmul (C, Wo, w->bo ? bo : 0, Q, n, e, e);
  for (uint64_t i = 0; i < n * e; i++)
    {
      if (c->out_dtype == ATTN_DT_BF16)
	m->st16 (m->ctx, y_addr + 2 * i, attn_bf16_from_f32 (Q[i]));
      else
	m->st32 (m->ctx, y_addr + 4 * i, attn_bits_from_f32 (Q[i]));
    }
}

#if !defined(__clang__) && defined(__GNUC__)
#pragma GCC pop_options
#endif

#endif /* ATTN_CORE_H */
