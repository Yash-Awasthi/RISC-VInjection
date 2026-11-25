/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Run one raw attn case through the host core, for the sanitizer builds.

     attn_sanitize_driver CASE OUT

   CASE is a 56-byte little-endian header followed by a guest memory image:

     char     magic[8]   "SANCASE1"
     uint64_t mem_size
     uint64_t x, w, c, y addresses of X, attn_weights, attn_cfg, Y
     uint32_t xlen
     uint32_t zero

   OUT receives the raw out_dtype bytes of Y.  The descriptor layouts come
   from include/attn_abi.h and the image was laid out by tools/vectors.py, so
   nothing here parses JSON.  Exit 0 when the run wrote Y, 1 when the core
   reported a fault, 2 on a bad file.  */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attn_abi.h"

#define HDR_SIZE 56u
#define OFF_MAGIC 0u
#define OFF_SIZE 8u
#define OFF_X 16u
#define OFF_W 24u
#define OFF_C 32u
#define OFF_Y 40u
#define OFF_XLEN 48u

/* tests/host/attn_host.c; returns 0, an illegal configuration, or an access
   outside mem.  */
extern int attn_host_run (unsigned char *mem, uint64_t size, uint64_t y,
			  uint64_t x, uint64_t w, uint64_t c, unsigned xlen);

static uint64_t
get64 (const unsigned char *p)
{
  uint64_t v;
  memcpy (&v, p, sizeof v);
  return v;
}

static uint32_t
get32 (const unsigned char *p)
{
  uint32_t v;
  memcpy (&v, p, sizeof v);
  return v;
}

int
main (int argc, char **argv)
{
  unsigned char hdr[HDR_SIZE];
  unsigned char *mem;
  struct attn_cfg cfg;
  uint64_t size, x, w, c, y, bytes;
  unsigned xlen;
  uint32_t elem;
  FILE *f;

  if (argc != 3)
    {
      fprintf (stderr, "usage: %s CASE OUT\n", argv[0]);
      return 2;
    }
  f = fopen (argv[1], "rb");
  if (!f)
    {
      fprintf (stderr, "cannot open %s\n", argv[1]);
      return 2;
    }
  if (fread (hdr, 1, HDR_SIZE, f) != HDR_SIZE
      || memcmp (hdr + OFF_MAGIC, "SANCASE1", 8) != 0)
    {
      fprintf (stderr, "%s: not a case file\n", argv[1]);
      fclose (f);
      return 2;
    }
  size = get64 (hdr + OFF_SIZE);
  x = get64 (hdr + OFF_X);
  w = get64 (hdr + OFF_W);
  c = get64 (hdr + OFF_C);
  y = get64 (hdr + OFF_Y);
  xlen = get32 (hdr + OFF_XLEN);
  mem = malloc (size ? size : 1);
  if (!mem)
    {
      fprintf (stderr, "cannot allocate %llu bytes\n",
	       (unsigned long long) size);
      fclose (f);
      return 2;
    }
  if (fread (mem, 1, size, f) != size)
    {
      fprintf (stderr, "%s: truncated image\n", argv[1]);
      free (mem);
      fclose (f);
      return 2;
    }
  fclose (f);

  if (c > size || size - c < sizeof cfg)
    {
      fprintf (stderr, "%s: attn_cfg outside the image\n", argv[1]);
      free (mem);
      return 2;
    }
  memcpy (&cfg, mem + c, sizeof cfg);
  if (cfg.out_dtype == ATTN_DT_F32)
    elem = 4;
  else if (cfg.out_dtype == ATTN_DT_BF16)
    elem = 2;
  else
    {
      fprintf (stderr, "%s: bad out_dtype %u\n", argv[1], cfg.out_dtype);
      free (mem);
      return 2;
    }
  bytes = (uint64_t) cfg.n * cfg.e * elem;
  if (y > size || size - y < bytes)
    {
      fprintf (stderr, "%s: Y outside the image\n", argv[1]);
      free (mem);
      return 2;
    }

  if (attn_host_run (mem, size, y, x, w, c, xlen) != 0)
    {
      fprintf (stderr, "%s: attn_host_run failed\n", argv[1]);
      free (mem);
      return 1;
    }
  f = fopen (argv[2], "wb");
  if (!f)
    {
      fprintf (stderr, "cannot write %s\n", argv[2]);
      free (mem);
      return 2;
    }
  if (fwrite (mem + y, 1, bytes, f) != bytes)
    {
      fprintf (stderr, "%s: short write\n", argv[2]);
      fclose (f);
      free (mem);
      return 2;
    }
  fclose (f);
  free (mem);
  return 0;
}
