/* attn_abi.h -- architectural interface of the RISC-V Xattn extension.

   One instruction computes a complete multi-head self-attention block:

     attn  rd, rs1, rs2, rs3
       rd  = address of Y        [n x e]      out_dtype   (written)
       rs1 = address of X        [n x e]      in_dtype    (read)
       rs2 = address of struct attn_weights               (read)
       rs3 = address of struct attn_cfg                   (read)

   Semantics (all arithmetic in binary32, see docs/01-instruction-spec.md):

     Q = X Wq + bq          Wq [e x e]
     K = X Wk + bk          Wk [e x kv]   kv = h_kv * d,  d = e / h
     V = X Wv + bv          Wv [e x kv]
     for each head j:  g = j / (h / h_kv)
       A_j = softmax(Q_j K_g^T * scale + M) V_g     (causal: keys > query masked)
     Y = concat(A_0 .. A_{h-1}) Wo + bo              Wo [e x e]

   This header is shared by the C library (attn.h), the Spike and QEMU
   execution models (attn_core.h) and the tests; it must stay plain C.  */

#ifndef ATTN_ABI_H
#define ATTN_ABI_H

#include <stdint.h>

/* custom-3 major opcode, funct3 = 1, funct2 = 3, R4 operand layout: the only
   R4 slots that overlap no standard or vendor encoding are in custom-3.  */
#define ATTN_MATCH 0x0600107bu
#define ATTN_MASK  0x0600707fu

#define ATTN_DT_F32  0u
#define ATTN_DT_BF16 1u

#define ATTN_F_CAUSAL (1u << 0)   /* query i attends only to keys 0..i */
#define ATTN_F_SCALE  (1u << 1)   /* use cfg.scale, not 1/sqrt(d) */
#define ATTN_F_ALL    (ATTN_F_CAUSAL | ATTN_F_SCALE)

/* Implementation limits of the reference execution model.  An instruction
   whose configuration exceeds them raises an illegal-instruction trap.  */
#define ATTN_MAX_N 4096u
#define ATTN_MAX_E 2048u

/* rs2.  Weights are row-major [in][out] in in_dtype; biases are binary32.
   A zero bias pointer means "no bias".  */
struct attn_weights
{
  uint64_t wq, wk, wv, wo;
  uint64_t bq, bk, bv, bo;
};

/* rs3.  mask, when non-zero, points at an [n x n] binary32 additive mask.  */
struct attn_cfg
{
  uint32_t n;          /* sequence length */
  uint32_t e;          /* model width, e = h * d */
  uint32_t h;          /* query heads */
  uint32_t h_kv;       /* key/value heads; 0 means h (no grouping) */
  uint32_t flags;      /* ATTN_F_* */
  uint16_t in_dtype;   /* ATTN_DT_* of X and W* */
  uint16_t out_dtype;  /* ATTN_DT_* of Y */
  uint32_t scale_bits; /* binary32 bits, used only with ATTN_F_SCALE */
  uint32_t reserved;   /* must be zero */
  uint64_t mask;
};

#define ATTN_WEIGHTS_SIZE 64u
#define ATTN_CFG_SIZE     40u

#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
_Static_assert (sizeof (struct attn_weights) == ATTN_WEIGHTS_SIZE,
		"attn_weights layout");
_Static_assert (sizeof (struct attn_cfg) == ATTN_CFG_SIZE, "attn_cfg layout");
#endif

#endif /* ATTN_ABI_H */
