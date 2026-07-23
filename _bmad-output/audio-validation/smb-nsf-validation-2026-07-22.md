# Super Mario Bros. custom NSF validation - 2026-07-22

## Scope

Goal: generate usable NSF files for the local Super Mario Bros. ROM using the
custom audio-engine research note.

Input ROM:

- `roms/Super Mario Bros. (World).nes`

Generated code:

- `qlnes/smb_nsf.py`
- CLI: `python -m qlnes smb-nsf`

## Generated NSF files

Multi-track NSF:

- `_bmad-output/audio-validation/smb-nsf/super-mario-bros-custom.nsf`
- SHA-256: `5ba6d18051a2987793b9aaffaa9ed4cc1f49262ee2d57b0190d55d3a9b897f69`
- Header: `NESM\x1A`, version `1`, songs `14`, start song `1`
- Load: `$8000`
- Init: `$8000`
- Play: `$8050`
- Banks: `$00,$01,$02,$03,$04,$05,$06,$07`
- Play stub bytes: `20 d0 f2 60` (`JSR $F2D0; RTS`)

Split NSF files:

- `_bmad-output/audio-validation/smb-nsf/split/01-ground.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/02-water.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/03-underground.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/04-castle.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/05-cloud.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/06-pipe-intro.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/07-star-power.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/08-death.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/09-game-over.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/10-victory.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/11-end-of-castle.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/12-end-of-level.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/13-time-running-out.nsf`
- `_bmad-output/audio-validation/smb-nsf/split/14-silence.nsf`

Each split NSF has `songs=1`, `load=$8000`, `init=$8000`, `play=$8050`,
and banks `$00..$07`.

## Commands

Generate:

```bash
.venv/bin/python -m qlnes smb-nsf "roms/Super Mario Bros. (World).nes" \
  -o _bmad-output/audio-validation/smb-nsf/super-mario-bros-custom.nsf \
  --split-dir _bmad-output/audio-validation/smb-nsf/split
```

Unit tests:

```bash
.venv/bin/python -m pytest tests/unit/test_smb_nsf.py -q
```

Result: `4 passed in 0.13s`.

Decode smoke test:

```bash
python3 - <<'PY'
from pathlib import Path
from qlnes.gme_play import render_nsf
base=Path('_bmad-output/audio-validation/smb-nsf')
out=base/'split-render-smoke'
for nsf in sorted((base/'split').glob('*.nsf')):
    render_nsf(nsf, out/(nsf.stem+'.wav'), track=0, duration_s=3.0, fade_s=0.5)
PY
```

## Decode measurements

Measured from 3 seconds of libgme-rendered WAV per split NSF:

| Track | Duration | RMS | Max | Status |
|---|---:|---:|---:|---|
| 01-ground | 3.000s | 2812 | 15265 | audible |
| 02-water | 3.000s | 3123 | 13187 | audible |
| 03-underground | 3.000s | 2814 | 11328 | audible |
| 04-castle | 3.000s | 4341 | 16561 | audible |
| 05-cloud | 3.000s | 3213 | 18826 | audible |
| 06-pipe-intro | 3.000s | 2489 | 14486 | audible |
| 07-star-power | 3.000s | 3222 | 19138 | audible |
| 08-death | 3.000s | 3982 | 23148 | audible |
| 09-game-over | 3.000s | 3744 | 11975 | audible |
| 10-victory | 3.000s | 4056 | 11530 | audible |
| 11-end-of-castle | 3.000s | 5051 | 20394 | audible |
| 12-end-of-level | 3.000s | 3690 | 11312 | audible |
| 13-time-running-out | 3.000s | 3736 | 14739 | audible |
| 14-silence | 3.000s | 0 | 0 | intentional silence track |

## Implementation Notes

The NSF is banked because the original 32 KiB PRG has no large safe code cave.
The generated NSF maps a new wrapper bank at `$8000` and preserves original PRG
banks 1..7 at `$9000..$FFFF`, keeping the original sound engine and music data
available at `$F000..$FFFF`.

`INIT(A=song-1)` clears RAM, sets `OperMode=$01`, then writes either:

- `$FB = area music bit`, or
- `$FC = event music bit`.

`PLAY()` calls the original SMB sound engine:

```asm
JSR $F2D0
RTS
```

## Limitations

- This is a local/private commercial-ROM-derived artifact. Do not distribute the
  ROM or generated NSF files unless rights are cleared.
- Validation proves NSF structure and libgme decodability, plus non-silence for
  13 musical tracks. It is not yet a full PCM equivalence comparison against a
  FCEUX gameplay reference.
- Track 14 is the engine's `Silence` event and is intentionally silent.

## MP3 listening conversion - 2026-07-23

Status: superseded by `mp3-no-repeat`. The earlier fixed 180 second listening
MP3s were removed because they intentionally contained loop repetitions.

## MP3 no-repeat conversion - 2026-07-23

Output folder:

- `_bmad-output/audio-validation/smb-nsf/mp3-no-repeat/`

Conversion method:

1. Parse the original SMB PRG music headers and square 2 streams.
2. Stop each track at the first square 2 `0x00` end marker.
3. For ground music, sum the documented ground header sequence from `$11`
   through `$31`, stopping before the engine loops back at `$32`.
4. For `time-running-out`, apply the engine's `NoteLengthTblAdder=$08`.
5. Render each split NSF through `qlnes.gme_play.render_nsf` with the calculated
   no-repeat duration and a 2 second fade that does not extend beyond that
   duration.
6. Encode each temporary WAV with `ffmpeg` / `libmp3lame` at `192k`, then remove
   temporary WAV files.

MP3 files:

| Track | MP3 | Duration | Source RMS | Source Max |
|---|---|---:|---:|---:|
| 01-ground | `01-ground.mp3` | 88.685714s | 2886 | 17903 |
| 02-water | `02-water.mp3` | 25.600000s | 3211 | 14107 |
| 03-underground | `03-underground.mp3` | 12.617143s | 2475 | 10975 |
| 04-castle | `04-castle.mp3` | 8.019592s | 4238 | 16327 |
| 05-cloud | `05-cloud.mp3` | 3.239184s | 3148 | 18320 |
| 06-pipe-intro | `06-pipe-intro.mp3` | 2.429388s | 2700 | 14218 |
| 07-star-power | `07-star-power.mp3` | 3.239184s | 3156 | 18634 |
| 08-death | `08-death.mp3` | 3.030204s | 3867 | 22562 |
| 09-game-over | `09-game-over.mp3` | 3.631020s | 3663 | 11645 |
| 10-victory | `10-victory.mp3` | 6.426122s | 4035 | 11476 |
| 11-end-of-castle | `11-end-of-castle.mp3` | 6.086531s | 4829 | 19844 |
| 12-end-of-level | `12-end-of-level.mp3` | 5.433469s | 3681 | 11481 |
| 13-time-running-out | `13-time-running-out.mp3` | 2.847347s | 3740 | 14321 |
| 14-silence | `14-silence.mp3` | 0.078367s | 0 | 0 |

Interpretation:

- Tracks 1-13 contain measurable audio over their no-repeat render windows.
- Track 14 remains silent by design because it maps to SMB's `Silence` event.
- These MP3s are listening artifacts, not canonical verification artifacts.
  The cut points are now derived from SMB music stream terminators, not fixed
  wall-clock guesses.
