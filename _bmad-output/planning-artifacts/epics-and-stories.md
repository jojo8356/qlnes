---
stepsCompleted:
  - 'step-01-init'
  - 'step-02-epic-quality-guardrails'
  - 'step-03-epic-list'
  - 'step-04-stories-per-epic'
  - 'step-05-acceptance-criteria'
  - 'step-06-dependency-graph'
  - 'step-07-fr-coverage-matrix'
  - 'step-08-nfr-touch-points'
  - 'step-09-sprint-sequencing'
  - 'step-10-out-of-scope-deferral'
  - 'step-11-sign-off'
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
  - _bmad-output/project-context.md
documentCounts:
  prd: 1
  ux: 1
  architecture: 1
  research: 0
  projectDocs: 1
  readinessReport: 1
projectMemoriesReferenced:
  - project_cli_only_no_public_api.md
  - project_audio_architecture_decisions.md
workflowType: 'epics-and-stories'
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
mvp_fr_count: 28
epic_count: 5
story_count: 23
---

# Epics & Stories — qlnes (Music-MVP)

**Author:** Johan
**Date:** 2026-05-03
**Status:** Ready for sprint planning. Inputs to `bmad-sprint-planning` (SP).

---

## 1. Overview

This document slices the **28 MVP Functional Requirements** of `qlnes` into **5 epics** and **23 stories**. Every story is a vertical slice that delivers user-visible value or actively prevents user-visible regression. Cross-cutting infrastructure (atomic writes, error emitter, config loader, …) is embedded *inside* the first user-value story that exercises it — never authored as its own technical-milestone story.

The seam structure (epics A–E) was proposed by the architecture document (§18) and is preserved verbatim here. This document expands each seam into stories with acceptance criteria, file-level dev notes, and FR/NFR traceability.

### Inputs consumed

- **PRD** — 28 MVP FRs (FR5–FR11, FR18–FR30, FR33–FR40), 18 NFRs.
- **UX design** — 14 sections, 15 locked decisions, 10 sample sessions used as AC fixtures.
- **Architecture** — 17 components, 7 cross-cutting modules, 20 ADRs, 5 epic seams, 12 risks.
- **Readiness report** — pre-emptive epic guidance (no technical-milestone epics, no forward deps, vertical slices).

### Output

- 5 epics (A–E), 23 stories (A.1–A.6, B.1–B.5, C.1–C.4, D.1–D.5, E.1–E.3).
- One story dependency graph.
- One FR↔story coverage matrix (28 / 28 MVP FRs covered).
- One NFR-touch table per story.
- One recommended sprint sequence.

---

## 2. Epic-Quality Guardrails (recalled)

The readiness report's *Pre-emptive Epic Guidance* identified four common epic-shape violations. This doc enforces them:

| Anti-pattern | How this doc avoids it |
|---|---|
| **Technical-milestone epic** ("Build the APU emulator", "Set up CI") | Epics are titled by user outcome ("Get music out of a ROM", "Trustworthy coverage"). The APU lands inside A.1. CI lands inside B.4 + D.4. |
| **Forward dependencies** (epic 3's story X depends on epic 4's story Y) | Dependency graph (§7) is a DAG. The only cross-epic edge is *A enables everything*. B/C/D/E only depend on A.1's cross-cutting scaffold. E is fully independent (regression net for existing features). |
| **Story without user-visible value** | Every story's title starts with a user value verb: "Render", "See", "Verify", "Get", "Refuse", "Surface". Cross-cutting modules are listed in dev notes, never in titles. |
| **Story not a vertical slice** | Every story closes ≥ 1 user-visible AC end-to-end (CLI invocation → artifact on disk OR stderr line OR exit code). Modules added are exercised by the same story's AC. |

### Story shape (locked)

```
### <Story ID> — <user value verb + outcome>

**User value.** <one sentence — what the user can now do that they couldn't before>
**FR(s) closed.** <list>
**NFR(s) touched.** <list, with the verification mechanism>
**Pre-conditions.** <stories that must merge first>
**Embedded scaffolding.** <new components/modules introduced in this story>

**Acceptance criteria.**
- AC1 — <given/when/then; testable>
- AC2 — ...

**Dev notes.**
- Files touched / created
- Key invariants / cross-cutting hooks
- Test layers exercised

**Estimate.** <S / M / L> — <1 dev-day / 2–3 dev-days / 1 week>
```

`S = ≤ 1 dev-day`, `M = 2–3 dev-days`, `L = 1 dev-week`. Solo developer assumption (PRD).

---

## 3. Epic List

| ID | Title | User journeys | Stories | FRs closed (MVP) | Estimate |
|---|---|---|---|---|---|
| A | **Get music out of a ROM** | Marco J1, Marco J4 | 6 | FR6, FR7, FR8, FR9, FR10, FR11, FR18, FR27 (scaffold), FR33–FR36 (scaffold) | ~3 weeks |
| B | **Trustworthy coverage** | (cross-cutting) | 5 | FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26 | ~2 weeks |
| C | **Sara's NSF with per-track metadata** | Sara J2 | 4 | FR5 | ~1.5 weeks |
| D | **Pipeline-grade CLI contract** | Lin J3, Marco J4 | 5 | FR27 (polish), FR28, FR29, FR30, FR37, FR38, FR39, FR40 | ~1.5 weeks |
| E | **Regression net for existing features** | (cross-cutting) | 3 | FR1, FR2, FR3, FR4, FR13, FR14, FR17 (validation only — already shipped) | ~3 dev-days |
| | **Total MVP** | | **23 stories** | **28 MVP FRs** | **~8 weeks (solo)** |

> **MVP date target.** Not pinned by the PRD. The 8-week estimate is solo-developer rough sizing; real sprint planning (`SP`) will refine. Confidence band: ±30%, dominated by the FamiTracker-engine equivalence work in A.1+A.4.

---

## 4. Epic A — Get music out of a ROM

**User value.** Marco runs `qlnes audio rom.nes --format wav --output tracks/`, gets sample-equivalent WAV files for any FT or Capcom ROM on a covered mapper, and Marco's pipeline (or his ear) cannot tell the difference vs FCEUX.

**Closes journeys.**
- *Marco J1 (happy path)* — sample-equivalent WAV.
- *Marco J4 (unsupported mapper)* — clean exit-100 error with `unsupported_mapper` JSON payload.

**FRs closed.** FR6, FR7, FR8, FR9, FR10, FR11, FR18, plus the cross-cutting subset of FR27, FR33–FR36 needed for A.1 to ship.

**Risks tracked.** R1 (APU sample-eq shortfall), R10 (loop-detection misclass), R12 (DMC tier-2 flood).

### Story A.1 — Render one mapper-0 FamiTracker ROM to sample-equivalent WAV

**User value.** Marco picks one mapper-0 ROM whose audio engine is FamiTracker, runs `python -m qlnes audio rom.nes --format wav --output tracks/`, and gets one or more `.wav` files whose PCM is bit-identical to FCEUX's reference render.

**FR(s) closed.** FR6 (one engine, one mapper), FR9 (deterministic filenames), FR11 (tier-1 sample-eq for recognized engine), partial FR8 (`--format wav` only), partial FR10 (referenced songs only — FR10 fully closed in A.5).

**NFR(s) touched.**
- NFR-PERF-2 (≤ 2× real time) — verified by `tests/integration/test_audio_perf.py`.
- NFR-REL-1 (byte-identical PCM) — verified by `tests/invariants/test_pcm_equivalence.py`.
- NFR-REL-4 (atomic writes) — verified by `tests/invariants/test_atomic_kill.py`.
- NFR-REL-2 (no wall-clock in artifact) — verified by `tests/invariants/test_determinism.py::test_no_wallclock_in_artifact`.

**Pre-conditions.** None. This is the first story of the MVP and the only one that lands the cross-cutting scaffold without any prior story.

**Embedded scaffolding.**
- `qlnes/io/atomic.py` (atomic-write helper, FR35).
- `qlnes/io/errors.py` (`QlnesError` + `emit`, FR33–FR34).
- `qlnes/io/preflight.py` (Preflight runner, FR36 — minimal: rom-readable + output-writable).
- `qlnes/det.py` (canonical_json, sha256_file, deterministic_track_filename).
- `qlnes/config/loader.py` (4-layer resolver, minimal schema covering `[default]` + `[audio]`, FR27 partial).
- `qlnes/apu/{__init__,pulse,triangle,noise,mixer,tables}.py` (4-channel APU, no DMC).
- `qlnes/audio/engine.py` (`SoundEngine` ABC + `SoundEngineRegistry`).
- `qlnes/audio/engines/famitracker.py` (FT handler — detect, walk_song_table, render_song, detect_loop tier-1).
- `qlnes/audio/renderer.py` (engine → APU → PCM → WAV pipeline).
- `qlnes/audio/wav.py` (RIFF + `'smpl'` chunk writer).
- `qlnes/oracle/fceux.py` (subprocess wrapper, trace + reference-PCM capture).
- `qlnes/audio_trace.lua` (refined to schema v1, captures both trace TSV and reference WAV).
- `cli.py::audio` migrated to route through `errors.emit` and `atomic_write_*`.

**Acceptance criteria.**
- **AC1.** `python -m qlnes audio <fixture-rom.nes> --format wav --output <tmp>/` produces N files named `<rom-stem>.<song-index-2-digit>.famitracker.wav` (where N matches the FT song-table count). Filenames are deterministic across runs.
- **AC2.** For every produced WAV, the embedded PCM stream is byte-identical (SHA-256 match) to the FCEUX reference for the same ROM × song-index pair, captured via `qlnes/audio_trace.lua` against fceux ≥ 2.6.6.
- **AC3.** Rendering a 3-minute FT song completes in under 6 minutes on the canonical hardware (NFR-PERF-2 budget).
- **AC4.** Killing the process with SIGKILL mid-render leaves the target directory unchanged (no `.wav` artifacts written, no `.tmp` orphans). Verified by `tests/invariants/test_atomic_kill.py`.
- **AC5.** Running `qlnes audio` against a *non*-readable file exits 66, prefixes stderr with `qlnes: error: missing_input` (or `bad_rom` for a non-iNES file), follows with one-line JSON `{"code":66,"class":"missing_input",...}`.
- **AC6.** Running with `--output <existing-file>.wav` (single file mode) without `--force` exits 73 with `cant_create` JSON. Adding `--force` overwrites cleanly.
- **AC7.** Two consecutive runs with the same flags produce byte-identical output files (NFR-REL-1).
- **AC8.** Output files contain no wall-clock timestamp, hostname, or username (NFR-REL-2). Verified by grepping the artifact bytes for `LANG`/`USER`/today's date.

**Dev notes.**
- Replace the existing `qlnes/audio.py` ffmpeg-based path with the new `qlnes/audio/renderer.py` pipeline. Keep `audio.py` as a thin backwards-compat shim that delegates; remove in A.6.
- The Lua trace script writes to `$QLNES_TRACE_PATH` (env var). The reference WAV is written via fceux's `sound.get` API to `<trace>.wav`. Both are read by `FceuxOracle`.
- Pre-flight predicates added in this story: `_check_rom_readable`, `_check_output_writable`, `_check_fceux_on_path`. Mapper-supported and lameenc-available predicates land in A.4 / A.2 respectively.
- The fixture ROM for `tests/integration/test_audio_pipeline.py` is one mapper-0 FT ROM (e.g. a homebrew test ROM legally distributable under MIT) — committed to `tests/fixtures/`.
- Tests exercised: `tests/unit/test_apu_pulse.py`, `test_apu_triangle.py`, `test_apu_noise.py`, `test_apu_mixer.py`, `test_engine_famitracker.py`, `test_atomic_writer.py`, `test_errors_emitter.py`, `test_det.py`; `tests/integration/test_audio_pipeline.py`, `test_cli_audio.py`; `tests/invariants/test_pcm_equivalence.py` (parametrized over the FT subset of the corpus), `test_atomic_kill.py`, `test_determinism.py::test_render_twice_identical`, `test_no_wallclock_in_artifact`.

**Estimate.** **L** — 1 dev-week. The APU emulator alone is ~2 days; FT engine handler ~2 days; cross-cutting scaffold + integration ~1 day.

---

### Story A.2 — Render the same ROM to MP3 via `lameenc`

**User value.** Marco passes `--format mp3` and gets per-track MP3 files whose PCM (decoded from the MP3) matches the WAV path's PCM, lossy at LAME's V2 default.

**FR(s) closed.** FR7 (MP3 output), partial FR8 (adds `mp3` to `--format`).

**NFR(s) touched.**
- NFR-DEP-2 (`lameenc==1.7.0` `==`-pinned) — verified by `requirements.txt` review + `tests/unit/test_mp3_encoder.py`.
- NFR-REL-1 (PCM equivalence) — MP3 byte-equivalence is encoder-version-bounded; PCM-decoded equivalence is the canonical invariant.

**Pre-conditions.** A.1 merged.

**Embedded scaffolding.**
- `qlnes/audio/mp3.py` (`Mp3Encoder` wrapping `lameenc`; encode-from-PCM, encode-from-WAV-path).
- Pre-flight predicate `_check_lameenc_available` activated when `--format mp3`.
- `requirements.txt` adds `lameenc==1.7.0`.

**Acceptance criteria.**
- **AC1.** `qlnes audio rom.nes --format mp3 --output tracks/` produces N `.mp3` files named with the locked filename convention (`<rom>.<idx>.<engine>.mp3`).
- **AC2.** Decoding the produced MP3 back to PCM and comparing sample-by-sample to the WAV path's PCM (same ROM × song-index): the absolute mean error is below 1 % of full-scale (≈ 327 LSB on 16-bit signed). This bounds the lossy-encode budget and proves the MP3 was rendered from the same internal PCM source as the WAV — not from a divergent path. Byte-identity of decoded PCM to source PCM is **not** asserted (lossy compression cannot be byte-equivalent by definition; AC4 below covers MP3-byte determinism on the encoded side, which is the meaningful invariant).
- **AC3.** Running `qlnes audio --format mp3` on a host without `lameenc` installed (or with a different `lameenc` version) exits 70 (`internal_error` with `detail="missing_dependency"` and `dep="lame"`) and a hint pointing at `scripts/install_audio_deps.sh`.
- **AC4.** Two consecutive `--format mp3` runs on the same host produce byte-identical MP3 files (locked encoder version means deterministic output).
- **AC5.** `tests/unit/test_mp3_encoder.py` includes a `@pytest.mark.lameenc(version="1.7.0")` skip marker; tests that compare MP3 bytes are skipped under any other lameenc version.

**Dev notes.**
- Pure subprocess-`lame` fallback documented but not wired in MVP. If `lameenc` ever drops Python 3.13 support, the fallback unblocks us without API change.
- `Mp3Encoder.encode(pcm: bytes, sample_rate: int = 44_100, bitrate: str = "V2") -> bytes` is the only public entry. Bitrate is fixed at V2 in MVP (matches what most NES OST consumers expect); tunable via a future `qlnes.toml [audio] mp3_bitrate` key (Growth).
- `cli.py::audio` reuses the rendering pipeline from A.1; only the final encode step changes.

**Estimate.** **S** — 1 dev-day.

---

### Story A.3 — Encode loop boundaries into WAV `'smpl'` chunks

**User value.** Marco's downstream audio engine (Rust audio system in his case) auto-loops `track-04.wav` correctly because the WAV's `'smpl'` chunk encodes the loop start/end. No manual Audacity surgery.

**FR(s) closed.** Partial FR6 (loop-aware WAV), partial FR10 (engine-bytecode loop-tier 1).

**NFR(s) touched.** NFR-REL-1 (deterministic loop boundaries; same ROM → same boundary frame).

**Pre-conditions.** A.1 merged.

**Embedded scaffolding.**
- `qlnes/audio/wav.py` extended: `'smpl'` RIFF chunk emission with type-0 (forward loop), `dwManufacturer=0`, `dwProduct=0`, `dwSamplePeriod` derived from `sample_rate`.
- `qlnes/audio/engines/famitracker.py::detect_loop` wired to FT bytecode loop sentinels (`Bxx` instruction → loop point, end-of-pattern → end frame).
- `qlnes/audio/engine.py::LoopBoundary` struct.

**Acceptance criteria.**
- **AC1.** WAV files for FT songs that contain a `Bxx` loop opcode have a `'smpl'` chunk in the RIFF stream. Verified by parsing the chunk back via stdlib `wave` (or `riff` parser) and asserting `dwSampleLoops == 1`.
- **AC2.** The `dwStart` and `dwEnd` sample offsets of the `'smpl'` chunk match the engine's reported loop boundaries to the sample (not the frame).
- **AC3.** WAV files for non-looping songs (e.g. jingles) emit no `'smpl'` chunk. Verified by absence.
- **AC4.** Running the WAV through a third-party verifier (`ffprobe -show_chunks`) confirms the `'smpl'` chunk is well-formed.
- **AC5.** Two runs produce byte-identical WAV bytes including the `'smpl'` chunk (loop boundaries are deterministic).

**Dev notes.**
- The FT loop opcode `Bxx` jumps to pattern X. We compute loop start = sample-offset where the jumped-to pattern begins; loop end = sample-offset just before the jump.
- WAV `'smpl'` chunk format reference: Multimedia Programming Interface and Data Specifications 1.0, Aug 1991, §4.7. Implementation is ~30 LOC.
- For the generic-engine path (A.5), `detect_loop` returns `None` and no `'smpl'` chunk is emitted (P3 — no false fidelity claims).

**Estimate.** **S** — 1 dev-day.

---

### Story A.4 — Add Capcom engine handler and broaden corpus to mappers 1, 2, 4, 66

**User value.** Marco's other ROMs (mostly Capcom platformers, MMC1/MMC3, mapper-66 multibank) now also produce sample-equivalent output. Capcom is the second tier-1 engine.

**FR(s) closed.** Partial FR11 (broadens recognized-engine coverage to a second engine).

**NFR(s) touched.** NFR-PERF-3 (audit time on growing corpus).

**Pre-conditions.** A.1, A.3.

**Embedded scaffolding.**
- `qlnes/audio/engines/capcom.py` — Capcom-3 / Sakaguchi engine handler. Detection signatures (mapper match + ASCII `CAPCOM` near reset vector + 2-byte note-event format heuristic). Implements `detect_loop` against Capcom's `0xFE` master-loop sentinel byte.
- Expand `corpus/manifest.toml` with 4–6 Capcom ROM entries spanning M1, M2, M4, M66.
- Pre-flight predicate `_check_mapper_supported_for_audio(mapper, engine_name)` consults a `qlnes/audio/engines/__init__.py` mapping.

**Acceptance criteria.**
- **AC1.** `qlnes audio` against any of the 4–6 newly-corpus'd Capcom ROMs produces sample-equivalent WAVs (PCM SHA-256 matches FCEUX reference).
- **AC2.** `qlnes audio` against a mapper-66 Capcom ROM (uses the multi-bank pipeline shipped in `c8fbc8f`) does not regress: the existing mapper-66 path stays green.
- **AC3.** `SoundEngineRegistry.detect()` resolves Capcom > FamiTracker on a Capcom ROM (confidence ordering).
- **AC4.** Loop boundaries detected via Capcom's `0xFE` sentinel are accurate to the sample on at least one ROM with a known-correct loop point.
- **AC5.** `corpus/manifest.toml` now lists ≥ 6 Capcom ROMs and the audit `bilan.json` (when generated in epic B) reports `engines.capcom: pass` for all of them.

**Dev notes.**
- Capcom's note-event format is documented on NESdev wiki (Capcom_3 / Sakaguchi engine). 2-byte format: `<note>:<duration>`.
- The `0xFE` master-loop sentinel is the engine's "go to loop point" marker; the loop point itself is a stored 16-bit address earlier in the song-pattern table.
- Capcom expansion sound is *not* in MVP scope (no MMC5/VRC6 in the corpus). Stays at tier-2 if encountered.

**Estimate.** **L** — 1 dev-week. Engine reverse-engineering is the dominant cost.

---

### Story A.5 — Surface unrecognized-engine output as `unverified` (generic fallback)

**User value.** Marco runs `qlnes audio rom.nes` on a ROM whose audio engine is not yet recognized. Instead of failing, qlnes emits frame-accurate WAV files tagged `unverified`, so Marco still gets *something* — but knows not to trust the loop boundaries or the sample-level fidelity.

**FR(s) closed.** Closes FR11 (tier-1 + tier-2 dual-tier promise), closes FR10 (exhaustive walk including unreferenced songs — works for both engine-recognized and generic paths).

**NFR(s) touched.** NFR-REL-5 (crash-free on supported corpus).

**Pre-conditions.** A.1, A.3.

**Embedded scaffolding.**
- `qlnes/audio/engines/generic.py` — generic fallback handler. Walks the FCEUX trace as a flat sequence of APU writes; emits PCM as one continuous block of the requested duration; reports `tier=2`; `detect_loop` returns `None`.
- `SoundEngineRegistry.detect()` falls through to `GenericEngine` when no specific handler scores ≥ 0.6.
- `--strict` integration: `GenericEngine.render_song` raises `QlnesError("equivalence_failed", "engine not recognized; --strict refuses tier-2 fallback")` when called under strict mode.
- WAV filename uses `unknown` as the engine slug (per UX §5.3 / §10.3 and ADR-15).

**Acceptance criteria.**
- **AC1.** A ROM with no recognized engine produces N WAV files named `<rom>.<idx>.unknown.wav` of the requested duration (default 600 frames = 10s).
- **AC2.** No `'smpl'` chunk is emitted in tier-2 output (the loop is unknown — claim no fidelity we can't prove).
- **AC3.** `--strict` against the same ROM exits 101 (`equivalence_failed`) with `class: "equivalence_failed"`, `extra.reason: "engine_not_recognized"`.
- **AC4.** `bilan.json` (when produced in epic B against this ROM) records the audio result under `engines.unknown` with `status: "unverified"`, never `pass` (ADR-15 invariant).
- **AC5.** `qlnes coverage` (epic B) renders the row with `… unverified` glyph and a yellow tint.

**Dev notes.**
- The generic handler doesn't *understand* the song table, so "exhaustive song-table walk" means: emit the entire trace as one block. Multi-track output for tier-2 requires per-engine knowledge by definition; FR10's "including unreferenced songs" is satisfied for tier-1 engines and is a no-op for tier-2.
- The fallback uses the FCEUX trace exactly as captured; the qlnes APU emulator replays it for sample synthesis. Cross-host determinism is preserved (the trace is deterministic; the APU emulator is integer-arithmetic).

**Estimate.** **M** — 2–3 dev-days.

---

### Story A.6 — Verify a single ROM's audio against FCEUX

**User value.** Marco runs `qlnes verify --audio rom.nes` and gets a clean `ok:` line (or a structured error pointing at the divergence frame) without re-running a full `audit`.

**FR(s) closed.** FR18 (per-ROM audio equivalence verification).

**NFR(s) touched.** NFR-REL-1 (sample-equivalence — re-uses the same hash-equality comparator).

**Pre-conditions.** A.1, A.5.

**Embedded scaffolding.**
- `cli.py::verify` extended: `--audio` flag (already declared in PRD §223).
- `qlnes/audio/renderer.py` exposes a `verify_pcm(rom: Path) -> VerifyResult` returning a struct `{equal: bool, divergence_frame: int | None, expected_hash: str, actual_hash: str}`.
- Removes the old `audio.py` shim (last caller now gone).

**Acceptance criteria.**
- **AC1.** `qlnes verify --audio rom.nes` for a sample-equivalent ROM emits one stdout line `ok: audio identical (<song-count> tracks, <sample-count> samples)` and exits 0.
- **AC2.** For a deliberately broken ROM (corpus fixture: a tampered FT ROM), `qlnes verify --audio` exits 101 with `class: "equivalence_failed"`, `extra: {"divergence_frame": <int>, "expected_hash": "...", "actual_hash": "..."}`.
- **AC3.** `qlnes verify --audio` against an `unverified`-tier ROM exits 101 in `--strict` mode, exits 0 with a warning line `qlnes: warning: tier-2 (frame-accurate)…` outside `--strict`.
- **AC4.** `qlnes verify` (no `--audio`) keeps its existing round-trip semantics unchanged. Verified by E.1's regression suite.
- **AC5.** Removing `qlnes/audio.py` does not break any public command. The MP3 encoding path now lives only in `qlnes/audio/mp3.py`.

**Dev notes.**
- The `divergence_frame` is computed by walking PCM in 1-frame windows (~735 samples at 44.1 kHz NTSC) and comparing hashes per frame. First mismatched frame index is reported.
- This story is the natural place to delete the legacy `qlnes/audio.py` file. Its responsibilities have been split across `qlnes/audio/{renderer,mp3,wav}.py`.

**Estimate.** **S** — 1 dev-day.

---

## 5. Epic B — Trustworthy coverage

**User value.** Anyone (Marco, Sara, Lin, a curious GitHub visitor) can answer "what works on which mappers and which engines today?" by typing `qlnes coverage`. The matrix is auto-generated, never hand-maintained, schema-versioned, and embedded in every release as the ground-truth scoreboard.

**FRs closed.** FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26.

**Risks tracked.** R6 (xdist non-determinism), R12 (DMC tier-2 flood — visible here).

### Story B.1 — Audit one ROM and write `bilan.json`

**User value.** A maintainer runs `qlnes audit` on a one-ROM corpus and produces a valid `bilan.json` matching the locked schema, ready to be consumed by `coverage`.

**FR(s) closed.** Partial FR19 (audit, single-ROM mode).

**NFR(s) touched.** NFR-REL-1 (canonical JSON output), NFR-REL-2 (no wall-clock except in `generated_at`), NFR-REL-4 (atomic write).

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- `qlnes/audit/bilan.py` (`BilanStore.read/write/is_stale`, schema-versioned).
- `qlnes/audit/bilan_schema.json` (JSON Schema for v1).
- `qlnes/audit/runner.py::AuditRunner` (single-ROM mode initially).
- `qlnes/audit/corpus.py` (`load_manifest(path: Path) -> Corpus`).
- `cli.py::audit` (new command).

**Acceptance criteria.**
- **AC1.** `qlnes audit --corpus tests/fixtures/mini-corpus/` writes a `bilan.json` to `./bilan.json` (or to `--bilan <path>`).
- **AC2.** The produced `bilan.json` validates against `qlnes/audit/bilan_schema.json` (use stdlib `json` + a hand-rolled validator, or `jsonschema` if added — defer dep decision to this story).
- **AC3.** The file is canonical: `json.dumps(..., sort_keys=True, separators=(",", ":"))` round-trips identical bytes.
- **AC4.** Running `qlnes audit` twice on the same corpus (same fceux version, same qlnes version) produces byte-identical `bilan.json` *except* for the `generated_at` field. (The exception is documented in NFR-REL-2 and project memory.)
- **AC5.** `qlnes audit` against a corpus where one ROM lacks its FCEUX reference exits 102 (`missing_reference`) without writing `bilan.json` (FR20).

**Dev notes.**
- For B.1, "validator" can be a hand-rolled function in `qlnes/audit/bilan.py::_validate(d: dict) -> None`; importing `jsonschema` is not justified for one schema. If we ever add a second JSON schema (`coverage` JSON output schema), revisit and add `jsonschema>=4.20` to deps.
- `BilanStore.write` calls `det.canonical_json` then `atomic.atomic_write_text` — the only correct path.

**Estimate.** **M** — 2–3 dev-days.

---

### Story B.2 — See the coverage matrix as table or JSON

**User value.** Marco/Lin/Sara typing `qlnes coverage` see the human-aligned table from UX §5.3; pipelines piping `qlnes coverage --format json` get the locked-schema document directly.

**FR(s) closed.** FR21 (table + JSON), FR25 (engine sub-map rendering).

**NFR(s) touched.** NFR-PERF-4 (`coverage` < 100 ms read-only path).

**Pre-conditions.** B.1.

**Embedded scaffolding.**
- `qlnes/coverage/render.py` (`render_table(bilan) -> str`, `render_json(bilan) -> str`).
- `qlnes/coverage/__init__.py` (public re-exports).
- `cli.py::coverage` (new command).

**Acceptance criteria.**
- **AC1.** `qlnes coverage` on the fixture `bilan.json` from B.1 emits the table format from UX §5.3 to stdout. Order: mapper ascending, then artifact in `(analyze, nsf, audio, verify)`.
- **AC2.** Status symbols are paired with words (`✓ pass`, `⚠ partial`, `… unverified`, `· missing`, `✗ fail`). Color is auto-on iff stdout is a TTY.
- **AC3.** Setting `NO_COLOR=1` or piping `qlnes coverage | cat` emits the same text without ANSI escapes. Setting `LANG=C` falls back to ASCII glyphs (`[OK]`, `[WARN]`, `[??]`, `[--]`, `[FAIL]`).
- **AC4.** `qlnes coverage --format json` emits `bilan.json` *as-is* on stdout (the file is the contract; don't reformat it). The output is parseable by `jq` and matches `bilan.json`'s SHA-256.
- **AC5.** Read-only `qlnes coverage` (with a fresh `bilan.json`) completes in under 100 ms on the canonical hardware.

**Dev notes.**
- Table rendering: pure Python `str.ljust` / `str.rjust` per column. No `tabulate` dep.
- The engine column is multi-token; format is `name:passed[/total][ note]`. Free of locale-specific separators.

**Estimate.** **M** — 2–3 dev-days.

---

### Story B.3 — Set up the corpus manifest and reference-generation script

**User value.** A new contributor (or CI runner) places their own legally-obtained ROMs into `corpus/roms/` (named by SHA), runs `python scripts/generate_references.py`, and the corpus is ready for audits without redistributing a single byte of commercial content.

**FR(s) closed.** No new MVP FR (this story is ground-laying for FR19–FR26 and is the IP discipline of architecture step 11).

**NFR(s) touched.** NFR-DEP-1 (FCEUX is the only hard external — used here heavily).

**Pre-conditions.** B.1, A.1, A.4.

**Embedded scaffolding.**
- `corpus/manifest.toml` (initial 50-ROM target, populated incrementally; A.4 added Capcom entries; this story finalizes mapper-0 NROM, mapper-1 MMC1, mapper-4 MMC3, mapper-66 GxROM).
- `scripts/generate_references.py` (driver: `for rom in manifest: oracle.reference_pcm(rom); save sha`).
- `corpus/README.md` (contributor instructions, IP posture, FCEUX install pointer).
- `.gitignore` updated: `corpus/roms/`, `corpus/references/`.

**Acceptance criteria.**
- **AC1.** `corpus/manifest.toml` validates against an inline TOML schema check in `qlnes/audit/corpus.py::load_manifest`. Required fields per `[[rom]]`: `name`, `sha256`, `mapper`, `region`, `engine`, `song_count`. Optional: `notes`.
- **AC2.** `python scripts/generate_references.py` walks `corpus/manifest.toml`, for each ROM that exists locally at `corpus/roms/<sha>.nes`, generates `corpus/references/<sha>.audio.wav` and `corpus/references/<sha>.nsf` (latter is shippable artifact for C.1+). Updates `[[reference]]` table in `manifest.toml` with hashes.
- **AC3.** If a contributor's ROM file's SHA doesn't match the manifest entry's `sha256`, the script logs a `warning: rom <name> hash mismatch (expected …, got …)` and skips. The corpus invariant is preserved.
- **AC4.** `corpus/README.md` documents: (i) why we don't ship ROMs; (ii) where to legally obtain test corpus ROMs; (iii) the SHA-naming convention; (iv) the FCEUX installation procedure.
- **AC5.** Running `qlnes audit` after `generate_references.py` against a 4-ROM mini-corpus produces a `bilan.json` covering all four ROMs.

**Dev notes.**
- The reference-generation script is run *manually* by maintainers, not by `qlnes audit`. `audit` consumes the references; it does not generate them. This is by design (FR20 — audit refuses to write if references are missing).
- License posture in `NOTICE.md` (see architecture step 11) is added in this story.

**Estimate.** **M** — 2–3 dev-days.

---

### Story B.4 — Audit the full corpus in parallel and gate releases on the corpus pass rate

**User value.** Maintainer (Johan) tags `v0.5.0`; CI runs `qlnes audit --strict` against the full corpus in parallel, produces a versioned `bilan.json`, attaches it to the GitHub release, and refuses to publish if any mapper × artifact has regressed from `pass` to anything else vs the previous tag.

**FR(s) closed.** FR19 (full audit), FR26 (release gate).

**NFR(s) touched.** NFR-PERF-3 (full audit < 30 min on 50-ROM corpus, parallelized).

**Pre-conditions.** B.1, B.2, B.3, A.5.

**Embedded scaffolding.**
- `qlnes/audit/runner.py::AuditRunner.run(corpus) -> Bilan` parallelized via `concurrent.futures.ProcessPoolExecutor`. Per-ROM job is a pure function `(rom_path, expected_hashes) -> RomResult`.
- Aggregator collects `RomResult`s, sorts by `rom_sha256`, builds the `engines` sub-map.
- `.github/workflows/audit.yml` (weekly schedule + on-tag push).
- `scripts/restore-corpus.sh` (placeholder for the maintainer-only ROM-restoration step; uses GitHub Actions secret `QLNES_CORPUS_BUNDLE_URL`).
- Release-gate logic: a `scripts/diff_bilan.py` compares two bilans and exits non-zero on regression.

**Acceptance criteria.**
- **AC1.** `qlnes audit` on a 50-ROM corpus completes in under 30 minutes on a CI-equivalent runner (Ubuntu 22.04, 4 vCPU, 8 GB RAM). Parallelism is by `min(cpu_count, 8)` workers.
- **AC2.** The produced `bilan.json` has `corpus.rom_count == 50` and a complete `mapper_breakdown`.
- **AC3.** Per-ROM determinism: re-running with the same input produces identical PCM hashes (NFR-REL-3). Verified by running the audit twice in the workflow and diffing the two bilans (excluding `generated_at`).
- **AC4.** `scripts/diff_bilan.py prev.json new.json` exits 0 on no-regression, exits non-zero with a list of regressed mapper × artifact pairs otherwise. Wired into `audit.yml` on tag.
- **AC5.** `audit.yml` weekly run commits a maintainer-merged PR updating `bilan.json` if there are no regressions; opens an issue otherwise.

**Dev notes.**
- The `audit.yml` workflow uses GitHub Actions caching for the FCEUX install and the corpus references. ROM bytes themselves are never cached on GitHub-hosted runners (privacy/IP).
- `ProcessPoolExecutor` (not threads) — Python GIL would serialize APU emulator work otherwise.

**Estimate.** **M** — 2–3 dev-days.

---

### Story B.5 — Refresh the bilan automatically when stale

**User value.** Marco runs `qlnes coverage` on a freshly-cloned repo whose `bilan.json` is from last quarter. He gets either (a) a warning line + the existing table (default), or (b) automatic re-audit + fresh table (`--refresh`).

**FR(s) closed.** FR22 (auto-audit if absent or schema-invalid), FR23 (stale warning), FR24 (`--refresh`).

**NFR(s) touched.** NFR-PERF-4 (read-only path stays < 100 ms when bilan is fresh).

**Pre-conditions.** B.1, B.2, B.4.

**Embedded scaffolding.**
- `BilanStore.is_stale(bilan, sources)` predicate.
- `cli.py::coverage` extended with `--refresh` flag and the auto-audit fallback.

**Acceptance criteria.**
- **AC1.** `qlnes coverage` with no existing `bilan.json` automatically runs `qlnes audit` first, then prints the table. Behavior identical to FR22.
- **AC2.** `qlnes coverage` with a `bilan.json` whose `generated_at` predates any source mtime in `qlnes/**/*.py` emits a warning line `qlnes: warning: bilan.json is stale (...)` followed by the table. JSON payload `{"class":"bilan_stale", ...}`.
- **AC3.** `qlnes coverage --refresh` runs `audit` even if the bilan is fresh. Useful in CI.
- **AC4.** `qlnes coverage --strict` (with stale bilan) treats the warning as an error: exits 70 with `class: "bilan_stale"`. UX §11.7 sample session.
- **AC5.** With a *fresh* bilan, `qlnes coverage` reads in < 100 ms (NFR-PERF-4 verified by `tests/integration/test_coverage_perf.py`).

**Dev notes.**
- "Newest source mtime" is derived from `qlnes/**/*.py` plus `corpus/manifest.toml`. Test files don't count (their changes don't affect output).
- The auto-audit fallback runs without `--strict` by default; the user can pass `--strict` to escalate.

**Estimate.** **S** — 1 dev-day.

---

## 6. Epic C — Sara's NSF with per-track metadata

**User value.** Sara runs `qlnes nsf rom.nes --output ost.nsf`, loads the file in NSFPlay or GME, and sees each track's title, length, and fadeout — including the unreferenced composer demos. She uses the file unchanged in her video essay.

**FRs closed.** FR5 (NSF output, MVP scope: mapper-0 sample-equivalent + mapper-66 best-effort).

**Risks tracked.** R7 (NSF2 + NSFe player compatibility).

### Story C.1 — Emit a valid NSF2 file for one mapper-0 ROM

**User value.** Sara loads `ost.nsf` in NSFPlay and the playlist appears with the correct number of tracks, each playable, on a known-good mapper-0 FT ROM.

**FR(s) closed.** Partial FR5 (NSF2 base, no NSFe yet).

**NFR(s) touched.** NFR-REL-1 (deterministic NSF byte output for the same ROM).

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- `qlnes/nsf2.py` — NSF2 header (128 bytes, version byte `0x02`), PRG-payload assembly, mapper-0 layout (load/init/play vectors derived from the ROM).
- `cli.py::nsf` migrated to call `nsf2.write_nsf(...)` (the existing `qlnes/nsf.py` v1 path stays as a fallback for one release, then is deleted in C.4).

**Acceptance criteria.**
- **AC1.** `qlnes nsf <mapper-0-rom> --output ost.nsf` produces a file whose first 5 bytes are `NESM\x1a` and whose version byte (offset 0x05) is `0x02`.
- **AC2.** Loading `ost.nsf` in NSFPlay (or `gme_player`, our test harness) plays the first track without error. Verified by `tests/invariants/test_nsf_validity.py::test_gme_loads`.
- **AC3.** Two consecutive `qlnes nsf` runs on the same ROM produce byte-identical `.nsf` output.
- **AC4.** The NSF's INIT/PLAY/LOAD addresses are correctly derived from the ROM's reset vector and audio entry point (verified by inspecting the header bytes 0x08-0x0F).

**Dev notes.**
- For mapper-0, NSF banking is not used. PRG fits in 32 KB; load address is `$8000`.
- Existing `qlnes/nsf.py` (v1) is kept until C.4 to avoid regressing Sara's path during C.1's scaffold work. C.4 deletes it.

**Estimate.** **M** — 2–3 dev-days.

---

### Story C.2 — Embed NSFe metadata (titles, lengths, fadeout, author, playlist)

**User value.** Sara's NSF, loaded in NSFPlay, shows track titles like "Stage 1 — Forest" instead of "Track 01"; track lengths render correctly; the playlist order matches the song-pointer table, including unreferenced demos at the end.

**FR(s) closed.** Closes FR5 (NSF2 + NSFe complete).

**NFR(s) touched.** NFR-REL-1 (deterministic chunk encoding).

**Pre-conditions.** C.1.

**Embedded scaffolding.**
- `qlnes/nsf2.py` extended: NSFe chunk encoders for `tlbl` (track labels), `time` (per-track lengths in ms), `fade` (fadeout in ms), `auth` (author info), `plst` (playlist order).
- Chunk-write helpers route through `det.canonical_json` for any string-list payload (sorted byte order where applicable; `tlbl` order is meaningful, not sorted).

**Acceptance criteria.**
- **AC1.** Produced `.nsf` files contain at least 5 NSFe chunks (`tlbl`, `time`, `fade`, `auth`, `plst`). Verified by chunk-walking the file's tail.
- **AC2.** NSFPlay displays the track titles from `tlbl` correctly (manual verification recorded as a test fixture screenshot or via NSFPlay's CLI dump mode).
- **AC3.** GME-decoded track lengths match the `time` chunk values to the millisecond.
- **AC4.** Unreferenced songs (demos) are present in `plst` at the end of the playlist. Sara's UX §11.2 sample session works end-to-end.
- **AC5.** Track titles default to `Track NN` when the engine doesn't expose them; `tlbl` is always present (never empty).

**Dev notes.**
- NSFe spec: `NSF/NSFe` extension on NESdev wiki. Chunk format: `[len:4][fourcc:4][payload]`.
- Track titles: for FT, walk the engine's instrument-name table when present; otherwise default to `Track NN`. For Capcom, no per-track names are encoded — default applies.

**Estimate.** **M** — 2–3 dev-days.

---

### Story C.3 — Best-effort NSF for mapper-66 (and the experimental flag)

**User value.** Sara has a mapper-66 (GxROM) ROM whose audio she wants in NSF form. She passes `--experimental` and gets a best-effort NSF that loads in NSFPlay. The output is tagged in `bilan.json` as `partial` (not `pass`) so Lin's pipeline knows not to trust full equivalence here.

**FR(s) closed.** Partial FR5 (mapper-66 best-effort, experimental tier).

**NFR(s) touched.** NFR-REL-5 (crash-free even when degraded).

**Pre-conditions.** C.2, A.4.

**Embedded scaffolding.**
- `qlnes/nsf2.py::write_nsf` extended with the `experimental: bool = False` parameter (already declared in `cli.py::nsf` from the existing code; this story makes it functional for mapper-66).
- Mapper-66 NSF banking: NSF's own bank-switching at `$5FF8-$5FFF` mapped to mapper-66's PRG bank register.
- `bilan.json` `engines.<engine>` for mapper-66 audio gets `format: "nsf2+nsfe (experimental)"` and `status: "partial"` until full equivalence is verified.

**Acceptance criteria.**
- **AC1.** `qlnes nsf <mapper-66-rom> --output ost.nsf --experimental` produces an NSF2 file that loads in NSFPlay without error.
- **AC2.** Without `--experimental`, the same command exits 100 (`unsupported_mapper`) with hint to add `--experimental` if the user accepts best-effort.
- **AC3.** A mapper-1 (MMC1) ROM with `--experimental` exits 100 (one-shot per supported mapper; expanding the supported set is a Growth story per FR12).
- **AC4.** The mapper-66 NSF is tagged in any bilan.json that includes it under `partial`, never `pass`.

**Dev notes.**
- Mapper-66 is a tractable starting point because its bank-switching is single-register. MMC1, MMC3, VRC are non-trivial and stay out of MVP NSF scope.

**Estimate.** **M** — 2–3 dev-days.

---

### Story C.4 — Verify NSF compatibility with NSFPlay and GME, and remove legacy `nsf.py`

**User value.** A regression suite ensures Sara's path stays green. The codebase has one NSF writer, not two.

**FR(s) closed.** No new FR; closes the C epic by hardening + cleanup.

**NFR(s) touched.** NFR-REL-5 (crash-free verified by player-load tests).

**Pre-conditions.** C.1, C.2, C.3.

**Embedded scaffolding.**
- `tests/invariants/test_nsf_validity.py` — drives NSFPlay (CLI / dump mode) and GME (Python wrapper if available, or subprocess) and asserts both load every NSF in the corpus's NSF references.
- Delete `qlnes/nsf.py` (v1 writer); update `cli.py::nsf` import path.

**Acceptance criteria.**
- **AC1.** `tests/invariants/test_nsf_validity.py` parametrizes over every NSF reference in the corpus and asserts both NSFPlay and GME decode without error.
- **AC2.** Per-track playback duration in GME matches the `time` chunk values within ±50 ms.
- **AC3.** The legacy `qlnes/nsf.py` is deleted; `git grep -l 'qlnes.nsf '` returns no results.
- **AC4.** Existing tests that imported the old `nsf.py` are migrated.

**Dev notes.**
- GME (Game Music Emu) is C with various Python bindings (`pygme`, `nsfplay-py`, etc.). If none is reliable on Linux, fall back to subprocess `gme_player`.
- The "manual" NSFPlay verification is automatable via NSFPlay's dump mode (`-w` flag for WAV-out).

**Estimate.** **S** — 1 dev-day.

---

## 7. Epic D — Pipeline-grade CLI contract

**User value.** Lin replaces her broken-tool soup with one `subprocess.run(["qlnes", "audio", ...])` call and a JSON parser on the trailing stderr line. The exit codes, the JSON shape, the deterministic filenames, and the strict mode are reliable enough that her CI never sees a flaky `qlnes`.

**FRs closed.** FR27 (polish — multi-section TOML), FR28 (env-var coverage), FR29 (per-command sub-sections), FR30 (shell completion), FR37 (refuse-to-overwrite), FR38 (`--strict`), FR39 (non-TTY mode), FR40 (`--debug`).

### Story D.1 — Refuse to overwrite by default; `--force` to override

**User value.** Marco's pipeline can re-run `qlnes audio` against the same `--output` directory without silently clobbering yesterday's artifacts. Adding `--force` is an explicit opt-in.

**FR(s) closed.** FR37.

**NFR(s) touched.** NFR-REL-4 (atomic + refusal: no half-write OR overwrite without consent).

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- Pre-flight predicate `_check_output_writable(path, force=force)` — checks: parent dir exists & is writable, path itself does not exist OR `force` is set.
- `cli.py` adds `--force` flag (already in UX §4.3 inventory).

**Acceptance criteria.**
- **AC1.** `qlnes audio rom.nes --output tracks/` then re-run without changes exits 73 (`cant_create`) with `class: "cant_create"`, `cause: "exists"`, hint `Add --force, or pick a different --output path.` (UX §11.8).
- **AC2.** Adding `--force` overwrites cleanly. Two consecutive runs with `--force` produce byte-identical outputs (deterministic).
- **AC3.** `--force` does not bypass other pre-flight checks (e.g. doesn't make a non-writable dir suddenly writable). Verified by `test_cli_force.py`.
- **AC4.** For multi-file outputs (`--output tracks/`), the refusal triggers if *any* expected output file already exists. The error reports the first conflicting path.

**Dev notes.**
- The refusal must happen *before any byte is written*. Pre-flight is the only correct place.

**Estimate.** **S** — 1 dev-day.

---

### Story D.2 — `--strict`, `--no-progress`, `--no-hints`, `--color {auto,always,never}`

**User value.** Lin sets `QLNES_STRICT=1 QLNES_PROGRESS=0 QLNES_HINTS=0 QLNES_COLOR=never` in CI and gets the cleanest, machine-friendliest output qlnes can produce.

**FR(s) closed.** FR38 (`--strict`), FR39 (non-TTY mode — already detection-based; this story formalizes via `--no-progress`), partial FR40 prep (formal stderr cleanup).

**NFR(s) touched.** NFR-REL-1 (color stripping does not affect any artifact bytes).

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- `cli.py` adds `--strict`, `--no-progress`, `--no-hints`, `--color` flags.
- `qlnes/io/errors.py::emit` honors `--no-hints` and `--color`.
- A small TTY-detection module `qlnes/io/term.py` (~20 LOC) wraps `sys.stderr.isatty()` plus `NO_COLOR` env detection.
- Progress-bar machinery (likely a thin internal helper, no external dep) checks `cfg.progress and term.is_tty(stderr)`.

**Acceptance criteria.**
- **AC1.** `--strict` upgrades every warning to an error with the appropriate exit code (default 70, except where a more specific code applies; see UX §6.5).
- **AC2.** `--no-progress` silences all progress animations even in TTY mode; per-step `→` log lines remain visible.
- **AC3.** `--no-hints` strips the `hint:` line from every error/warning. JSON line still emitted.
- **AC4.** `--color never` strips ANSI escapes from every line of output. `--color always` emits ANSI escapes even when piped. `--color auto` is the default.
- **AC5.** `NO_COLOR=1` env var has the same effect as `--color never` (industry convention). `--color always` overrides it (explicit > implicit).
- **AC6.** All four flags are also exposed via `QLNES_STRICT`, `QLNES_PROGRESS`, `QLNES_HINTS`, `QLNES_COLOR` env vars (FR28).

**Dev notes.**
- The progress-bar helper is intentionally simple: `\r`-based redraw, ASCII `[####    ] 47% ETA 12s`. No `tqdm` dep — keeps wheel small.
- `--debug` interaction with `--quiet`: mutually exclusive (UX §4.3); enforced in cli.py with a Typer callback.

**Estimate.** **M** — 2–3 dev-days.

---

### Story D.3 — `--debug` adds resolved config, per-step timings, full tracebacks

**User value.** When something goes wrong, Marco re-runs with `--debug`, gets the full picture (resolved config, per-step timing, Python traceback), files an issue with the dump.

**FR(s) closed.** FR40 (debug mode).

**NFR(s) touched.** None directly; debug output is non-deterministic by definition.

**Pre-conditions.** D.2.

**Embedded scaffolding.**
- `cli.py` adds `--debug` flag.
- `qlnes/io/errors.py::emit` checks `--debug` to pass `from_exception` traceback through.
- A `qlnes/io/timing.py` helper providing `with timed_step("rendering audio"): ...` context manager that emits `debug: rendering audio (1.3s)` lines.
- ConfigLoader exposes `provenance` for `--debug` to dump.

**Acceptance criteria.**
- **AC1.** `--debug` prints `debug:`-prefixed lines to stderr, dimmed when color is on.
- **AC2.** On any error under `--debug`, the full Python traceback follows the JSON payload line, prefixed `debug: traceback:`.
- **AC3.** Without `--debug`, internal-error tracebacks are *suppressed* from stderr (UX §6.1). The `internal_error` JSON payload is still emitted.
- **AC4.** `--debug` and `--quiet` together exit 64 (`usage_error`, `--quiet and --debug are mutually exclusive`).
- **AC5.** `--debug` resolved-config dump shows each key + the layer that set it (DEFAULT / TOML / ENV / CLI).

**Dev notes.**
- The traceback dump uses `traceback.format_exception` for Python 3.11+'s fine-grained errors.
- `timed_step` does not emit anything outside `--debug` mode (zero overhead in production).

**Estimate.** **S** — 1 dev-day.

---

### Story D.4 — Layered config + env vars + per-command sections

**User value.** Marco/Sara/Lin can each choose their level of customization: hardcoded defaults, a project-level `qlnes.toml`, environment variables (CI), or per-invocation flags. Each layer overrides the previous.

**FR(s) closed.** FR27 (full 4-layer model), FR28 (env-var coverage), FR29 (per-command sub-sections honored by `audio`, `verify`, `audit`, `coverage`).

**NFR(s) touched.** NFR-REL-1 (config resolution is deterministic given the same inputs).

**Pre-conditions.** A.1 (introduced minimal loader), B.1, B.2.

**Embedded scaffolding.**
- `qlnes/config/loader.py` — full schema covering `[default]`, `[audio]`, `[verify]`, `[audit]`, `[coverage]` sections (locked in UX §4.4).
- Unknown-key warning under default mode; error under `--strict`.
- Env-var resolution: `QLNES_<SECTION>_<KEY>` for sub-section keys (e.g. `QLNES_AUDIO_FORMAT`); `QLNES_<KEY>` for `[default]` keys.
- `qlnes.toml.example` shipped at repo root with the canonical schema.

**Acceptance criteria.**
- **AC1.** `qlnes audio rom.nes` with `qlnes.toml` containing `[audio] format = "mp3"` honors the TOML and produces MP3 output. Adding `--format wav` overrides.
- **AC2.** `QLNES_AUDIO_FORMAT=mp3 qlnes audio rom.nes` produces MP3. Both flag and TOML present: flag wins.
- **AC3.** `qlnes audit` honors `[audit] corpus_dir = "./alt-corpus"` from `qlnes.toml`.
- **AC4.** `qlnes coverage` honors `[coverage] format = "json"` from `qlnes.toml`.
- **AC5.** Unknown TOML key (`[audio] formaat = "wav"`, typo) emits a warning by default, exits 70 under `--strict` with `class: "internal_error"` and `extra.detail: "unknown_config_key"`.
- **AC6.** `--config <path>` overrides TOML discovery. With no `--config`, `$PWD/qlnes.toml` is tried first, then the ROM's parent directory (UX §4.2).

**Dev notes.**
- `tomllib` is stdlib in 3.11+; no `tomli` shim needed.
- The unknown-key warning uses the same `qlnes/io/errors.py::warn` helper that B.5 introduces (or this story introduces if B.5 hasn't merged yet).

**Estimate.** **M** — 2–3 dev-days.

---

### Story D.5 — Install shell completion (bash, zsh, fish, PowerShell)

**User value.** Marco runs `qlnes --install-completion zsh`, restarts his shell, and gets tab-completion on commands, flags, and enum values.

**FR(s) closed.** FR30.

**NFR(s) touched.** NFR-PORT-1 (Linux canonical — completion install paths verified on Ubuntu 22.04).

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- Flip `add_completion=False` to `True` in `qlnes/cli.py::app` initialization. Typer auto-wires the rest.
- Document the install procedure in README.

**Acceptance criteria.**
- **AC1.** `qlnes --install-completion bash` installs the completion snippet into the canonical location and prints a success line on stderr.
- **AC2.** After completion install + shell reload, `qlnes <TAB>` lists all commands; `qlnes audio --<TAB>` lists all flags; `qlnes audio --format <TAB>` lists `wav`, `mp3`, `nsf`.
- **AC3.** Same for zsh, fish, PowerShell. Verified manually + a test that confirms `--install-completion` exits 0 on each shell name.
- **AC4.** A read-only host (e.g. immutable container) makes `--install-completion` exit 73 (`cant_create`) with hint pointing at the manual install path.

**Dev notes.**
- This is Typer's built-in mechanism. Our work is mostly verification + README.
- Mapper-aware completion (`qlnes coverage --mapper <TAB>` from live bilan) is deferred to Growth — UX §13 open question 5.

**Estimate.** **S** — 1 dev-day.

---

## 8. Epic E — Regression net for existing features

**User value.** As epics A–D land, the existing capabilities (`analyze`, `recompile`, `verify` round-trip, asset extraction, dynamic discovery) keep working. A maintainer-confidence net.

**FRs closed.** None (the FRs are `[Existing]` and were closed before this PRD). This epic *prevents regression*.

**Risks tracked.** R9 (mapper-66 audio regress).

### Story E.1 — Migrate existing tests into the unit/integration/invariants layout

**User value.** A new contributor can find tests in a predictable place and the test runner gives signal proportional to risk.

**FR(s) closed.** None (refactor + safety).

**NFR(s) touched.** None directly.

**Pre-conditions.** A.1.

**Embedded scaffolding.**
- Move existing `tests/test_*.py` files into `tests/unit/` or `tests/invariants/` per the architecture's layout (step 6).
- Add `tests/conftest.py` with shared fixtures (corpus loader, lameenc-version skip marker, oracle fixture).
- Update CI workflow paths.

**Acceptance criteria.**
- **AC1.** `pytest tests/unit` runs in under 30 seconds and excludes corpus-dependent tests.
- **AC2.** `pytest tests/integration` runs in under 5 minutes and uses one or two corpus ROMs.
- **AC3.** `pytest tests/invariants` runs the full corpus and is the only suite that depends on FCEUX subprocess.
- **AC4.** Every existing test (`test_basic.py`, `test_dataflow.py`, `test_engines_assets.py`, `test_emulator.py`, `test_real_rom.py`, etc.) continues to pass after migration.

**Dev notes.**
- This is a low-risk move. The tests don't change behaviorally; only their location does. CI workflow's `pytest tests/` becomes `pytest tests/unit tests/integration` for PR runs.

**Estimate.** **S** — 1 dev-day.

---

### Story E.2 — Lock down round-trip and asset-extraction tests

**User value.** `qlnes analyze`, `qlnes recompile`, `qlnes verify` (round-trip), and `qlnes analyze --assets` keep their byte-identical guarantees as the audio pipeline lands.

**FR(s) closed.** No new FR; protects FR1, FR2, FR3, FR4, FR13, FR14, FR17.

**NFR(s) touched.** NFR-REL-1 (existing round-trip is byte-identical).

**Pre-conditions.** E.1.

**Embedded scaffolding.**
- `tests/invariants/test_round_trip.py` — parametrize over a small corpus; for each ROM, run `analyze` then `recompile` and assert byte-equality vs the original.
- `tests/invariants/test_asset_extraction.py` — parametrize; assert PNG outputs from `analyze --assets` are byte-identical across runs (NFR-REL-1) and free of host metadata (NFR-REL-2).

**Acceptance criteria.**
- **AC1.** Round-trip test passes on the existing `test_real_rom.py` corpus subset (already covered, this story formalizes).
- **AC2.** Asset PNGs from `analyze --assets` contain no `tIME` or `tEXt` chunks with host info (Pillow can leak these unless we strip).
- **AC3.** Two `analyze --assets` runs produce byte-identical PNGs (NFR-REL-1, NFR-REL-3 implied).

**Dev notes.**
- The Pillow PNG-metadata stripping is one line: `image.save(path, pnginfo=PngInfo())` where `PngInfo()` is empty. Document this as the only correct call pattern in `qlnes/assets.py`.

**Estimate.** **S** — 1 dev-day.

---

### Story E.3 — Confirm cynes-feature-gating still degrades gracefully

**User value.** A user without `cynes` installed (or whose `cynes` has been broken by an upstream change) still gets `qlnes analyze` working, just without the dynamic-discovery uplift.

**FR(s) closed.** No new FR; protects FR4 (existing).

**NFR(s) touched.** NFR-DEP-1 (FCEUX is the only hard external — `cynes` is feature-gated, must remain so).

**Pre-conditions.** E.1.

**Embedded scaffolding.**
- `tests/integration/test_no_cynes.py` — runs `qlnes analyze` in a venv where `cynes` is *not* installed (or with `cynes` mocked-import-error) and asserts the command succeeds without dynamic-discovery output.

**Acceptance criteria.**
- **AC1.** `qlnes analyze rom.nes` in a no-cynes environment exits 0 and emits `→ discovery dynamique : ignorée (cynes non installé)`.
- **AC2.** Same command in a no-cynes environment with `--no-dynamic` is a no-op for the cynes path (no different from no-cynes alone).
- **AC3.** Static analysis (FR1–FR3) is unaffected.

**Dev notes.**
- The existing `_have_cynes()` helper in `cli.py` is the gate. This story's only change is a CI-side test asserting the gate behaves.

**Estimate.** **S** — 1 dev-day.

---

## 9. Story Dependency Graph

```
                                ┌──────────┐
                                │   A.1    │  cross-cutting + APU + FT + WAV
                                └────┬─────┘
                ┌──────────┬─────────┼─────────┬──────────┬──────────┐
                ▼          ▼         ▼         ▼          ▼          ▼
              A.2        A.3       A.4       B.1        C.1        D.1
              MP3       loops    Capcom    audit-1    NSF2-base   refuse-overwrite
                                   │         │
                                   ▼         ▼
                                  A.5       B.2
                                  generic   coverage table
                                   │         │
                                   ▼         ├──────────────────┐
                                  A.6        ▼                  ▼
                                  verify   B.3                 D.4
                                   │       corpus & gen-refs   layered config
                                           │
                                           ▼
                                          B.4
                                          full audit + gate
                                           │
                                           ▼
                                          B.5
                                          stale + refresh

         C.1 ─→ C.2 ─→ C.3 (mapper-66) ─→ C.4 (cleanup)
         A.1 ─→ D.1, D.2 ─→ D.3, D.4 ─→ D.5
         A.1 ─→ E.1 ─→ E.2, E.3   (E branch fully parallel with A–D)
```

**Critical path** (longest sequence):

```
A.1 → A.4 → A.5 → B.3 → B.4 → B.5
```

Six stories deep; ~3–4 weeks if sequential. Parallelism (epic C alongside, epic D after A.1) brings total to ~7–8 weeks.

---

## 10. FR Coverage Matrix (28 / 28 MVP FRs)

| FR | Description (one line) | Story |
|---|---|---|
| FR5 | NSF output | C.1, C.2, C.3 |
| FR6 | WAV per-track output | A.1, A.3 |
| FR7 | MP3 per-track output | A.2 |
| FR8 | `--format {wav,mp3,nsf}` flag | A.1 (wav), A.2 (mp3), C.1 (nsf) |
| FR9 | Deterministic per-track filenames | A.1 |
| FR10 | Exhaustive song-table walk (incl. unreferenced) | A.1, A.4, A.5 (tier-2 limitation) |
| FR11 | Tier-1 sample-eq for recognized engine + tier-2 frame-acc | A.1 (FT), A.4 (Capcom), A.5 (generic) |
| FR18 | `qlnes verify --audio` per-ROM | A.6 |
| FR19 | `qlnes audit` writes `bilan.json` | B.1, B.4 |
| FR20 | Audit refuses without FCEUX references (exit 102) | B.1 |
| FR21 | `qlnes coverage` table + JSON | B.2 |
| FR22 | Auto-audit if bilan absent / schema-invalid | B.5 |
| FR23 | Stale-bilan warning | B.5 |
| FR24 | `coverage --refresh` | B.5 |
| FR25 | Bilan engine sub-map (incl. synthetic `unknown`) | B.1, B.2, A.5 |
| FR26 | 100% release gate via corpus | B.4 |
| FR27 | 4-layer config | A.1 (minimal), D.4 (full) |
| FR28 | Every TOML/env value also a CLI flag | D.4 |
| FR29 | Per-command sub-sections honored | D.4 |
| FR30 | Shell completion (`--install-completion`) | D.5 |
| FR33 | Sysexits-aligned exit codes | A.1 |
| FR34 | Structured JSON `stderr` | A.1 |
| FR35 | Atomic writes | A.1 |
| FR36 | Pre-flight validation | A.1 (minimal), D.1 (refuse-overwrite), D.2 (TTY checks) |
| FR37 | Refuse-to-overwrite by default | D.1 |
| FR38 | `--strict` | D.2 |
| FR39 | Non-TTY mode (no progress bars/prompts) | D.2 |
| FR40 | `--debug` | D.3 |

**Coverage:** 28 / 28 MVP FRs explicitly mapped. **No FR is orphaned.**

### Existing-tier FRs (validated, not closed by this MVP)

| FR | Story (validation only) |
|---|---|
| FR1 | E.2 (round-trip + analyze regression net) |
| FR2 | E.2 |
| FR3 | E.2 |
| FR4 | E.3 (cynes feature-gating) |
| FR13 | E.2 |
| FR14 | E.2 |
| FR17 | E.2 |

### Out-of-MVP FRs (deferred — see §12)

| FR | Tier | Notes |
|---|---|---|
| FR12 | Growth | Per-engine coverage extension beyond MVP-2 engines. |
| FR15 | Growth | PNG ↔ CHR-ROM round-trip. |
| FR16 | Vision | Gameplay data tables (drop tables, RNG seeds, AI scripts). |
| FR31 | Growth | `pip install qlnes`. |
| FR32 | Vision | `qlnes shell <rom>` REPL. |

---

## 11. NFR Touch Points (per story)

| NFR | Story / mechanism |
|---|---|
| NFR-PERF-1 (`analyze` < 2 s) | E.2 (existing perf preserved) |
| NFR-PERF-2 (audio ≤ 2× real time) | A.1 (perf budget AC), A.2, A.4 |
| NFR-PERF-3 (audit < 30 min on 50-ROM) | B.4 (parallel ProcessPoolExecutor) |
| NFR-PERF-4 (coverage read < 100 ms) | B.2, B.5 |
| NFR-PERF-5 (peak RAM < 500 MB) | A.1 (chunked PCM emission), B.4 (per-ROM job isolation) |
| NFR-REL-1 (byte-identical PCM) | A.1, A.4 (tier-1 promise); B.1 (canonical JSON in bilan) |
| NFR-REL-2 (no wall-clock in artifacts) | A.1 (test_no_wallclock_in_artifact), E.2 (PNG metadata strip) |
| NFR-REL-3 (deterministic parallelism) | B.4 (audit aggregation sorted by sha) |
| NFR-REL-4 (atomic writes) | A.1 (test_atomic_kill), D.1 (refuse-to-overwrite as the partner invariant) |
| NFR-REL-5 (crash-free on supported corpus) | B.4 (release gate); C.4 (NSF player verification) |
| NFR-PORT-1 (Linux canonical) | All stories tested on Ubuntu 22.04 in CI |
| NFR-PORT-2 (macOS Growth) | Deferred |
| NFR-PORT-3 (Windows deferred) | Deferred |
| NFR-PORT-4 (Python ≥ 3.11) | `requirements.txt` floor + CI matrix |
| NFR-DEP-1 (FCEUX only hard external) | E.3 (cynes feature-gating), A.2 (lameenc as Python wheel, not system dep) |
| NFR-DEP-2 (`requirements.txt` floor-pinned, lameenc `==`) | A.2, D.4 (deptry CI) |
| NFR-DEP-3 (new hard external requires PRD update) | Process — not a story |

**Coverage:** 18 / 18 NFRs mapped to at least one story or to a deferred / process gate.

---

## 12. Sprint Sequencing (recommendation for `bmad-sprint-planning`)

The sequencing below is *suggestion-grade*; SP refines. The critical path is A.1 → A.4 → A.5 → B.3 → B.4 → B.5.

### Sprint 1 (~1 week) — "First WAV"

- A.1 — Render one mapper-0 FT ROM to sample-equivalent WAV.
- E.1 — Migrate existing tests into the new layout. *(Parallel — different files)*

**Outcome.** `qlnes audio rom.nes --format wav --output tracks/` works for one ROM. Cross-cutting scaffold in place.

### Sprint 2 (~1 week) — "Format & loop fidelity"

- A.2 — MP3 via lameenc.
- A.3 — Loop-aware WAV `'smpl'` chunks.
- D.1 — Refuse-to-overwrite (small story, easy to slot here).

**Outcome.** Marco's J1 happy path works for one engine, both formats, with proper loops and overwrite safety.

### Sprint 3 (~1 week) — "Capcom + generic"

- A.4 — Capcom engine.
- A.5 — Generic fallback.

**Outcome.** Two recognized engines + universal fallback. Closes FR11 fully.

### Sprint 4 (~1 week) — "Coverage matrix"

- B.1 — Audit-one-ROM + bilan schema.
- B.2 — `coverage` table + JSON.
- A.6 — `qlnes verify --audio` (small).

**Outcome.** Lin can `qlnes coverage --format json | jq` to discover what works. Marco can verify per-ROM.

### Sprint 5 (~1 week) — "Corpus & release gate"

- B.3 — Corpus manifest + `generate_references.py`.
- B.4 — Full audit + parallelism + release gate.
- B.5 — Stale + refresh.

**Outcome.** `bilan.json` is committed and gates releases. NFR-PERF-3 satisfied.

### Sprint 6 (~1 week) — "NSF for Sara"

- C.1 — NSF2 base for mapper-0.
- C.2 — NSFe metadata.
- C.3 — Mapper-66 best-effort.

**Outcome.** Sara's J2 happy path works.

### Sprint 7 (~1 week) — "Pipeline polish"

- D.2 — `--strict`, `--no-progress`, `--no-hints`, `--color`.
- D.3 — `--debug`.
- D.4 — Full layered config + env vars + per-command sections.
- D.5 — Shell completion.
- C.4 — NSF player-validity tests + remove legacy `nsf.py`.

**Outcome.** Lin's J3 contract fully satisfied. Polish + cleanup.

### Sprint 8 (~3 days) — "Hardening before tag"

- E.2 — Round-trip / asset regression net.
- E.3 — Cynes feature-gating verification.
- Tag `v0.5.0` (MVP exit).

**Outcome.** Release candidate. `audit.yml` runs on tag, produces the canonical `bilan.json` for v0.5.0, attached to the release.

### Total: ~8 weeks for solo developer

Confidence band: ±30%. Dominant uncertainty in A.4 (Capcom RE) and B.3 (corpus-side IP coordination).

---

## 13. Out-of-MVP Deferral

### Growth (post-MVP, pre-v1)

- **FR12** — Per-engine coverage extension (Konami KGen, Sunsoft 5B, Namco 163, …).
- **FR15** — PNG ↔ CHR-ROM round-trip.
- **FR31** — `pip install qlnes` (`pyproject.toml` migration).
- **macOS portability** (NFR-PORT-2).
- **`--explain-config` flag** (UX §13, open question 3).
- **`--rename-by-hash` flag** (UX §13, open question 4).
- **Mapper-aware completion** (UX §13, open question 5).
- **Coverage matrix as auto-rendered README badge** (UX §13, open question 2).
- **DMC channel full implementation** (architecture step 8 — DMC stub in MVP, full in Growth, ADR-18).
- **Expansion-audio mappers** (MMC5, VRC6) for both audio rendering and NSF emission.

### Vision (v1+)

- **FR16** — Gameplay data tables (drop tables, RNG seeds, AI scripts).
- **FR32** — `qlnes shell <rom>` interactive REPL.
- **Public Python API** (currently explicitly NOT a stable surface — UX P4, ADR-20). May ship as a separate paid offering per PRD §169.
- **Windows portability** (NFR-PORT-3).

These items are intentionally not stories in this document. They appear here only to confirm the MVP boundary is sharp.

---

## 14. Sign-off

This document is complete and ready to feed `bmad-sprint-planning` (SP).

### What this document delivers

- **5 epics** structured by user outcome, not technical milestones.
- **23 stories**, each a vertical slice with embedded scaffolding rather than a separate technical-milestone story.
- **Acceptance criteria** for every story, testable at the CLI surface or at `bilan.json`.
- **Story dependency graph** as a DAG with one critical path (6 stories deep).
- **FR coverage** at 28 / 28 MVP FRs — no orphan.
- **NFR coverage** at 18 / 18 NFRs — every NFR has a story or a process gate.
- **Sprint sequencing** suggestion for ~8 weeks solo.
- **Out-of-MVP deferral** explicit (Growth / Vision separation per PRD).

### Acceptance criteria for `bmad-check-implementation-readiness` (next pass)

The next readiness check (`IR`) should now produce real findings instead of the structural N/As of the 2026-05-03 first pass:

- ✓ Architecture exists (`architecture.md`, 1759 lines, all 19 steps complete).
- ✓ UX design exists (`ux-design.md`, 895 lines, all 12 steps complete).
- ✓ Epics & stories exist (this file, 23 stories).
- ✓ Every PRD MVP FR maps to ≥ 1 story (§10 above).
- ✓ Every PRD NFR maps to ≥ 1 verification mechanism (§11 above).
- ✓ Story dependency graph is a DAG (§9 above).
- ✓ No technical-milestone epic; every story title is a user-value verb (§2 enforcement).

### Epic-quality re-check against readiness-report guidance

| Pre-emptive guidance item | This doc's compliance |
|---|---|
| No technical-milestone epics | ✓ Five epics titled by user outcome (Get music…, Trustworthy coverage, Sara's NSF, Pipeline-grade, Regression net) |
| No forward dependencies | ✓ DAG verified §9; only edge into A is the brownfield baseline; B/C/D/E only depend on A.1's scaffold |
| Each story user-visible | ✓ Every story title starts with a user-value verb; no story is purely "Add module X" |
| Vertical slices | ✓ Cross-cutting modules embedded inside the first user-value story that exercises them (A.1) |
| Test-corpus + FCEUX references early | ✓ B.3 lands the corpus + reference-generation script; epic A consumes corpus from A.4 onwards |
| IP question for corpus before publishing | ✓ B.3 includes `corpus/README.md`, `NOTICE.md`, `.gitignore` for `corpus/roms/`+`corpus/references/` |

### Next BMad action

**Run `bmad-check-implementation-readiness` (IR)** for a real coverage audit (steps 3 and 5 of the readiness skill will now produce findings instead of structural N/A).

If `IR` returns ✓, proceed to **`bmad-sprint-planning` (SP)** to generate the sprint backlog using the 8-sprint suggestion above as a starting point. SP's output then drives the per-story `bmad-create-story` (CS) → `bmad-dev-story` (DS) → `bmad-code-review` (CR) cycle.

---

*End of Epics & Stories Document — qlnes Music-MVP (v1, 2026-05-03)*
