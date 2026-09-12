# Input workflow

Desktop preview accepts `--audio-wav PATH` as an analysis-only source. The WAV
reader supports RIFF/WAVE PCM 8/16/24/32-bit and IEEE-float 32-bit, mono or
multichannel (the first two channels are used; mono is duplicated). Samples are
clamped to `[-1,1]`, played once at the file's actual sample rate, and never
sent to a physical output. Files have a 256 MiB container limit and a 64 MiB
decoded stereo-float limit (about 175 seconds at 48 kHz), plus a 28.8-million
frame ceiling. Chunks are scanned and decoded in bounded blocks; malformed or
unsupported files are rejected before playback. Supported sample rates are
8–192 kHz.

`--record PATH` records live key, OSC knob, and MIDI input as the existing
frame-indexed replay JSON. Desktop key releases use `key_release`; hardware
button releases use `hardware_release`, preserving shift and held-key state.
The initial five knob values are recorded at frame 0. This is input-event
recording, not a full audiovisual capture: mode/settings/audio configuration is
not included. `--record-limit N` bounds memory and output (default
10,000, maximum 100,000); events beyond the limit are dropped and status
reports `recording_truncated`. Recording is written atomically on exit. Replay
remains deterministic: events are applied at their frame, live input is
disabled, and replay does not recursively record.

Examples:

```sh
./eyesyctl preview starter --headless --frames 600 --audio-wav samples.wav
./eyesyctl preview starter --headless --frames 300 --record local/demo.json
./eyesyctl preview starter --headless --replay local/demo.json
```

`status.json` includes `audio_available`, `audio_source`, actual
`audio_sample_rate`, `audio_rms_left/right`, `audio_sequence`, and dropped
callback frames. These fields make headless capture checks possible without
requiring a sound output device.
