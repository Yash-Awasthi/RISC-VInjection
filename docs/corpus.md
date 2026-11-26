# The recognizer on the corpus

The corpus is four real projects, fetched on 2026-11-26 into the gitignored
`build/corpus/`: llama.cpp `436d7e81`, MNN `54694759`, ncnn `3c9504a6` and
llama2.c `350e04fe` (the trees, their tarball hashes and their licences are
recorded in `.fleet/evidence/RISC-VInjection/corpus-303-350.md`).
`tools/corpus_scan.py` selects the files that implement attention or its
neighbours, by name and by content, and tries to compile each one with the
toolchain built from this repository (GCC 16.2.1 20261012).

## Method

Each file is compiled to an object at `-O2` twice: once with the recognizer
(the default) and once with `-fno-tree-loop-attn`. The two objects are
compared by sha256 and by instruction count. Identical objects mean the pass
replaced nothing; a difference means the recognizer changed the code. The
`attn` mnemonic is counted in the disassembly. A file that does not compile
is recorded with the error, not with a count, because a count would describe
code that was never built.

Two kinds of stand-in header are used, and neither is linked or run:
`sys/mman.h` plus a `clock_gettime` declaration for the POSIX calls the
projects make, and `ggml-version.h` for the header CMake normally generates.
They exist only so the C front end reaches the loops; the tool writes them
to a temporary directory and nothing is added to the corpus.

`demo/mha_plain.c` is the control: the same command line must produce one
`attn` there, or the scan is measuring the wrong compiler.

## Result

| File | Built | `attn` | Instruction count, loops | Instruction count, recognizer |
|---|---|---|---|---|
| `demo/mha_plain.c` | yes | 1 | 351 | 393 |
| `build/corpus/llama2c/run.c` | yes | 0 | 2827 | 2827 |
| `build/corpus/llama2c/runq.c` | yes | 0 | 3183 | 3183 |
| `build/corpus/llamacpp/ggml/src/ggml.c` | yes | 0 | 22943 | 22943 |
| `build/corpus/llamacpp/ggml/src/ggml-cpu/ggml-cpu.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/flash_attn_ext_f32.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/flash_attn_ext_f16_me.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/softmax_f32.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/rope_f32.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/gated_delta_net_f32.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-et/et-kernels/src/rwkv_wkv6_f32.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-hexagon/htp/flash-attn-ops.c` | no | - | - | - |
| `build/corpus/llamacpp/ggml/src/ggml-hexagon/htp/softmax-ops.c` | no | - | - | - |
| `build/corpus/mnn/source/backend/cpu/CPUAttention.cpp` | no | - | - | - |
| `build/corpus/mnn/source/backend/cpu/CPULinearAttention.cpp` | no | - | - | - |
| `build/corpus/mnn/source/backend/cpu/riscv/rvv/MNNRvvAttentionFunctions.cpp` | no | - | - | - |
| `build/corpus/ncnn/src/layer/multiheadattention.cpp` | no | - | - | - |
| `build/corpus/ncnn/src/layer/arm/multiheadattention_arm.cpp` | no | - | - | - |

## What was recognised, and what was not

Four of the eighteen files compile, and none of the four holds a recognised
attention region. With the recognizer on and off, `run.c` (2827
instructions), `runq.c` (3183) and `ggml.c` (22943) produce byte-identical
objects, while the control differs (351 to 393) because it does contain the
pattern. So recall is zero over the attention implementations that could be
built, and precision is zero of zero: no loop was replaced, so there was
nothing that could be wrong.

The reasons are per file, not one sentence:

- **No candidate nest.** Before it tries anything the pass tests a loop pair
  whose inner loop has three children, and it prints one line for every
  candidate it then rejects. These three files printed no such line, so
  their attention code never reached the proof. Clause G1 of the grammar in
  `docs/recognizer.md` states what the proof needs: three projection nests
  and an output projection around the attention, over local scratch
  allocations. llama2.c keeps one `att` buffer inside the layer loop, and
  ggml.c's flash-attention kernel works over pointers in a params struct,
  not over five nests with `malloc`ed `q`, `k`, `v` and `c`.
- **C++ sources.** This toolchain is configured `--enable-languages=c`, so
  `gcc -x c++` answers `language c++ not recognized`. Every MNN and ncnn
  attention implementation in the corpus is C++, so this toolchain cannot
  compile any of them; the recognizer is a middle-end pass and does not care
  about the source language, but this build's front end does.
- **Vendor SDKs.** The ggml-et kernels include `etsoc/common/utils.h` and
  the Hexagon kernels include `HAP_*.h`; neither SDK is in the corpus or in
  this repository, so those files do not compile on this machine.

## Cost, per file

For the three files that build, the two objects are identical, so the
recognizer's cost on this corpus is exactly zero: no instruction added, no
instruction removed, `attn` count zero. The control shows the other side of
the same measurement: replacing the five nests adds 42 instructions of guard
and descriptor set-up at `-O2` (351 to 393) and, when the guard passes,
executes one `attn` instead of the loops; the executed counts are in
`docs/results.md`.

These are static counts. They say nothing about the runtime cost of an
unrecognised kernel, because nothing was replaced.

`tests/test_corpus_report.py` checks this page against
`tests/corpus/scan.json`, which the tool wrote, so the table cannot drift
from the run.
