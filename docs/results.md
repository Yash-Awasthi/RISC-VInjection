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
