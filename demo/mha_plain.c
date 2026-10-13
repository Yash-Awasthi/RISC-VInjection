/* Multi-head self-attention written as ordinary C loops.

   Compiled with plain -O2 (the toolchain defaults to Xattn), GCC proves
   that this function computes exactly what one attn instruction computes
   and replaces all of the loops below with that instruction.  */

#include <math.h>
#include <stdlib.h>

void
mha (float *restrict y, const float *restrict x,
     const float *restrict wq, const float *restrict wk,
     const float *restrict wv, const float *restrict wo,
     const float *restrict bq, const float *restrict bk,
     const float *restrict bv, const float *restrict bo,
     int n, int e, int h)
{
  int d = e / h;
  float scale = 1.0f / sqrtf ((float) d);
  float *q = malloc (sizeof (float) * n * e);
  float *k = malloc (sizeof (float) * n * e);
  float *v = malloc (sizeof (float) * n * e);
  float *c = malloc (sizeof (float) * n * e);
  float *p = malloc (sizeof (float) * n);

  /* Q = X Wq + bq, K = X Wk + bk, V = X Wv + bv.  */
  for (int i = 0; i < n; i++)
    for (int j = 0; j < e; j++)
      {
	float acc = 0.0f;
	for (int t = 0; t < e; t++)
	  acc += x[i * e + t] * wq[t * e + j];
	q[i * e + j] = acc + bq[j];
      }
  for (int i = 0; i < n; i++)
    for (int j = 0; j < e; j++)
      {
	float acc = 0.0f;
	for (int t = 0; t < e; t++)
	  acc += x[i * e + t] * wk[t * e + j];
	k[i * e + j] = acc + bk[j];
      }
  for (int i = 0; i < n; i++)
    for (int j = 0; j < e; j++)
      {
	float acc = 0.0f;
	for (int t = 0; t < e; t++)
	  acc += x[i * e + t] * wv[t * e + j];
	v[i * e + j] = acc + bv[j];
      }

  /* Per head: softmax (Q K^T * scale) V, causal.  */
  for (int hd = 0; hd < h; hd++)
    for (int i = 0; i < n; i++)
      {
	float mx = -INFINITY;
	for (int j = 0; j <= i; j++)
	  {
	    float s = 0.0f;
	    for (int t = 0; t < d; t++)
	      s += q[i * e + hd * d + t] * k[j * e + hd * d + t];
	    s = s * scale;
	    p[j] = s;
	    if (s > mx)
	      mx = s;
	  }
	float l = 0.0f;
	for (int j = 0; j <= i; j++)
	  {
	    p[j] = expf (p[j] - mx);
	    l += p[j];
	  }
	for (int t = 0; t < d; t++)
	  {
	    float acc = 0.0f;
	    for (int j = 0; j <= i; j++)
	      acc += p[j] * v[j * e + hd * d + t];
	    c[i * e + hd * d + t] = acc / l;
	  }
      }

  /* Y = concat (heads) Wo + bo.  */
  for (int i = 0; i < n; i++)
    for (int j = 0; j < e; j++)
      {
	float acc = 0.0f;
	for (int t = 0; t < e; t++)
	  acc += c[i * e + t] * wo[t * e + j];
	y[i * e + j] = acc + bo[j];
      }

  free (q);
  free (k);
  free (v);
  free (c);
  free (p);
}
