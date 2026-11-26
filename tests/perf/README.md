# tests/perf: the recognizer measured per shape

`bench.c` is linked with `demo/mha_plain.c` compiled twice by `Makefile`:
`mha_attn` at plain `-O2` (one `attn` plus the runtime guard) and
`mha_loops` with `-fno-tree-loop-attn`. Both run on identical inputs and the
program prints one CSV line per call with `minstret` and `mcycle` read
around it, so the numbers price the whole function call.

Reproduce:

```bash
make -C tests/perf check      # writes build/perf/spike.csv and qemu.csv
```

The `expected/` copies are the run published in `docs/results.md`:

- produced by `make -C tests/perf check` at `076aeab`
  (`076aeab98cc467f9a0b8029d45035506af39492e`)
- toolchain from Full run 45857819667,
  `xattn-toolchain-076aeab98cc4.tar.xz`, sha256
  `c60cb4bcd5225edb178946c8a16d3496304d79943899850845cd446acca88e95`
  (GCC 16.2.1 20261012)
- simulators from the same run, `xattn-simulators-076aeab98cc4.tar.xz`,
  sha256 `03f7938441abdb774bc598d1f92f0090e55926ccf05a811aedcbebf1bb15d493`
  (Spike 1.1.1-dev at `2aaf784`, QEMU 11.1.50)
- QEMU runs with `-icount shift=0,sleep=off`, because without it `minstret`
  and `mcycle` read a host clock; with it the counts are the guest's
  instructions and agree with Spike exactly.

`tests/test_perf.py` checks these files, never the simulators: the two
simulators agree, `attn` retires fewer instructions than the loops on every
valid shape, the guard costs a bounded number of instructions, and the cost
model in `docs/results.md` is recomputed from these rows.
