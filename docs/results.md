# Results

## No silicon measurement exists

This repository contains no measurement from real hardware. No RISC-V board
was available to the authors, so nothing here was run on silicon, and no
silicon speedup is claimed anywhere in this repository: not in the README,
not in the documentation, not in the artefacts. Any figure described as a
speedup that you find outside this repository was not produced here.

Status on 2026-11-26: no board available, no silicon number. This page will
be replaced when one exists, not filled in with an estimate.

## What the repository does establish

Two things, both from software:

- Functional equivalence: the instruction and the C code it replaces produce
  the same outputs for the frozen vectors and for the checked shapes.
- Static and dynamic instruction counts: the disassembly shows one `attn`
  where the loops were, and Spike reports how many instructions each build
  executed. These are counts, not time, and not a speedup.

Those are the only numbers this repository reports, and they come from the
simulator.

## What would be measured on a board

The plan's row asks for a measurement on real hardware. On a board the
measurement would be:

1. Build the same source twice with `-O2`, once with the recognizer enabled
   and once with `-fno-tree-loop-attn`, so the compiler and flags are the
   only variables.
2. Run each build for a fixed set of shapes `(n, e, h)` covering the
   instruction's limits, with the same input data and the same number of
   repetitions for both builds.
3. Read the retired-instruction counter and the cycle counter around each
   run, through the hart's performance counters or a debug probe, and take
   the median of the repetitions.
4. Record cycles per shape and retired instructions per shape, and report
   the ratio between the two builds per shape rather than one aggregate
   number.
5. Record the conditions with the result: board and hart, ISA string, clock,
   memory and cache configuration, and the exact compiler flags. A cycle
   count without the clock and the cache state is not reproducible.

The table below is the shape of that result. It is empty on purpose; no
entry has been filled, because no board was available.

| Shape `(n, e, h)` | Retired instructions, loops | Retired instructions, `attn` | Cycles, loops | Cycles, `attn` |
|---|---|---|---|---|
| — | not measured | not measured | not measured | not measured |

## Where results live instead

- `artifacts/README.md` and `artifacts/attncc-run.txt`: the Spike run of both
  builds, with the executed-instruction counts and the output difference.
- `docs/artifacts.html`: the static report generated from the committed JSON
  and the artefacts README.
- `tests/vectors/`: the frozen vectors, with the hash that `tests/test_vectors.py`
  pins.

The simulator number is an instruction count from Spike. It says how much
work the two builds issue; it does not say how fast either one runs on any
particular core, and it is not a substitute for the board measurement above.

## `attn` against the loops: both simulators, per shape

Produced by `make -C tests/perf check` at `076aeab`, with the toolchain
packed by Full run 45857819667 (GCC 16.2.1 20261012) and the simulators from
the same run (Spike 1.1.1-dev at `2aaf784`, QEMU 11.1.50). Raw lines:
`tests/perf/expected/spike.csv` and `tests/perf/expected/qemu.csv`; the
provenance is in `tests/perf/README.md`.

Method: `mha_attn` is `demo/mha_plain.c` compiled at plain `-O2`, so it
contains one `attn` plus the runtime guard; `mha_loops` is the same file
with `-fno-tree-loop-attn`, so it contains the loops as written. One
bare-metal image calls each once unmeasured (the first call grows the heap)
and once measured, on the same inputs, with `minstret` and `mcycle` read
immediately around the call with `csrr`. There is no repetition loop: both
simulators are deterministic and repeated runs print the same bytes.

The two simulators report the same retired-instruction count for every row,
exactly. Neither models a pipeline. Spike's `mcycle` advances once per
retired instruction, and QEMU is run with `-icount shift=0,sleep=off` so its
`mcycle` counts guest instructions instead of a host clock; without
`-icount` QEMU's counters are host-derived and are not reported. The cycle
column is therefore the same measurement as the instruction column on both
simulators, not a cycle model, and the ratio column is a ratio of retired
instructions, not a speedup.

| Shape `(n, e, h)` | Retired instructions, loops | Retired instructions, `attn` | Ratio | Cycles, loops | Cycles, `attn` |
|---|---|---|---|---|---|
| `(4, 8, 2)` | 12591 | 1026 | 12.3 | 12591 | 1025 |
| `(8, 16, 4)` | 82944 | 1031 | 80.5 | 82944 | 1030 |
| `(16, 32, 4)` | 582644 | 1029 | 566.2 | 582644 | 1028 |
| `(16, 64, 8)` | 2081031 | 1078 | 1930.5 | 2081031 | 1077 |
| `(32, 64, 8)` | 4513294 | 1077 | 4190.6 | 4513294 | 1076 |
| `(64, 128, 8)` | 34535911 | 1369 | 25227.1 | 34535911 | 1368 |

The `attn` column is flat to within 4% from `(4, 8, 2)` to `(32, 64, 8)`:
what the compiler emits around the instruction (the guard, five `malloc`
calls, the descriptor, five `free` calls) does not grow with the shape. The
loops grow with `n * n * e` and `n * e * e` as written.

## The runtime guard when the instruction cannot be used

Same harness, sizes the guard rejects. On these inputs the `attn` build
evaluates the guard, takes the fallback edge and runs the same loops as the
`loops` build, so the difference between the two rows is what the guard and
its branch cost. Raw lines: the `g_` cases of
`tests/perf/expected/spike.csv`.

| Case `(n, e, h)` | Why the guard fails | Instructions, attn build | Instructions, loops build | Delta |
|---|---|---|---|---|
| `(0, 32, 4)` | `n < 1` | 931 | 918 | +13 |
| `(8, 33, 8)` | `e % h != 0` | 294098 | 294031 | +67 |
| `(8, 32, 0)` | `h < 1` | 242039 | 242026 | +13 |

The guard costs 13 to 67 retired instructions once per call, never per
element: on the smallest failing case it is 13 instructions on a call of
918, and on the `e % h != 0` case it is 67 on 294031. The 67 is larger
because that path still computes `d = e / h` and the guard's `d * h == e`
test after the range checks. A program whose sizes never satisfy the
descriptor limit pays this once per call and nothing else; the loops it was
compiled with are unchanged.

## Cost model from the descriptor

The `attn` build's instruction count is modelled from `(n, e, h)` alone:

```
I(n, e, h) = 1017.6 + 0.0423 * n * e
```

fitted by least squares on the six valid shapes of
`tests/perf/expected/spike.csv`, with the basis the code shape suggests: a
fixed part (guard, descriptor, the five `malloc`/`free` pairs) and a part
that grows with the buffer the descriptor names (`n * e` elements). `h`
enters only through the guard (`d * h == e`), which is a comparison, so the
fit has no term in `h`.

| Shape `(n, e, h)` | Measured | Predicted | Error |
|---|---|---|---|
| `(4, 8, 2)` | 1026 | 1019 | -0.7% |
| `(8, 16, 4)` | 1031 | 1023 | -0.8% |
| `(16, 32, 4)` | 1029 | 1039 | +1.0% |
| `(16, 64, 8)` | 1078 | 1061 | -1.6% |
| `(32, 64, 8)` | 1077 | 1104 | +2.5% |
| `(64, 128, 8)` | 1369 | 1364 | -0.4% |

Largest relative error 2.6% over the six shapes, and the two coefficients are
positive. `tools/perf_report.py` prints this table from the CSV, and
`tests/test_perf.py` recomputes the fit and asserts the published
coefficients and the 2.6% bound, so the table cannot drift from the data.
The model prices the code around the instruction, not the instruction's own
latency: no simulator here has a cost for `attn` itself beyond one retired
instruction, and no silicon number exists (see the top of this page).