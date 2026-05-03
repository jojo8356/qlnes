---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
completedAt: '2026-05-03'
lastAmended: '2026-05-03'
amendmentLog:
  - date: '2026-05-03'
    summary: 'Post-readiness research integrated: tiered audio fidelity (sample-accurate for recognized engines, frame-accurate for unknown), MP3 byte-equivalence bounded by encoder-library version with PCM as canonical hash target, bilan.json coverage axis extended to (mapper, audio engine) for audio artifacts.'
releaseMode: phased
inputDocuments:
  - _bmad-output/project-context.md
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 0
  projectDocs: 1
classification:
  projectType: cli_tool+developer_tool
  domain: general
  complexity: high
  projectContext: brownfield
workflowType: 'prd'
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
---

# Product Requirements Document - qlnes

**Author:** Johan
**Date:** 2026-05-03

## Executive Summary

`qlnes` is a Python CLI and developer toolkit that makes any Nintendo Entertainment System ROM fully transparent and exploitable: code, music, assets, and gameplay data are extractable as clean artifacts in the format the user chooses. The product targets three audiences who today rely on incomplete or fragmented tooling: ROM hackers porting classic titles to modern platforms or producing HD remasters; researchers, speedrunners, and completionists who need exact game mechanics (drop rates, RNG behavior, AI logic) rather than community approximations; and modern developers studying NES-era optimization techniques (data compression, code density, banking, four-channel audio) as a pedagogical reference.

The problem this solves is concrete. Knowledge about NES games circulates as myths and approximations even though every answer is in the ROM bytes — the bottleneck is tooling, not data. Existing tools each cover a slice (Mesen for debugging, da65 for static disassembly, NSF rippers for music, asset extractors for sprites), but none is complete across the full corpus or across the full set of artifacts a user might want.

### What Makes This Special

**Completeness over invention.** The strategic position is not to invent novel disassembly or audio extraction techniques but to be the single tool that delivers every NES ROM artifact through one interface. Where another open-source project covers a slice well (e.g. universal music handling), `qlnes` integrates the relevant code rather than reimplementing it.

**Universality across the mapper space.** The end-state target is every iNES mapper, not just mapper 0 (currently the only mapper supported by the dynamic `cynes` runner) or the recently added mapper 66. The multi-bank pipeline and sound-engine extractor are first steps toward that target.

**Direct ASM → audio pipeline for fidelity.** Rather than rely on the ASM → NSF → MP3 chain (which loses information at the NSF rip stage), `qlnes` renders audio directly from disassembled audio code. The output matches what runs inside the ROM and serves as the reference signal for audio testing.

**Need → format → artifact, no ceremony.** Each user need maps to one command and one chosen output format: music as `NSF`, `MP3`, or `WAV`; code as annotated assembly; sprites as PNG; round-trip verification as recompiled bytes. The tool delivers the artifact and exits — no gating UX layer.

## Project Classification

- **Project Type:** CLI tool. Invocation: `python -m qlnes <command>`. The CLI surface — commands, flags, exit codes, structured `stderr` payloads — is the project's only public contract; internal Python modules are not a public surface (rationale in *CLI Tool — Specific Requirements*).
- **Domain:** General — retro-engineering and NES ROM tooling. No regulatory exposure; closest neighbor is the scientific-computing domain due to reproducibility expectations (byte-identical round trips).
- **Complexity:** High. Low regulatory complexity, but technically deep: 6502 instruction semantics, iNES header and mapper semantics across the full mapper space, PPU/APU register-level reproduction, emulator-driven discovery, and cycle-accurate audio synthesis from source.
- **Project Context:** Brownfield. An analysis pipeline already exists (static disassembly, dataflow detection, asset extraction, optional dynamic discovery via `cynes`, optional round-trip verify via `py65`); this PRD scopes the next wave of work — completing NSF support, adding the direct ASM → MP3 pipeline, and broadening mapper coverage toward the universality goal.

## Success Criteria

### User Success

For each user need, `qlnes` produces the requested artifact in the requested format through a single command, with no manual post-processing required. Specifically:

- A user requesting music receives an `NSF`, `MP3`, or `WAV` file (their choice) that plays correctly in any standard player for that format.
- A user requesting code receives annotated 6502 assembly that reassembles to a byte-identical ROM via `py65`.
- A user requesting assets receives PNG sprite sheets that round-trip back to byte-identical CHR-ROM.
- A user requesting gameplay data (drop tables, RNG, AI scripts) receives a structured artifact (JSON or markdown table) extracted directly from ROM bytes.
- The generated `STACK.md` gives a non-expert reader a complete technical picture of an unknown ROM in under ten minutes of reading.

### Technical Success — Equivalence Invariants

`qlnes` is judged on **strict equivalence**, not approximation. Each artifact must satisfy a defined invariant against the source ROM. No fuzzy thresholds, no "good enough."

| Artifact | Invariant | Verification method |
|---|---|---|
| `NSF` | The generated NSF, played in the reference NSF player, produces a PCM stream sample-by-sample identical to the audio captured from the reference NES emulator running the original ROM, at a defined sample rate and channel mix. | Automated PCM hash diff over the test corpus. |
| `MP3` / `WAV` (direct ASM → audio path) | The PCM stream is sample-by-sample identical to FCEUX **for ROMs whose audio engine has a recognized handler** (tier 1). For ROMs whose audio engine is not recognized, the output is **frame-accurate** (≈ 16.6 ms NTSC) and is tagged `unverified` in `bilan.json`, never `pass`. `MP3` is the lossy encoding of the canonical PCM stream; PCM is the equivalence-checked artifact. | Automated PCM hash diff over the test corpus. |
| Annotated ASM | The reassembled ROM (via `py65`) is byte-identical to the input `.nes` file. | Existing `--verify` round-trip hash check, applied per supported mapper. |
| `CHR` / `PNG` | Round-trip `CHR → PNG → CHR` is byte-identical for the original CHR-ROM bank set. | SHA-256 hash compare. |
| Gameplay data | Structured outputs (drop tables, RNG, AI scripts) are extracted from disassembled bytes and refer back to source addresses; values must agree with the original ROM's runtime behavior on a fixed input sequence in the reference emulator. | Replay-and-compare against captured runtime traces. |

**Reference emulator:** FCEUX. Chosen for pragmatic reasons (already in the project owner's environment, well-documented audio capture path). All PCM equivalence checks are anchored to FCEUX's audio output. The reference choice can be revisited later if a stronger oracle is needed, but FCEUX is the locked default for this PRD.

**Tiered audio fidelity (the "recognized engine" model).** The sample-by-sample equivalence promise applies only to ROMs whose **audio engine** (the in-ROM driver that walks the song-pointer table — Capcom-Sakaguchi, Konami-Maezawa, FamiTracker, Sunsoft, etc.) has a recognized handler in `qlnes`. Recognition is necessary because per-engine bytecode and loop-opcode semantics differ — there is no published universal NES-audio detector. Coverage extends one engine at a time, gated by the engine's full equivalence-invariant set passing on its corpus subset. ROMs whose engine is *not* recognized fall back to a frame-accurate (≈ 16.6 ms NTSC) generic path that emulates the ROM and fingerprints APU register writes; outputs from this path are tagged `unverified` in `bilan.json` and never reported as `pass`. The product-level mapper-coverage promise is therefore an *(iNES mapper, audio engine)* matrix for audio artifacts, not just a mapper count.

**Test corpus:** A versioned set of `.nes` ROMs covering each supported mapper. Every release of `qlnes` runs every invariant against every corpus ROM. A release ships for a mapper only if every invariant passes for every corpus ROM of that mapper.

### Measurable Outcomes

- **Equivalence pass rate:** 100% (not 99.9%, not 99%) on every invariant for every ROM in the supported portion of the corpus. Anything below 100% blocks release for that mapper.
- **Coverage progress signal:** for non-audio artifacts (`analyze`, `verify`), the public progress signal is the number of iNES mappers for which the full invariant set passes. For audio artifacts (`audio`, `nsf`), the signal is the number of *(mapper, audio engine)* pairs for which the full invariant set passes — the (mapper, engine) matrix is published via `bilan.json` and `qlnes coverage`.
- **Audio fidelity:** Bit-identical PCM output vs reference emulator on the audio test corpus, for both the `NSF` path and the direct ASM → audio path.
- **Round-trip fidelity:** Byte-identical reassembled ROM for every supported mapper.

## Product Scope

This PRD scopes the **music** workstream of `qlnes`. Other artifacts — code round-trip, asset extraction, gameplay data — exist in the codebase already or are explicitly deferred to later workstreams. The full phased breakdown (MVP, Growth, Vision) is defined in [Project Scoping & Phased Development](#project-scoping--phased-development) below; the rest of this document refers back to those tiers via the `[MVP]` / `[Growth]` / `[Vision]` tags on functional requirements and capabilities.

## User Journeys

### Journey 1 — Marco, the porter (primary user, happy path)

**Persona.** Marco is a hobbyist developer porting a classic NES JRPG to PC. He has the source-level engine reimplemented in Rust, but for the soundtrack he has been using YouTube rips: low bitrate, missing tracks, broken loops. He needs perfect-fidelity audio that he can drop into his game's audio engine, with proper loop points.

**Opening scene.** Marco stares at a list of 23 OST tracks in his project and three half-usable MP3s. He has tried `nsf2wav` chains on his ROM and hit a mapper-66 issue.

**Rising action.** He installs `qlnes`, runs:

```
python -m qlnes audio rom.nes --format wav --output tracks/
```

The tool detects the audio engine, walks the song table, and emits one loop-aware WAV per track — sample-identical to what runs inside the ROM.

**Climax.** Marco diffs the PCM of `track-04.wav` against an FCEUX recording. Hash matches. He drops the WAVs into his Rust audio system; the tracks play with loops correct on the first try.

**Resolution.** Marco's port has the OST done in one afternoon instead of three weekends of Audacity surgery. He stops thinking about audio.

**Capabilities revealed:**
- Per-track audio extraction with correct loop boundaries.
- Automatic mapper detection.
- Multiple output formats (`WAV`, `MP3`, `NSF`) selectable per invocation.
- Per-ROM corpus of expected outputs to validate fidelity.

### Journey 2 — Sara, the content creator (primary user, NSF path)

**Persona.** Sara is a speedrunner producing a video essay about an obscure NES platformer's OST. She needs the complete soundtrack as `NSF` (for use in chiptune players on stream) and `WAV` (for the video edit).

**Opening scene.** Sara has scoured `nesmusic.org` for the NSF; the available rip is missing two unused tracks (composer demos that never made the final cut). Her video specifically wants those.

**Rising action.** She runs:

```
python -m qlnes nsf rom.nes --output ost.nsf
python -m qlnes audio rom.nes --format wav --output tracks/
```

`qlnes` walks every entry in the song-pointer table — including the unreferenced ones — and emits a complete NSF plus per-track WAVs.

**Climax.** She loads `ost.nsf` in her NSF player and finds the two missing demo tracks. The WAV exports drop into her video editor at studio fidelity.

**Resolution.** Her video credits the qlnes extraction. She no longer tells viewers "the original soundtrack is unavailable in good quality."

**Capabilities revealed:**
- Exhaustive song-table extraction (referenced and unreferenced).
- Valid `NSF` output that loads in standard chiptune players.
- Same source ROM, multiple format outputs in the same session.

### Journey 3 — Lin, the pipeline integrator (CLI consumer)

**Persona.** Lin is the author of an HD-2D remastering tool for NES games. Her pipeline takes a ROM and produces a Unity project skeleton with sprites, levels, and audio. The audio stage has been her weakest link — glued together from three different tools, breaks on every mapper she hadn't tested.

**Opening scene.** Lin's pipeline crashes on a user-submitted MMC3 ROM. Audio extraction segfaults inside her vendored copy of an old NSF tool.

**Rising action.** She replaces her audio stage with a `subprocess` call to the `qlnes` CLI:

```
qlnes audio rom.nes --format wav --output tracks/
```

Her pipeline reads the exit code, scans `stderr` for the structured error prefix on failure, and consumes the WAV files from `tracks/` on success.

**Climax.** Her pipeline now uses one external dependency for audio, with one predictable failure model (clear `qlnes`-prefixed `stderr` line plus non-zero exit when an unsupported mapper appears, no segfault). Universality of `qlnes` across mappers means her tool inherits the same coverage automatically as `qlnes` lands new mapper support.

**Resolution.** Lin contributes back a corpus of MMC3 test ROMs and a fixture for one bug she hits. Her own tool ships with `qlnes` listed in its install instructions, invoked as a CLI — never imported.

**Capabilities revealed:**
- Stable CLI surface: stable command names, stable flag semantics, stable exit-code contract, stable structured error prefixes on `stderr`.
- Predictable failure mode for unsupported-mapper or malformed-ROM cases (no segfaults, no silent fallbacks).
- Output written to a user-specified directory in deterministic file names so a parent pipeline can pick artifacts up by convention.

> **Note on scope.** `qlnes` is intentionally CLI-only. There is no public Python API. Internal modules may be refactored at any time. Consumers integrate via subprocess. A library-style API may exist in a future separate offering, but is explicitly out of scope for this PRD.

### Journey 4 — Marco again, edge case (unsupported mapper)

**Persona.** Marco from Journey 1, on a different project — porting a mapper-5 (MMC5) game whose audio uses MMC5 expansion sound channels.

**Opening scene.** He runs his familiar command on the new ROM:

```
python -m qlnes audio rom.nes --format wav --output tracks/
```

**Rising action.** `qlnes` detects mapper 5, recognizes the MMC5 audio expansion, and prints a single clear message:

```
qlnes: error: mapper 5 (MMC5) audio extraction is not yet covered.
       Static disassembly and CHR extraction will still work.
       Track progress: <link to mapper-coverage page in the project README>.
```

The exit code is non-zero. Nothing partial is written.

**Climax.** Marco does not waste an hour debugging a corrupted output. He files an issue with the ROM's hash and moves on.

**Resolution.** He uses `qlnes` for the static disassembly and the CHR extraction, and contributes the ROM hash to the future MMC5 corpus when that workstream lands.

**Capabilities revealed:**
- Per-mapper, per-artifact coverage matrix exposed to the user.
- Clear, actionable failure mode for unsupported configurations.
- Partial-success policy: never emit corrupted output; fail loudly.

### Journey Requirements Summary

The four journeys above reveal the following capability areas:

- **Audio extraction commands** (`audio`, `nsf`) with per-track output and user-selectable format (`WAV`, `MP3`, `NSF`).
- **Loop-aware WAV/MP3 emission** so output is usable in audio engines without manual editing.
- **Exhaustive song-table walking**, including unreferenced songs.
- **Stable CLI surface** — command names, flag semantics, exit codes, and structured `stderr` error prefixes are the public contract. The Python module layout is *not* a public surface.
- **Per-mapper coverage matrix** surfaced to the user, with a clear, non-zero-exit error model for unsupported configurations.
- **Partial-success policy:** corrupted output is never written; failures are loud and specific.
- **Reference-emulator-anchored equivalence checks** (FCEUX) runnable by both developers (CI) and curious users (`qlnes verify --audio rom.nes`).

## CLI Tool — Specific Requirements

### Project-Type Overview

`qlnes` is a Typer-based Python CLI built on the run-as-module pattern (`python -m qlnes <command> …`). Each invocation is fire-and-forget: it takes a ROM, produces one artifact in one chosen format, and exits. No interactive mode in MVP. No public Python API. The CLI surface — commands, flags, exit codes, structured `stderr` error prefixes — is the project's only stable public contract.

### Command Structure

Existing commands (already in `qlnes/cli.py`):

- `analyze` — produce `STACK.md`, optionally annotated ASM (`--asm`), optionally extract assets (`--assets`), optionally verify round-trip (`--verify`).
- `recompile` — reassemble annotated ASM back to a `.nes` via `py65`.
- `verify` — run the round-trip equivalence check on a ROM.
- `audio` — render audio (in MVP: `WAV` / `MP3` / `NSF` per format flag).
- `nsf` — emit a standalone `NSF` file.

Music-MVP additions:

- `audio --format {wav,mp3,nsf}` with deterministic per-track output filenames driven by the song-table walk.
- `audio --output <dir>` for the per-track output directory.
- `verify --audio` to run the audio equivalence invariant against the FCEUX reference.
- `audit` — run every equivalence invariant against the entire test corpus and write the result to `bilan.json` (the project's audit report). Long-running. Used in CI and on demand.
- `coverage` — read `bilan.json` and print the per-mapper, per-artifact support matrix (human-readable table by default; `--format json` for scripts). If `bilan.json` is absent or malformed, `coverage` runs `audit` automatically before printing. `--refresh` forces a re-audit.

### Output Formats

The output-format contract is the user's primary customization point. Each command accepts an explicit `--format` flag. Defaults are conservative (`wav` for audio because lossless; `STACK.md` for `analyze` because human-readable). The authoritative per-artifact format and equivalence reference is the table in the Success Criteria section above.

### Configuration — Layered Model

`qlnes` uses a layered configuration model. Each layer overrides the previous one:

1. **Built-in defaults** — sensible defaults baked into the code (e.g. `format=wav`, `assets=auto`).
2. **Project config file** — `qlnes.toml` at the working directory or next to the ROM. Typed values, per-command sections.
3. **Environment variables** — `QLNES_*` prefix, for CI / cluster overrides. Every env var must be expressible via a flag too.
4. **CLI flags** — always the final say. Anything on the command line wins.

Example `qlnes.toml`:

```toml
[default]
output_dir = "./out"
quiet = false
bilan_file = "./bilan.json"

[audio]
format = "wav"
reference_emulator = "fceux"

[verify]
strict = true
```

Honoring the `qlnes.toml` defaults from `audio`, `verify`, `audit`, and `coverage` is part of the music-MVP scope.

### The `bilan.json` Audit Artifact

`bilan.json` is the persisted, machine-generated state of the equivalence test corpus — the single source of truth for the coverage matrix. Hand-maintained coverage tables are not allowed; the matrix is always read from this file.

**Default location:** repo root (`./bilan.json`). Overridable via `--bilan <path>` or `[default] bilan_file = "..."` in `qlnes.toml`. The file is meant to be committed, so it acts as a public scoreboard in the repo.

**Schema (versioned):**

```json
{
  "generated_at": "2026-05-03T14:30:00Z",
  "qlnes_version": "0.x.y",
  "reference_emulator": "fceux",
  "corpus": {
    "rom_count": 42,
    "mapper_breakdown": {"0": 15, "66": 8, "1": 12, "2": 4, "4": 3}
  },
  "results": {
    "0": {
      "analyze": {"status": "pass", "rom_count": 15, "fail_count": 0},
      "nsf":     {"status": "pass", "rom_count": 15, "fail_count": 0},
      "audio":   {"status": "pass", "rom_count": 15, "fail_count": 0},
      "verify":  {"status": "pass", "rom_count": 15, "fail_count": 0}
    },
    "1": {
      "analyze": {"status": "pass", "rom_count": 12, "fail_count": 0},
      "verify":  {"status": "pass", "rom_count": 12, "fail_count": 0},
      "audio": {
        "status": "partial",
        "rom_count": 12,
        "fail_count": 4,
        "engines": {
          "famitracker":  {"status": "pass",       "rom_count": 8, "fail_count": 0},
          "unknown":      {"status": "unverified", "rom_count": 4, "fail_count": 4}
        }
      },
      "nsf": {
        "status": "partial",
        "rom_count": 12,
        "fail_count": 4,
        "engines": {
          "famitracker": {"status": "pass",       "rom_count": 8, "fail_count": 0, "format": "nsf2+nsfe"},
          "unknown":     {"status": "unverified", "rom_count": 4, "fail_count": 4}
        }
      }
    }
  }
}
```

**Freshness guarantees:**

- If `bilan.json` is absent or fails schema validation, `qlnes coverage` runs `qlnes audit` before printing.
- If `bilan.json`'s `generated_at` is older than the most recent mtime in `qlnes/`, `qlnes coverage` warns that the bilan is likely stale and suggests `--refresh`.
- `qlnes audit` refuses to write `bilan.json` if any ROM declared in the test corpus is missing (exits `102`).

### Scripting Support — Maximum-Safety Contract

`qlnes` is designed to be embedded in pipelines (see Lin's journey). The contract is intentionally strict and stable.

**Exit codes** — disjoint, semver-disciplined, never reused. Aligned to `sysexits.h` where possible.

| Code | Meaning |
|---|---|
| `0` | Full success: every invariant passed, the artifact was written. |
| `2` | CLI usage error (bad flag, missing arg) — `bash` convention. |
| `64` | `EX_USAGE` — invalid CLI invocation (`sysexits.h`). |
| `65` | `EX_DATAERR` — input ROM malformed or not iNES. |
| `66` | `EX_NOINPUT` — input file missing or unreadable. |
| `70` | `EX_SOFTWARE` — internal error / bug; should never fire on normal input. |
| `73` | `EX_CANTCREAT` — output path not writable. |
| `74` | `EX_IOERR` — I/O error during read/write. |
| `100` | Mapper not supported for the requested artifact. |
| `101` | Equivalence check failed (audio or round-trip not bit-identical). |
| `102` | FCEUX reference output missing for one or more ROMs in the test corpus. |
| `130` | Killed by SIGINT (Ctrl-C) — standard convention. |

**Robustness commitments:**

- **Atomic writes.** No output file is ever left half-written. Every output is written to a sibling `.tmp` and `rename(2)`d on completion. If `qlnes` crashes, the prior file (if any) is intact.
- **Pre-flight validation.** Before writing a single byte, `qlnes` validates everything it can — iNES header, mapper supported for the requested artifact, output directory writable, FCEUX corpus references available. If a fatal failure is predictable, `qlnes` fails before writing.
- **`--strict` flag.** Any warning becomes fatal. CI uses `--strict`.
- **Refuse-to-overwrite by default.** If the output file already exists, `qlnes` errors with code `73` unless `--force` is passed.
- **Structured JSON payload on `stderr`** for every error: after the `qlnes: error: <reason>` line, a single-line JSON object such as `{"code": 100, "class": "unsupported_mapper", "mapper": 5, "rom_sha256": "…"}`. Scripts depend on the JSON, not text parsing.

**Other scripting conventions:**

- **`stderr`.** All errors prefixed with `qlnes: error:` followed by an explicit reason. No stack traces in `stderr` by default; `--debug` exposes them.
- **`stdout`.** Machine-readable when relevant (e.g. `coverage` defaults to an aligned table; `--format json` for scripts).
- **Deterministic output filenames.** Consumers can predict file names from the input ROM and the command flags. No timestamps in default filenames.
- **Non-TTY mode.** No prompts, no progress bars, purely batch behavior when piped.

### Shell Completion

Shell completion is enabled (Typer's built-in, via `--install-completion`). Currently disabled in `qlnes/cli.py` (`add_completion=False`); flipping that flag is in MVP scope. Completion supports bash, zsh, fish, and PowerShell.

### Implementation Considerations

- **Distribution.** Out of MVP scope. The MVP ships as clone-and-`requirements.txt`. A `pyproject.toml` and PyPI publication are deferred to a post-MVP / pre-v1 milestone, then production-released at v1. The CLI design must not preclude pip-installability — entry points must work cleanly when this work lands.
- **No interactive REPL in MVP.** A `qlnes shell <rom.nes>` interactive mode is explicitly deferred. May ship at v1 as a bonus.
- **No public Python API.** Internal modules are not part of the public surface. The CLI is. Any future library-style API is reserved for a separate paid offering and is out of scope for this PRD.
- **Skip sections per project-type guidance.** `visual_design`, `ux_principles`, `touch_interactions`, `store_compliance` are intentionally not part of this product (CLI tool, no GUI, no app store).

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP approach.** Problem-solving MVP, narrowed to a single workstream: **music**. The MVP proves that `qlnes` can deliver bit-identical audio artifacts in multiple formats with strict equivalence guarantees. Other artifacts (code, assets, gameplay data) are intentionally out of MVP scope because they are either already partially shipped or because they would dilute the MVP's core proof point: that `qlnes` ships *complete and correct* output for one artifact class before extending to others.

**Resource assumption.** Solo developer (Johan), no funded team. The phasing is built around what one person can ship without compromising the strict-equivalence quality bar.

### MVP Feature Set (Phase 1 — Music Workstream)

**Core user journeys supported:**

- Marco (the porter) — `qlnes audio rom.nes --format wav` produces loop-aware, sample-identical WAV per track.
- Sara (the content creator) — `qlnes nsf rom.nes` produces a complete, player-loadable NSF; `qlnes audio --format wav` produces per-track WAVs.
- Lin (the pipeline integrator) — same commands invoked via subprocess, with stable exit codes and structured JSON `stderr` payloads.
- Marco again (edge case) — unsupported mapper for audio is reported cleanly with exit code `100` and no partial output.

**Must-have capabilities (in scope for MVP):**

- `audio --format {wav,mp3,nsf}` with deterministic per-track filenames.
- `nsf` standalone NSF emission.
- Direct ASM → audio pipeline (no NSF intermediate) with PCM equivalence vs FCEUX.
- Exhaustive song-table walk (referenced and unreferenced songs).
- `verify --audio` runnable per-ROM.
- `audit` runs the full equivalence test corpus and writes `bilan.json`.
- `coverage` reads `bilan.json` and prints the per-mapper, per-artifact matrix; auto-runs `audit` if `bilan.json` is missing.
- Layered configuration (built-in defaults → `qlnes.toml` → `QLNES_*` env vars → CLI flags).
- Maximum-safety scripting contract: sysexits-aligned exit codes, atomic writes, pre-flight validation, `--strict`, refuse-overwrite-without-`--force`, JSON stderr payloads.
- Shell completion enabled (Typer's built-in).
- Test corpus versioned with the code; FCEUX-anchored reference outputs available for every corpus ROM.

### Post-MVP Features (Phase 2 — Growth, pre-v1)

- **Universal mapper coverage for the audio workstream** — extending the supported-mapper set toward every iNES mapper one mapper at a time, each added only when its full equivalence-invariant set passes against the corpus.
- **Selective integration of third-party open-source audio code** where it accelerates universality (rather than reimplementing).
- **Extension of the equivalence-invariant framework** to other artifact types (code round-trip, assets, gameplay data) as those workstreams come online — applying the same 100% bit-identical / sample-identical bar.
- **Distribution.** Add `pyproject.toml` and an entry-point. Test `pip install qlnes` privately before the v1 release. PyPI publication ships at v1 cut.

### Vision (Phase 3 — v1 and beyond)

- **"ROM → portable project" pipeline** producing bundles ready to port to modern consoles or remaster in HD, derived from the full set of `qlnes` artifacts.
- **Auto-generated game-mechanics documentation** (drop tables, RNG behavior, AI scripts) for researchers, speedrunners, and completionists.
- **Pedagogical capture of NES-era optimization techniques** as a learning resource for modern developers.
- **Interactive REPL** (`qlnes shell <rom.nes>`) as a v1 bonus — explore a ROM, list subroutines, audition tracks interactively.

### Risk Mitigation Strategy

**Technical risks.**

- *FCEUX as the oracle could disagree with Mesen or hardware on edge cases.* Mitigation: lock FCEUX as the reference in this PRD; allow the reference to be re-anchored later if a stronger oracle is needed, but never silently. Re-anchoring is itself a versioned event recorded in `bilan.json`.
- *Cycle-accurate APU emulation from disassembled ASM is hard, especially for less-mainstream sound engines.* Mitigation: small initial test corpus (mapper 0, mapper 66), expand mapper-by-mapper. Each new mapper lands only when 100% equivalence is achieved on its corpus subset — never partially.
- *`bilan.json` drift relative to the code.* Mitigation: `coverage` warns if `bilan.json`'s `generated_at` is older than any source file in `qlnes/`; CI re-runs `qlnes audit` on every change.

**Adoption risks.**

- *Niche audience: small NES ROM-hacking community.* Mitigation: the product is a personal/community utility, not a market product. The MVP's success criteria are technical (equivalence pass rate), not adoption metrics. Adoption-level concerns are explicitly out of scope.

**Resource risks.**

- *Solo developer; scope creep would block delivery.* Mitigation: the MVP is intentionally narrowed to a single artifact class (music). Other artifact types are deferred to Growth, not parallelized. The phasing enforces focus.
- *FCEUX corpus generation requires manual setup.* Mitigation: reference captures for each corpus ROM are versioned alongside the test corpus, generated once, and checked in. `qlnes audit` exits `102` if a ROM's reference is missing rather than silently passing.

## Functional Requirements

The functional requirements below are the capability contract for the product across MVP, Growth, and Vision phases. Each FR is tagged with its scope tier:

- `[Existing]` — already shipped before this PRD; documented here for completeness, no change in this PRD's MVP.
- `[MVP]` — new capability landing in the music-workstream MVP defined by this PRD.
- `[Growth]` — deferred to Phase 2 (post-MVP, pre-v1).
- `[Vision]` — deferred to Phase 3 (v1+).

Capabilities not listed below are not part of the product. If something is needed and not here, this PRD must be updated before it is built.

### 1. ROM Ingestion & Static Analysis

- **FR1.** `[Existing]` User can load an iNES `.nes` file and have its header validated (magic, mapper number, PRG/CHR bank counts, mirroring, battery, trainer flags).
- **FR2.** `[Existing]` User can produce `STACK.md`, a human-readable technical summary of an unknown ROM (header, hardware-register usage, dataflow patterns, named subroutines, characterization).
- **FR3.** `[Existing]` User can produce annotated 6502 disassembly of the full PRG-ROM with named labels for detected subroutines (e.g. `ppu_load`, `play_pulse`, `update_scroll`).
- **FR4.** `[Existing]` User can run dynamic discovery via `cynes` to expand static-only coverage (currently mapper-0 only; broadens with Growth).

### 2. Audio Extraction (MVP focus)

- **FR5.** `[MVP]` User can extract the soundtrack of a supported-mapper ROM as a single `NSF` file via `qlnes nsf <rom>`.
- **FR6.** `[MVP]` User can extract the soundtrack as per-track `WAV` files via `qlnes audio <rom> --format wav`, with loop boundaries preserved per track.
- **FR7.** `[MVP]` User can extract the soundtrack as per-track `MP3` files via `qlnes audio <rom> --format mp3`, encoded from the same PCM source as the WAV path.
- **FR8.** `[MVP]` User can choose between `NSF`, `WAV`, and `MP3` output via the `--format` flag (one format per invocation).
- **FR9.** `[MVP]` User can specify a per-track output directory via `--output <dir>`; output filenames are deterministic and predictable from the input ROM's hash and the song-table index.
- **FR10.** `[MVP]` `qlnes` walks the song-pointer table exhaustively, including unreferenced entries (composer demos, unused music) — these are included in the output unless explicitly filtered.
- **FR11.** `[MVP]` The audio rendering path for `WAV`/`MP3` is direct ASM → PCM, with no intermediate `NSF` rip. The PCM output is **sample-by-sample identical to FCEUX for ROMs whose audio engine has a recognized handler** (tier 1, the `qlnes` correctness commitment). For ROMs whose audio engine is not recognized, the output is **frame-accurate** (≈ 16.6 ms NTSC) and is reported as `unverified` in `bilan.json`, never as `pass`. PCM-level signal heuristics are never used as the primary rendering path.
- **FR12.** `[Growth]` User can extract audio from any iNES mapper covered by Growth-phase work; coverage extends one mapper at a time, gated by full equivalence on the test corpus.

### 3. Code & Asset Round-Trip

- **FR13.** `[Existing]` User can recompile annotated ASM back to a `.nes` file via `qlnes recompile`, producing a byte-identical reproduction of the source ROM.
- **FR14.** `[Existing]` User can extract CHR-ROM sprites as PNG sheets via `qlnes analyze --assets`, with each bank emitted as a separate file.
- **FR15.** `[Growth]` User can round-trip extracted PNG sheets back to byte-identical CHR-ROM banks (`PNG → CHR` equivalence).
- **FR16.** `[Vision]` User can extract gameplay data tables (drop tables, RNG seeds, AI scripts) as structured JSON or markdown artifacts.

### 4. Equivalence Verification & Coverage Reporting

- **FR17.** `[Existing]` User can verify a round-trip on a single ROM via `qlnes verify <rom>` (current behaviour: byte-identical reassembled ROM).
- **FR18.** `[MVP]` User can verify the audio equivalence invariant on a single ROM via `qlnes verify --audio <rom>` against the FCEUX reference.
- **FR19.** `[MVP]` User can run the full equivalence audit across the test corpus via `qlnes audit`, producing a versioned `bilan.json` report.
- **FR20.** `[MVP]` `qlnes audit` exits non-zero (`102`) without writing `bilan.json` if any ROM declared in the test corpus lacks its FCEUX reference output.
- **FR21.** `[MVP]` User can read the coverage matrix via `qlnes coverage`, rendered as a human-readable table by default or as JSON via `--format json`. The matrix axis is **per-mapper** for non-audio artifacts (`analyze`, `verify`) and **per-(mapper, audio engine)** for audio artifacts (`audio`, `nsf`), reflecting that audio coverage depends on whether the ROM's audio engine has a recognized handler.
- **FR22.** `[MVP]` `qlnes coverage` automatically runs `qlnes audit` and generates `bilan.json` if it is missing or fails schema validation.
- **FR23.** `[MVP]` `qlnes coverage` warns the user that `bilan.json` is likely stale if its `generated_at` predates any source file in `qlnes/`, and suggests `--refresh`.
- **FR24.** `[MVP]` User can force a re-audit via `qlnes coverage --refresh`, bypassing the cached `bilan.json`.
- **FR25.** `[MVP]` `bilan.json` records, per supported mapper and per artifact type, the pass/fail status, the corpus ROM count, the failure count, and the SHA-256s of failing ROMs. For audio artifacts (`audio`, `nsf`), an additional `engines` sub-map records the same fields per recognized audio engine plus a synthetic `unknown` entry for ROMs whose engine is not recognized; the `unknown` entry is always reported with `status: "unverified"`, never `pass`.
- **FR26.** `[MVP]` Every release is gated by a 100% equivalence pass rate on the supported portion of the test corpus; partial passes block release for the affected mapper.

### 5. Configuration & Invocation Surface

- **FR27.** `[MVP]` User can configure `qlnes` via four layers, each overriding the previous: built-in defaults, project-level `qlnes.toml`, `QLNES_*` environment variables, CLI flags.
- **FR28.** `[MVP]` Every value expressible via `qlnes.toml` or a `QLNES_*` env var is also expressible via a CLI flag.
- **FR29.** `[MVP]` `qlnes audio`, `qlnes verify`, `qlnes audit`, and `qlnes coverage` each honor `qlnes.toml` defaults under their own section plus the shared `[default]` section.
- **FR30.** `[MVP]` User can install shell completion for bash, zsh, fish, and PowerShell via `--install-completion` (Typer's built-in mechanism).
- **FR31.** `[Growth]` User can install `qlnes` via `pip install qlnes` and invoke it as `qlnes <command>` (in addition to `python -m qlnes`).
- **FR32.** `[Vision]` User can launch an interactive REPL via `qlnes shell <rom>` to explore a ROM, list subroutines, and audition tracks without re-invoking the CLI.

### 6. Scripting & Robustness Contract

- **FR33.** `[MVP]` `qlnes` exits with documented, semver-disciplined exit codes drawn from `sysexits.h` plus a `qlnes`-specific extension range: `0` success, `2`/`64` usage error, `65` malformed ROM, `66` missing input, `70` internal error, `73` non-writable output, `74` I/O error, `100` unsupported mapper, `101` equivalence-check failure, `102` missing reference, `130` SIGINT.
- **FR34.** `[MVP]` Every error written to `stderr` is prefixed `qlnes: error:` and followed on the next line by a single-line JSON payload with structured fields (`code`, `class`, plus class-specific details such as `mapper`, `rom_sha256`).
- **FR35.** `[MVP]` Output files are written atomically: the tool writes to a sibling `.tmp` and renames on completion. A crash never leaves a half-written output.
- **FR36.** `[MVP]` `qlnes` performs pre-flight validation before writing any output (header valid, mapper supported for the artifact, output directory writable, reference corpus available). Predictable failures fail before the first byte is written.
- **FR37.** `[MVP]` `qlnes` refuses to overwrite an existing output file unless `--force` is passed; the refusal exits with code `73`.
- **FR38.** `[MVP]` User can pass `--strict` to make any warning fatal; CI uses `--strict` by default.
- **FR39.** `[MVP]` In non-TTY mode (output piped), `qlnes` emits no progress bars or interactive prompts; behaviour is purely batch.
- **FR40.** `[MVP]` Stack traces are suppressed from `stderr` by default; `--debug` exposes them for development.

## Non-Functional Requirements

### Performance

Performance budgets are defined for a developer laptop (4-core CPU, 16 GB RAM, SSD). Cloud-CI hosts may differ.

- **NFR-PERF-1.** `qlnes analyze <rom>` on a 32 KB iNES ROM completes in under **2 seconds** (cold cache).
- **NFR-PERF-2.** `qlnes audio <rom> --format wav` renders each track at **≤ 2× real time** (a 3-minute track renders in under 6 minutes).
- **NFR-PERF-3.** `qlnes audit` on a 50-ROM corpus (mixed mappers) completes in **under 30 minutes** on a developer laptop. CI may be slower; if CI exceeds 60 minutes for a typical commit, the corpus or scheduling strategy must be revisited.
- **NFR-PERF-4.** `qlnes coverage` (read-only path against an existing `bilan.json`) completes in **under 100 ms**.
- **NFR-PERF-5.** Peak resident memory for any single `qlnes` invocation stays **under 500 MB** on the canonical hardware. The product is not expected to support memory-constrained embedded hosts.

### Reliability & Determinism

The product's value proposition is strict equivalence. Determinism is therefore a first-class quality attribute, not an afterthought.

- **NFR-REL-1.** Given the same input ROM, the same `qlnes` version, the same FCEUX reference, and the same flags, every output is **byte-identical** across runs and across hosts (within the supported portability matrix). The PCM stream is the canonical hash target. `MP3` byte-equivalence is additionally bounded by the encoder library version (LAME stamps its version into the MP3 Info Tag); cross-version equivalence checks hash the PCM, not the MP3.
- **NFR-REL-2.** No output artifact contains a wall-clock timestamp, hostname, username, or other host-specific value by default. `bilan.json`'s `generated_at` is the documented exception (it is part of the audit's provenance and not part of any equivalence-checked artifact).
- **NFR-REL-3.** Any internal parallelism is order-deterministic: the output of a parallel render is bit-identical to the serial render of the same input.
- **NFR-REL-4.** Output files are written atomically (per FR35); a crash or kill leaves the previous output (if any) intact.
- **NFR-REL-5.** `qlnes` is crash-free on the supported test corpus — no segfaults, no uncaught exceptions reaching the user. Internal errors surface as exit code `70` with the structured JSON payload.

### Portability

- **NFR-PORT-1.** Linux is the canonical supported platform (current dev environment: Debian-derived, Python 3.11+).
- **NFR-PORT-2.** macOS support is a non-goal for MVP; a port is welcome in Growth if `qlnes` runs cleanly on a stock macOS Python without code changes.
- **NFR-PORT-3.** Windows support is explicitly deferred. Path handling uses `pathlib`, so most paths should be Windows-clean by construction, but FCEUX integration on Windows is not validated and is out of scope.
- **NFR-PORT-4.** The Python floor is `3.11` (matches the project's current floor and unblocks newer typing features). The ceiling is the highest Python version on which the test corpus passes.

### External Dependencies

- **NFR-DEP-1.** FCEUX is the **only** hard external (non-Python) dependency in MVP. `qlnes audit` and `qlnes verify --audio` require it. All other commands work without FCEUX.
- **NFR-DEP-2.** Python dependencies are pinned by floor only in `requirements.txt`, matching the current convention. `deptry` runs weekly in CI to catch unused or undeclared deps.
- **NFR-DEP-3.** `cynes` is treated as optional and feature-gated: if not importable, `qlnes` falls back to static-only analysis with a clear message; commands depending on dynamic discovery exit `66` if cynes is required and missing.
- **NFR-DEP-4.** Adding a new hard external dependency (binary or library) requires a PRD update. Internal Python deps may be added by normal patch.
