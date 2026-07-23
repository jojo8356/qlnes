# Epic 1 Audio Validation - 2026-07-22

## Scope Validated

Epic 1 was validated against the current in-process audio pipeline for a legal
synthetic mapper-0 NES fixture that configures Pulse 1 to NTSC A4.

Fixture:

- `_bmad-output/audio-validation/synthetic_a440.nes`
- Engine detected: `famitracker`
- Mapper: `0`
- Expected Pulse 1 frequency: `440.4 Hz`

Multi-song fixture:

- `_bmad-output/audio-validation/synthetic_two_song.nes`
- Engine detected: `famitracker`
- Mapper: `0`
- Declared songs: `0` and `1` via embedded `QLNESFTMETA1` song metadata

External FamiTone2 reference:

- `_bmad-output/external-fixtures/famitone2-v1.15/demo.nes`
- Source: Shiru FamiTone2 v1.15 public-domain archive
- `scan_famitone2_tables()` detects official music-data tables at CPU
  addresses `0x8983` and `0x9A85`.

External fan-ROM smoke fixture:

- `_bmad-output/external-fixtures/nova-the-squirrel-v1.0.6a/nova.nes`
- SHA-256:
  `e4780e90b9d1587489bfb797d2ca395be21371ea9262fa9f87f99324ec6960ab`
- Smoke command exits with `unsupported_mapper` for mapper `1`; no frequency
  equivalence claim is made for this ROM because qlnes does not recognize its
  audio engine and no expected reference frequency is bundled.

Synthetic FamiTone2 fixture:

- `_bmad-output/audio-validation/synthetic_famitone2.nes`
- Contains a raw FamiTone2 music-data table only: no `QLNESFTMETA1` metadata
  and no embedded NSF header.
- Declared sub-songs: `0` and `1`

Synthetic FamiTone2 note-change fixture:

- `_bmad-output/audio-validation/synthetic_famitone2_change.nes`
- Contains a raw FamiTone2 music-data table whose first sub-song changes from
  A4 to C5 after explicit FamiTone2 rows.

Synthetic FamiTone2 pulse-2 fixture:

- `_bmad-output/audio-validation/synthetic_famitone2_pulse2.nes`
- Contains a raw FamiTone2 music-data table whose first sub-song keeps pulse 1
  silent and renders C5 from pulse 2.

Synthetic FamiTone2 triangle fixture:

- `_bmad-output/audio-validation/synthetic_famitone2_triangle.nes`
- Contains a raw FamiTone2 music-data table whose first sub-song keeps both
  pulse channels silent and renders C5 from triangle.

## Runtime Evidence

WAV command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_a440.nes -o _bmad-output/audio-validation/tracks --format wav --frames 90 --engine-mode in-process --force --color never
```

WAV output:

- `_bmad-output/audio-validation/tracks/synthetic_a440.00.famitracker.wav`
- Duration: `1.497528 s`
- Peak-to-peak amplitude: `4895`
- Measured dominant frequency: `440.393 Hz`
- Expected frequency tolerance: `abs <= 2 Hz`

MP3 command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_a440.nes -o _bmad-output/audio-validation/tracks --format mp3 --frames 90 --engine-mode in-process --force --color never
```

MP3 output:

- `_bmad-output/audio-validation/tracks/synthetic_a440.00.famitracker.mp3`
- Decoded WAV: `_bmad-output/audio-validation/tracks/synthetic_a440.decoded.wav`
- Decoded duration: `1.541224 s`
- Decoded peak-to-peak amplitude: `21889`
- Decoded dominant frequency: `440.395 Hz`
- Expected frequency tolerance: `abs <= 3 Hz`

Multi-song WAV command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_two_song.nes -o _bmad-output/audio-validation/two-song-tracks --format wav --frames 90 --engine-mode in-process --force --color never
```

Multi-song WAV outputs:

- `_bmad-output/audio-validation/two-song-tracks/synthetic_two_song.00.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - Measured dominant frequency: `440.393 Hz`
  - `smpl` loop chunk: present
- `_bmad-output/audio-validation/two-song-tracks/synthetic_two_song.01.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - Measured dominant frequency: `522.713 Hz`
  - `smpl` loop chunk: absent

Unknown-engine fallback command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/unknown_mapper0.nes -o _bmad-output/audio-validation/unknown-tracks --format wav --frames 90 --engine-mode in-process --force --color never
```

Unknown-engine fallback output:

- `_bmad-output/audio-validation/unknown-tracks/unknown_mapper0.00.unknown.wav`
- `_bmad-output/audio-validation/unknown-bilan.json`
- Stderr includes `moteur=unknown`, `tier=2`, `mapper=0`,
  `sha256=44bc1c6d5610ba5bbc4f9782f25f34d04e6b6ad2a0a4880aa778c442c2168b3a`,
  and `statut=unverified`.
- `unknown-bilan.json` records schema `qlnes.audio_bilan.v1`, engine `unknown`,
  tier `2`, ROM SHA-256
  `44bc1c6d5610ba5bbc4f9782f25f34d04e6b6ad2a0a4880aa778c442c2168b3a`,
  and track status `unverified`; it does not record `pass`.

FamiTone2 table WAV command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_famitone2.nes -o _bmad-output/audio-validation/famitone2-tracks --format wav --frames 90 --engine-mode in-process --force --bilan _bmad-output/audio-validation/famitone2-bilan.json --color never
```

FamiTone2 table WAV outputs:

- `_bmad-output/audio-validation/famitone2-tracks/synthetic_famitone2.00.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - Measured dominant frequency: `440.400 Hz`
- `_bmad-output/audio-validation/famitone2-tracks/synthetic_famitone2.01.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - Measured dominant frequency: `522.713 Hz`

FamiTone2 note-change WAV outputs:

- `_bmad-output/audio-validation/famitone2-change-tracks/synthetic_famitone2_change.00.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - First segment measured dominant frequency: `440.413 Hz`
  - Second segment measured dominant frequency: `522.726 Hz`

FamiTone2 pulse-2 WAV command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_famitone2_pulse2.nes -o _bmad-output/audio-validation/famitone2-pulse2-tracks --format wav --frames 90 --engine-mode in-process --force --bilan _bmad-output/audio-validation/famitone2-pulse2-bilan.json --color never
```

FamiTone2 pulse-2 WAV output:

- `_bmad-output/audio-validation/famitone2-pulse2-tracks/synthetic_famitone2_pulse2.00.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `4895`
  - Measured dominant frequency: `522.713 Hz`
  - Bilan metadata records `first_note_channel: 1`,
    `expected_frequency_hz: 523.2511306011972`, and status `unverified`.

FamiTone2 pulse-2 MP3 command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_famitone2_pulse2.nes -o _bmad-output/audio-validation/famitone2-pulse2-mp3 --format mp3 --frames 90 --engine-mode in-process --force --bilan _bmad-output/audio-validation/famitone2-pulse2-mp3-bilan.json --color never
```

FamiTone2 pulse-2 MP3 output:

- `_bmad-output/audio-validation/famitone2-pulse2-mp3/synthetic_famitone2_pulse2.00.famitracker.mp3`
- Decoded WAV:
  `_bmad-output/audio-validation/famitone2-pulse2-mp3/synthetic_famitone2_pulse2.00.decoded.wav`
  - Decoded duration: `1.541224 s`
  - Decoded peak-to-peak amplitude: `21006`
  - Decoded dominant frequency: `522.710 Hz`

FamiTone2 triangle WAV command:

```bash
.venv/bin/python -m qlnes audio _bmad-output/audio-validation/synthetic_famitone2_triangle.nes -o _bmad-output/audio-validation/famitone2-triangle-tracks --format wav --frames 90 --engine-mode in-process --force --bilan _bmad-output/audio-validation/famitone2-triangle-bilan.json --color never
```

FamiTone2 triangle WAV output:

- `_bmad-output/audio-validation/famitone2-triangle-tracks/synthetic_famitone2_triangle.00.famitracker.wav`
  - Duration: `1.497528 s`
  - Peak-to-peak amplitude: `8371`
  - Measured dominant frequency: `522.713 Hz`
  - Bilan metadata records `first_note_channel: 2`,
    `expected_frequency_hz: 523.2511306011972`, status `unverified`, and
    loop provenance `{"reason": "unavailable", "status": "unverified"}`.

## Automated Test Evidence

Targeted fallback tests:

```bash
.venv/bin/python -m pytest tests/unit/test_audio_renderer.py::test_render_unrecognized_mapper0_uses_unknown_fallback tests/unit/test_audio_renderer.py::test_render_unsupported_mapper_still_raises_unsupported_mapper tests/integration/test_cli_audio.py::test_audio_unknown_mapper0_uses_unverified_fallback tests/integration/test_cli_audio.py::test_audio_unsupported_mapper_exits_100 -q
```

Result: `4 passed`

FamiTracker and renderer tests:

```bash
.venv/bin/python -m pytest tests/unit/test_audio_famitracker.py tests/unit/test_audio_renderer.py -q
```

Result: `47 passed`

Audio tranche:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `224 passed, 1 xpassed`

After adding per-song init/play metadata validation:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `226 passed, 1 xpassed`

After adding embedded NSF-header song enumeration and NSF-style `A` song
selector support:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `236 passed, 1 xpassed`

After adding `qlnes audio --bilan` provenance:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `238 passed, 1 xpassed`

After adding the conservative FamiTone2 music-data scanner:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_famitone2_data.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `240 passed, 1 xpassed`

After adding conservative static FamiTone2 rendering:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_famitone2_data.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `241 passed, 1 xpassed`

After adding row-by-row FamiTone2 stream rendering:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_famitone2_data.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `243 passed, 1 xpassed`

After adding conservative multi-channel FamiTone2 static rendering and
first tonal-channel metadata:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_famitone2_data.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `244 passed, 1 xpassed`

After adding explicit loop provenance and triangle-only FamiTone2 frequency
validation:

```bash
.venv/bin/python -m pytest tests/unit/test_apu_*.py tests/unit/test_audio_*.py tests/unit/test_famitone2_data.py tests/unit/test_in_process_runner.py tests/unit/test_renderer_engine_mode.py tests/integration/test_audio_pipeline.py tests/integration/test_cli_audio.py tests/integration/test_audio_perf.py tests/invariants/test_determinism.py -q
```

Result: `246 passed, 1 xpassed`

## Story Status

- Story 1.1: validated for mapper-0 in-process WAV on the synthetic A440
  fixture. The fixture proves audible output longer than one second and
  frequency alignment with the expected APU timer.
- Story 1.2: implemented for two recognized song-table sources:
  `QLNESFTMETA1` metadata and embedded NSF headers (`NESM\x1A`). Recognized
  fixtures can declare multiple referenced and unreferenced song entries with
  stable zero-padded filenames, per-song init/play addresses, and independently
  measurable audio outputs. Embedded NSF headers expose song count plus
  init/play addresses and use the NSF-style song selector in register A.
  Universal discovery of every arbitrary FamiTracker exporter layout remains a
  follow-up. A conservative FamiTone2 music-data scanner is now present and
  validated against Shiru's official demo ROM. qlnes can render each detected
  FamiTone2 table song through a conservative row-by-row static path tagged
  `unverified`; the path follows FamiTone2 note rows, empty-row repeats,
  speed tags, references, and loop tags across pulse 1, pulse 2, triangle, and
  noise register targets. Frequency metadata records the first tonal channel
  detected. This prevents silent misses while avoiding a false
  sample-equivalence claim.
- Story 1.3: implemented for metadata-derived loop boundaries. The WAV writer
  emits deterministic `smpl` chunks when loop metadata is available and omits
  them when unavailable. `bilan.json` records `loop_provenance` as
  `verified/engine` when boundaries exist and `unverified/unavailable` when no
  loop detection is available.
- Story 1.4: validated. MP3 is encoded from the same canonical PCM path and
  decoded audio preserves the expected A440 frequency. The optional audio
  bilan records encoder provenance (`lameenc`, VBR V2, 44.1 kHz) and PCM hash.
- Story 1.5: implemented for mapper-0 unknown-engine fallback. Unsupported
  non-fallback mappers still return `unsupported_mapper`. The fallback path
  writes `unknown` filenames, reports tier 2, emits mapper/SHA-256 plus
  `unverified` in stderr, and `--bilan` records unknown-engine tracks as
  `unverified` rather than `pass`.

## Completion Audit

Epic 1 addendum scope is complete as of 2026-07-22:

- Story 1.1: proved by WAV CLI renders, synthetic A440 frequency validation,
  APU unit coverage, pulse 2 and triangle-only FamiTone2 integration tests, and
  explicit DMC-stub behavior in unit tests.
- Story 1.2: proved by metadata, embedded NSF-header, and conservative
  FamiTone2 table enumeration tests. Outputs use zero-padded song indexes and
  bilans record engine, mapper, song index, ROM hash, and detection evidence.
- Story 1.3: proved by `smpl` loop chunk tests for metadata-derived loop
  boundaries and `loop_provenance` in `bilan.json` for unavailable loop
  detection.
- Story 1.4: proved by MP3 CLI renders, encoder provenance, canonical PCM
  hash recording, and version-bound MP3 determinism tests.
- Story 1.5: proved by mapper-0 unknown-engine CLI fallback, tier-2
  `unverified` artifacts, stderr mapper/SHA-256 evidence, and bilans that never
  record unknown-engine output as `pass`.

## Limitations

- The current validation proves audio behavior on a controlled legal fixture,
  not sample equivalence against FCEUX for a broad real-ROM corpus.
- Arbitrary commercial ROMs were not used.
- Additional exporter-specific FamiTracker pointer-table walkers are still
  needed to claim exhaustive extraction for unknown uninstrumented ROMs that
  contain neither `QLNESFTMETA1` metadata nor an embedded NSF header.
- FamiTone2 static rendering currently models row timing, pulse 1, pulse 2,
  triangle, and noise register targets, but not full instruments/envelopes or
  DPCM sample playback. Full FamiTone2 playback remains follow-up work before
  claiming tier-1 sample equivalence for arbitrary FamiTone2 ROMs.
- The current `--bilan` is a single-command audio provenance file. Corpus-level
  `qlnes audit` aggregation remains Epic 2.
