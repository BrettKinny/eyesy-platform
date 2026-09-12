# DSP performance experiment

`tools/dsp_benchmark.cpp` is a standalone benchmark; compile it with
`g++ -O2 -Iengine/src tools/dsp_benchmark.cpp engine/src/core.cpp -o /tmp/dsp_benchmark`.
It runs 20 warmup analyses followed by 1000 stereo analyses and reports the
mean microseconds per analysis. Run before and after the FFT change on the same
machine/build flags when evaluating a speedup.

The post-change standalone ARM benchmark ran on the real CM3+ during the
2026-09-12 overnight session: 1000 stereo analyses averaged **619.862 µs** after
warmup. No pre-change target baseline was captured, so this establishes a current
cost, not a measured speedup. It excludes rendering and audio-device latency.

The FFT now caches its Hann window, normalization sum, bit-reversal permutation,
and 1024-point twiddle factors in a thread-safe function-local table. This
removes repeated trigonometric setup from every channel transform while keeping
the existing windowing and one-sided normalization semantics.

Numerical checks are in `tests/dsp_regression.cpp`; compile with
`g++ -O2 -Iengine/src tests/dsp_regression.cpp engine/src/core.cpp -o /tmp/dsp_regression`.
