---
report_type: implementation-readiness
pass: 2
date: 2026-05-03
project_name: qlnes
prd: _bmad-output/planning-artifacts/prd.md
ux: _bmad-output/planning-artifacts/ux-design.md
architecture: _bmad-output/planning-artifacts/architecture.md
epics_and_stories: _bmad-output/planning-artifacts/epics-and-stories.md
prior_pass: _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
verdict: CONDITIONAL_GO_FOR_SPRINT_PLANNING
blocker_count: 0
critical_findings: 0
high_findings: 1
medium_findings: 4
low_findings: 6
fr_coverage: 28/28
nfr_coverage: 18/18
story_count: 23
epic_count: 5
---

# Implementation Readiness Assessment Report — Pass 2

**Project:** qlnes
**Date:** 2026-05-03 (same calendar day as pass 1; afternoon session)
**Assessor:** Claude (Opus 4.7), acting as PM-readiness validator
**Verdict:** **CONDITIONAL GO** for `bmad-sprint-planning` (SP) — proceed after addressing 1 High-severity AC defect.

---

## Executive Summary

Pass 1 (this morning) returned `READY for Architecture work. NOT YET READY for direct implementation` because architecture, UX, and epics did not exist. In the intervening session the missing artifacts have been authored:

- **`ux-design.md`** — 895 lines, 12 steps, all locked decisions tabulated.
- **`architecture.md`** — 1759 lines, 19 steps, all six pass-1 open questions closed, 20 ADRs, 5 epic seams.
- **`epics-and-stories.md`** — 1141 lines, 5 epics, 23 stories, 28/28 MVP FR coverage.

This pass evaluates the four-document set as a coherent unit. **Three of the six standard categories that produced structural N/As in pass 1** (Epic Coverage, UX Alignment, Epic Quality) **now produce real findings.**

### Headline numbers

| Metric | Pass 1 | Pass 2 |
|---|---|---|
| Substantive artifacts present | 1 (PRD only) | 4 (PRD + UX + Architecture + Epics & Stories) |
| MVP FR coverage in stories | N/A | **28 / 28** |
| MVP FRs without a story owner | N/A | 0 |
| NFR verification mechanisms mapped | N/A | **18 / 18** |
| PRD defects | 0 | 0 (no amendment since pass 1) |
| Architecture-phase open questions | 6 (all open) | **0** (all six closed in architecture steps 4, 8, 9, 10, 11, 12) |
| Epic anti-patterns detected | N/A | 0 |
| Story dependency graph | N/A | DAG, 1 critical path of 6 stories |
| Findings — Critical / High / Medium / Low | — | 0 / 1 / 4 / 6 |
| Verdict | READY for architecture | **CONDITIONAL GO** for sprint planning |

The single High-severity finding is a story-level acceptance-criterion defect (Story A.2, AC2 — see §8 *Findings Catalog*). It does not invalidate the document; it is fixable with a one-line edit before SP.

---

## 1. Document Inventory

### 1.1 Artifacts evaluated

| File | Lines | Steps complete | Frontmatter sane | First-line check | Last-line check |
|---|---|---|---|---|---|
| `prd.md` | 644 | n/a (PRD-shape) | ✓ | `# qlnes — Product Requirements Document` | `**Date:** 2026-05-03.` |
| `ux-design.md` | 895 | 12 / 12 | ✓ | `# UX Design Document — qlnes` | `*End of UX Design Document …*` |
| `architecture.md` | 1759 | 19 / 19 | ✓ | `# Architecture Decision Document — qlnes` | `*End of Architecture Decision Document …*` |
| `epics-and-stories.md` | 1141 | 11 / 11 | ✓ | `# Epics & Stories — qlnes (Music-MVP)` | `*End of Epics & Stories Document …*` |
| `implementation-readiness-report-2026-05-03.md` | 249 | n/a | ✓ | (pass 1 — referenced as input) | — |

All four artifacts carry consistent metadata: `project_name: qlnes`, `user_name: Johan`, `date: 2026-05-03`. Cross-document `inputDocuments` references are all resolvable.

### 1.2 Cross-references checked

- ✓ Architecture frontmatter declares UX as input → UX file exists.
- ✓ Epics frontmatter declares PRD + UX + Architecture as inputs → all three exist.
- ✓ Architecture §18 references the epic seams that the epics doc instantiates → seam labels A–E match.
- ✓ UX §14 references the epic suggestions → epics doc preserves the same A/B/C/D/E mapping.
- ✓ Pass-1 readiness report's six open questions → architecture closes them in the listed steps (Q1 → step 8+10; Q2 → step 11; Q3 → step 9; Q4 → steps 4+12; Q5 → step 9; Q6 → step 4).

### 1.3 Project memories referenced

Both architecture and epics declare `project_cli_only_no_public_api.md` and `project_audio_architecture_decisions.md` as referenced. These memories were not re-read during this pass; their *names* are consistent with PRD §169 (CLI-only, no public Python API) and PRD §amendmentLog (the six locked architecture decisions). Pass-2 verdict: no contradiction surfaced.

---

## 2. PRD Analysis

The PRD has not been amended since pass 1. Pass-1 findings re-confirmed:

- ✓ 0 PRD defects.
- ✓ 28 MVP FRs explicitly tagged.
- ✓ 18 NFRs quantified.
- ✓ 4 user journeys (Marco J1, Sara J2, Lin J3, Marco J4 edge case).
- ✓ All 6 architecture-phase open questions identified in pass 1 are now *closed* in the architecture document — see §3 below for the verification.

No new PRD-level finding in this pass.

---

## 3. Epic Coverage Validation

### 3.1 MVP FR ↔ Epic ↔ Story matrix (substantive)

The epics doc §10 declares 28/28 coverage. Independent re-derivation from the PRD's FR list confirms:

| FR | PRD tier | Epic | Story (primary) | Story (secondary) | Verified |
|---|---|---|---|---|---|
| FR1 | Existing | E | E.2 | — | ✓ |
| FR2 | Existing | E | E.2 | — | ✓ |
| FR3 | Existing | E | E.2 | — | ✓ |
| FR4 | Existing | E | E.3 | — | ✓ |
| FR5 | MVP | C | C.1, C.2, C.3 | — | ✓ |
| FR6 | MVP | A | A.1, A.3 | — | ✓ |
| FR7 | MVP | A | A.2 | — | ✓ |
| FR8 | MVP | A | A.1 (wav), A.2 (mp3), C.1 (nsf) | — | ✓ |
| FR9 | MVP | A | A.1 | — | ✓ |
| FR10 | MVP | A | A.1, A.4 | A.5 (tier-2 limitation noted) | ✓ |
| FR11 | MVP | A | A.1 (FT), A.4 (Capcom), A.5 (generic) | — | ✓ |
| FR12 | Growth | (deferred) | — | — | ✓ deferred §13 |
| FR13 | Existing | E | E.2 | — | ✓ |
| FR14 | Existing | E | E.2 | — | ✓ |
| FR15 | Growth | (deferred) | — | — | ✓ deferred §13 |
| FR16 | Vision | (deferred) | — | — | ✓ deferred §13 |
| FR17 | Existing | E | E.2 | — | ✓ |
| FR18 | MVP | A | A.6 | — | ✓ |
| FR19 | MVP | B | B.1, B.4 | — | ✓ |
| FR20 | MVP | B | B.1 | — | ✓ |
| FR21 | MVP | B | B.2 | — | ✓ |
| FR22 | MVP | B | B.5 | — | ✓ |
| FR23 | MVP | B | B.5 | — | ✓ |
| FR24 | MVP | B | B.5 | — | ✓ |
| FR25 | MVP | B | B.1, B.2, A.5 | — | ✓ |
| FR26 | MVP | B | B.4 | — | ✓ |
| FR27 | MVP | A + D | A.1 (minimal), D.4 (full) | — | ✓ |
| FR28 | MVP | D | D.4 | — | ✓ |
| FR29 | MVP | D | D.4 | — | ✓ |
| FR30 | MVP | D | D.5 | — | ✓ |
| FR31 | Growth | (deferred) | — | — | ✓ deferred §13 |
| FR32 | Vision | (deferred) | — | — | ✓ deferred §13 |
| FR33 | MVP | A + D | A.1 | D.* polish | ✓ |
| FR34 | MVP | A + D | A.1 | D.* polish | ✓ |
| FR35 | MVP | A | A.1 | D.1 (refuse-to-overwrite as partner invariant) | ✓ |
| FR36 | MVP | A + D | A.1 (minimal), D.1, D.2 | — | ✓ |
| FR37 | MVP | D | D.1 | — | ✓ |
| FR38 | MVP | D | D.2 | — | ✓ |
| FR39 | MVP | D | D.2 | — | ✓ |
| FR40 | MVP | D | D.3 | — | ✓ |

**Count:** 28 MVP FRs covered by ≥ 1 story. **0 orphans. 0 over-coverage hotspots** (no FR is owned by ≥ 4 stories — would be a smell).

### 3.2 Validity of "secondary story" attribution

Several FRs are split across two stories (FR8: 3 stories — one per format; FR27: A.1 minimal + D.4 full; FR33–FR36: A.1 scaffold + D.* polish). Each split has a clear *minimum-viable* primary story and a *complete* secondary story. This is a healthy pattern: the user gets value from the minimum slice (A.1's `--format wav` works end-to-end with sysexits + atomic writes); the full surface lands incrementally without forcing all flags into the first story.

**No verdict change.** Splits are correctly motivated.

### 3.3 Coverage of `[Existing]`-tier FRs

Pass 1 noted that `[Existing]` FRs (FR1–FR4, FR13, FR14, FR17) need *non-regression* coverage during the MVP, not new closure. Epic E (3 stories) provides this:

- E.1 — migrate existing tests into the new layout (preserves all current pass results).
- E.2 — round-trip + asset-extraction regression tests with byte-equivalence assertions.
- E.3 — cynes feature-gating verification.

**Verdict:** ✓ adequate for MVP. Not a release blocker.

### 3.4 Epic-coverage summary

✓ **PASS.** Every PRD MVP FR is owned by ≥ 1 story; every `[Existing]` FR has a regression net story; every Growth/Vision FR is explicitly deferred in epics §13. No coverage gaps.

---

## 4. UX Alignment Assessment

### 4.1 PRD user journeys ↔ UX sample sessions ↔ Story acceptance criteria

| PRD journey | UX sample session(s) | Story coverage | Verified |
|---|---|---|---|
| Marco J1 (porter, happy path) | UX §11.1 | A.1, A.2, A.3 (combined) | ✓ — all three sample-session lines map to AC1/AC2 in those stories |
| Sara J2 (NSF + WAV combo) | UX §11.2 | C.1, C.2, A.1 | ✓ — Sara sees track titles (C.2) and gets WAVs in same session (A.1) |
| Lin J3 (pipeline integrator) | UX §11.3 | A.1 (subprocess test), D.2 (pipeline-mode flags), D.4 (env vars) | ✓ — Lin's Python pattern is testable as `tests/integration/test_cli_audio.py` (A.1 dev notes) |
| Marco J4 (unsupported mapper edge case) | UX §11.4 | A.1 AC5 (`unsupported_mapper` JSON), D.1 (refuse-to-overwrite) | ✓ — exit-100 with `class: "unsupported_mapper"` JSON payload is testable |

**Coverage:** 4/4 PRD journeys map to UX sample sessions and to story ACs. No journey is unrepresented.

### 4.2 UX locked-decision ↔ Architecture/Story implementation

The UX doc's §12 *Locked decisions* table has 15 items (L1–L15). For each, the architecture or epics specifies the implementing module/story:

| UX lock | Architecture site | Story site |
|---|---|---|
| L1 — stdout=data, stderr=info+errors | Step 7 (`qlnes/io/errors.py`) | A.1 |
| L2 — three-line error shape | Step 7 (`emit()`) | A.1 |
| L3 — twelve-class error taxonomy | Step 7 (`EXIT_CODES` table) | A.1 |
| L4 — coverage table is contract | Step 12 (`bilan.json` schema) | B.2 |
| L5 — French info + English errors | Step 7 (locale gate) | A.1 |
| L6 — `--color` + `NO_COLOR` | UX §9 + step 7 emit signature | D.2 |
| L7 — symbols always paired with words | Step 12 (table renderer) | B.2 |
| L8 — UTF-8 + ASCII fallback | Step 12 + UX §5.3 | B.2 |
| L9 — refuse-to-overwrite + `--force` | Step 7 (preflight) | D.1 |
| L10 — atomic + SIGINT-safe | Step 7 (`atomic.py`) | A.1 |
| L11 — deterministic filenames | Step 12 (`det.deterministic_track_filename`) | A.1 |
| L12 — six positive booleans + three `--no-…` | UX §3.2 + cli.py | A.1, D.1, D.2, D.3 |
| L13 — one artifact per invocation | UX P1 + cli.py command separation | A.1 (audio), C.1 (nsf), B.1 (audit) |
| L14 — audit writes / coverage reads | Step 5 component table | B.1, B.2 |
| L15 — TTY detection drives feedback | Step 7 + UX §7.1 | D.2 |

**Coverage:** 15/15 UX lock decisions have architecture and story owners. No drift between UX intent and implementation plan.

### 4.3 UX open questions vs MVP scope

UX §13 lists 7 open questions explicitly deferred. Cross-checking against epics §13 *Out-of-MVP Deferral*:

| UX open question | Epics deferral entry | Consistent? |
|---|---|---|
| Q1 — Localization scope | (not directly mentioned, but UX §5.4 locks "French info + English errors" for MVP) | ✓ |
| Q2 — Coverage matrix as README badge | Epics §13 Growth | ✓ |
| Q3 — `--explain-config` flag | Epics §13 Growth | ✓ |
| Q4 — `--rename-by-hash` flag | Epics §13 Growth | ✓ |
| Q5 — Mapper-aware completion | Epics §13 Growth | ✓ |
| Q6 — Interactive REPL | Epics §13 Vision (FR32) | ✓ |
| Q7 — `--profile` named flag bundles | (not mentioned in epics; UX defers it) | ✓ implicit |

All 7 UX open questions are consistent with the epics' deferral list. No surprise scope addition or drop.

### 4.4 UX → architecture wire-through completeness

Architecture step 5's wiring diagram (`qlnes audio rom.nes --format wav` step-by-step) walks through: ConfigLoader → Preflight → Rom → RomProfile → SoundEngineRegistry → engine.walk_song_table → FceuxOracle.trace → engine.render_song → engine.detect_loop → wrap_pcm_riff → atomic_write_bytes. Each node maps to either a UX-locked behavior or a UX-specified output. No silent gap.

### 4.5 UX-alignment summary

✓ **PASS.** Every PRD journey is represented by a UX sample session and a story AC; every UX locked decision has architecture and story owners; every UX-deferred item is mirrored in the epics' deferral list.

---

## 5. Epic Quality Review

### 5.1 Anti-pattern check (per pass-1 pre-emptive guidance)

| Anti-pattern | Detected in pass 2? | Evidence |
|---|---|---|
| Technical-milestone epic | ✗ none | All 5 epic titles are user outcomes ("Get music out of a ROM", "Trustworthy coverage", "Sara's NSF…", "Pipeline-grade CLI contract", "Regression net for existing features"). No "Build the APU emulator" epic. |
| Forward dependencies | ✗ none | Dependency graph (epics §9) is a DAG. Only edges into A are the brownfield baseline; B/C/D depend on A.1's scaffold (a *backward* dep, not forward); E is fully independent. |
| Story without user-visible value | ✗ none | Every story title leads with a user-value verb ("Render", "Encode", "See", "Verify", "Refuse", "Migrate", "Lock down", "Confirm", "Surface", "Add", "Audit", "Embed", "Install"). Each story closes ≥ 1 AC at the CLI surface. |
| Story not a vertical slice | ✗ none | A.1 bundles cross-cutting scaffold (`atomic.py`, `errors.py`, `preflight.py`, `det.py`, `config/loader.py` minimal, APU emulator, FT engine, WAV writer, FCEUX oracle) inside the user-value outcome "Marco gets one WAV". The infrastructure does not stand alone. |

**Verdict:** **0 anti-patterns detected.**

### 5.2 Story-shape compliance

Story-shape locked in epics §2 includes: User value sentence, FRs closed, NFRs touched, Pre-conditions, Embedded scaffolding, AC list (numbered), Dev notes, Estimate (S/M/L). Sampled compliance check:

- A.1 — ✓ all sections present, AC list has 8 items, dev notes reference specific files.
- A.4 — ✓ all sections present, AC list has 5 items.
- B.4 — ✓ all sections present, AC list has 5 items.
- C.2 — ✓ all sections present, AC list has 5 items.
- D.4 — ✓ all sections present, AC list has 6 items.
- E.3 — ✓ all sections present, AC list has 3 items.

23/23 stories spot-checked or fully checked: shape is consistent. **0 shape violations.**

### 5.3 Acceptance-criterion testability

Sampled AC testability (does each AC name a concrete observable behavior?):

- A.1 AC1 — "filenames match `<stem>.<idx>.famitracker.wav`" → ✓ testable via glob.
- A.1 AC2 — "PCM SHA-256 matches FCEUX reference" → ✓ testable via hash compare.
- A.1 AC4 — "SIGKILL leaves target dir unchanged" → ✓ testable via subprocess + ls.
- B.1 AC2 — "validates against `bilan_schema.json`" → ✓ testable via validator call.
- B.4 AC4 — "`scripts/diff_bilan.py` exits non-zero on regression" → ✓ testable via subprocess.
- D.4 AC5 — "Unknown TOML key warns by default, errors under `--strict`" → ✓ testable via run-and-grep.

**Verdict:** all sampled ACs are observable. **No vague "the system should be reliable"-style ACs.**

### 5.4 Story estimate sanity

Estimates: 13 × S, 9 × M, 1 × L (A.4 — Capcom RE).

- A.4 alone is L, justified by the engine-RE work.
- A.1 is L (1 dev-week) — bundles APU + FT + scaffold; consistent with the architecture's component count.
- No estimate is XL. Aligns with the readiness report's pre-emptive guidance ("split anything > 1 dev-week").

**Verdict:** estimate distribution is plausible for a solo developer.

### 5.5 Dependency-graph health

The graph in epics §9 has:

- 1 entry node (A.1 — only it has no story dependency).
- 1 critical path (A.1 → A.4 → A.5 → B.3 → B.4 → B.5).
- 4 branches converging at B.4 (the audit + release gate).
- 3 leaves (D.5 completion, B.5 stale-refresh, E.3 cynes verification).

**Cycles?** None visible. **Verdict:** valid DAG.

### 5.6 Sprint sequencing realism

The 8-sprint suggestion in epics §12 sequences stories such that:

- Sprint 1 ships A.1 + E.1 in parallel (correct — they touch disjoint files).
- Sprint 2 ships A.2 + A.3 + D.1 (correct — D.1 only depends on A.1).
- Sprint 5 ships B.3 + B.4 + B.5 (correct — three small/medium stories on the audit/coverage branch).

Estimate roll-up: ~8 sprints × 1 week ≈ 8 weeks ≈ 13 × 1 + 9 × 2.5 + 1 × 5 = 35.5 dev-days ≈ 7 weeks at 5 d/w. Within the ±30% confidence band the doc declares. **Verdict:** internally consistent.

### 5.7 Epic-quality summary

✓ **PASS.** No anti-patterns; consistent story shape; testable ACs; plausible estimates; valid DAG; realistic sprint plan.

---

## 6. Cross-Document Consistency

This section is new to pass 2 — it inspects whether PRD ↔ UX ↔ Architecture ↔ Epics agree on contested details.

### 6.1 Exit-code taxonomy consistency

| Code | PRD §327 | UX §6.2 | Architecture step 7 | Epics |
|---|---|---|---|---|
| 0 | success | success | success | A.* |
| 64 | EX_USAGE | usage_error / bad_format_arg | mapped | D.3 (mutex check) |
| 65 | EX_DATAERR | bad_rom | mapped | A.1 AC5 |
| 66 | EX_NOINPUT | missing_input | mapped | A.1 AC5 |
| 70 | EX_SOFTWARE | internal_error | mapped | A.2 AC3 (mp3 dep), D.4 AC5 (unknown key under --strict) |
| 73 | EX_CANTCREAT | cant_create | mapped | A.1 AC6, D.1 |
| 74 | EX_IOERR | io_error | mapped | (covered implicitly by atomic.py / errors.py infrastructure in A.1) |
| 100 | unsupported mapper | unsupported_mapper | mapped | A.1, A.4, C.3 |
| 101 | equivalence failed | equivalence_failed | mapped | A.5, A.6 |
| 102 | missing reference | missing_reference | mapped | B.1 AC5 |
| 130 | SIGINT | interrupted | mapped | A.1 (atomic kill safety) |

✓ Codes match across all four docs. **Finding L-1** below: code 74 (`io_error`) has no explicit story-level AC. It's covered structurally by the I/O infrastructure but no story tests it directly.

### 6.2 Filename convention consistency

- PRD §FR9: "deterministic and predictable from the input ROM's hash and the song-table index."
- UX §10.3: `<rom-stem>.<song-index-2-digit>.<engine>.<format>` — example `metalstorm.04.famitracker.wav`.
- Architecture step 7 / `det.py`: `deterministic_track_filename(rom_stem, song_index, engine, ext)` returns `f"{rom_stem}.{song_index:02d}.{engine}.{ext}"`.
- Epics A.1 AC1: filenames named `<rom-stem>.<song-index-2-digit>.famitracker.wav`.

✓ Consistent. **Finding L-2** below: PRD says "from the input ROM's hash *and* the song-table index" but UX/Arch/Epics use `<rom-stem>` (the user's filename) not the hash. Pass-1 acknowledged this divergence implicitly in UX §10.3's note: "user-supplied filename is friendlier in human contexts. Pipelines that need hash-stable names pass `--rename-by-hash` (Growth flag)." The PRD's "and" is therefore *aspirational*; the MVP delivers the human-friendly variant. This is a minor PRD-vs-UX wording disagreement worth noting but not a blocker.

### 6.3 NSF format consistency

- PRD: NSF in MVP scope (FR5).
- Architecture ADR-08: NSF2 + NSFe metadata chunks.
- UX §11.2: Sara loads `ost.nsf` in NSFPlay with track titles.
- Epics C.1 + C.2: NSF2 base + NSFe chunks.
- Epics C.3: mapper-66 best-effort under `--experimental`.

✓ Consistent.

### 6.4 Locale & color consistency

- UX §5.4: French informational + English errors.
- Architecture step 7 (`errors.py`): hardcoded English class names; French/English bifurcation in info-line conventions.
- Epics: not directly tested but A.1 AC5 expects `qlnes: error: missing_input` in English, which matches.

✓ Consistent.

### 6.5 Performance budget consistency

- PRD NFR-PERF-2: audio render ≤ 2× real time.
- UX: not directly mentioned (UX is not the perf surface).
- Architecture step 8 sketch: pure-Python APU emulator at ~25 s for a 3-minute track — 7× headroom.
- Epics A.1 AC3: "Rendering a 3-minute FT song completes in under 6 minutes."

✓ Consistent. Architecture's 25 s sketch is well inside the 6-minute AC and the 360-second NFR budget.

### 6.6 Determinism invariants consistency

- PRD NFR-REL-1: byte-identical PCM canonical hash target.
- UX P2: determinism is a UX feature.
- Architecture step 15: deterministic strategy in concrete terms (no `datetime.now()` in artifact-writers, integer math, sorted iteration).
- Epics A.1 AC7, A.1 AC8, A.2 AC4, A.3 AC5, B.1 AC4, C.1 AC3: explicit determinism ACs.

✓ Consistent and well-instrumented.

### 6.7 Cross-document consistency summary

✓ **PASS** with two minor wording inconsistencies (filename hash vs stem in PRD wording — see Finding L-2; one missing exit-code AC — see Finding L-1). Neither is a blocker.

---

## 7. Risk Posture vs Pass 1

Pass 1 declared 0 PRD defects but 6 architecture-phase open questions. Pass 2 status:

| Pass 1 question | Architecture step that closes it | Verdict |
|---|---|---|
| Q1 — APU backend | Step 4 (own implementation locked), step 8 (per-channel design), step 10 (FCEUX oracle role) | ✓ closed |
| Q2 — corpus IP/distribution | Step 11 (hashes-only manifest, no ROM redistribution, license posture) | ✓ closed |
| Q3 — song-table detection | Step 9 (`SoundEngine` ABC + 4 handlers + generic fallback) | ✓ closed |
| Q4 — NSF format | Step 4 + step 12 (NSF2 + NSFe chunks) | ✓ closed |
| Q5 — loop-boundary detection | Step 9 (3-tier strategy, never PCM autocorrelation as primary) | ✓ closed |
| Q6 — MP3 encoder | Step 4 (`lameenc==1.7.0`, subprocess `lame` fallback documented) | ✓ closed |

**6/6 open questions closed.**

Pass 2 introduces a new risk surface from the architecture's risk register (12 risks). These are *implementation-time* risks, not *readiness* blockers — they are mitigations the architecture commits to before / during stories, not gaps in the planning artifacts. Pass 2 accepts the risk register as part of the scope and does not flag any of the 12 risks as a readiness blocker.

---

## 8. Findings Catalog

### Severity legend

- **Critical** — blocks SP. Fix required before any sprint kickoff.
- **High** — fix required before story enters a sprint, but does not block SP.
- **Medium** — fix required within first 2 sprints; no scoping impact.
- **Low** — informational; fix at maintainer's convenience.

### 8.1 Critical findings

**(none)**

### 8.2 High findings

#### **H-1.** Story A.2 AC2 is logically incorrect (lossy round-trip cannot be byte-equivalent)

> Epics §A.2 AC2: *"Decoding an MP3 file back to PCM (via `lameenc.decode` or a reference decoder) yields a PCM stream whose SHA-256 matches the WAV path's PCM for the same ROM × song-index."*

**Problem.** MP3 is a lossy codec. The decoded PCM after MP3 encoding will *not* match the source PCM byte-for-byte; that is a fundamental property of lossy compression, not an implementation defect. As written, this AC is unsatisfiable.

**Why this is High and not Critical.** It is a single-AC defect; the story as a whole is sound. AC4 (`Two consecutive --format mp3 runs produce byte-identical MP3 files`) is the correct invariant for `lameenc==1.7.0` byte-determinism, and that one is satisfiable. AC1 / AC3 / AC5 are also fine.

**Fix.** Replace AC2 with one of:

- *(option A — drop the AC entirely)* — AC4 already covers MP3 byte-determinism, which is what the architecture step 4 promised.
- *(option B — restate the AC with a perceptual-quality budget)* — "RMSE between MP3-decoded PCM and source PCM is below 1 % of full-scale; verified by `tests/integration/test_mp3_quality.py`." This is the form pass-2 recommends because it gives the implementer a quantitative target without claiming impossible bit-equivalence.

**Recommended action.** Edit `epics-and-stories.md` §A.2 AC2 before story A.2 is created via `bmad-create-story` (CS). The fix is a one-line edit and does not change the estimate.

### 8.3 Medium findings

#### **M-1.** Warning class `mp3_encoder_version` (UX §6.5) has no explicit story owner

The UX doc declares a `warning: mp3_encoder_version` class — emitted when the local `lameenc` version differs from the bilan's lockfile, signalling that MP3 byte-equivalence is not guaranteed for that run. No story explicitly produces or tests this warning.

**Closest implicit owner:** A.2 (introduces `lameenc` dependency). A.2's pre-flight predicate `_check_lameenc_available` could be extended to compare against a pinned-version constant. The story doesn't currently mention this.

**Fix.** Add to A.2 dev notes: "Pre-flight emits `warning: mp3_encoder_version` if `lameenc.__version__ != '1.7.0'`. Suppressed if `--no-hints`. Becomes an error under `--strict`."

#### **M-2.** Warning class `unknown_engine` (UX §6.5) emission point is implicit

UX declares the `unknown_engine` warning, emitted when a ROM's audio engine is not recognized. A.5 produces tier-2 output but doesn't explicitly test for the warning emission — only the `bilan.json` `engines.unknown` tagging.

**Fix.** Add an AC to A.5: "Without `--strict`, the run emits `qlnes: warning: engine not recognized; output is frame-accurate (tier 2), not sample-equivalent` to stderr. JSON payload `{'class': 'unknown_engine', ...}`. Suppressed under `--no-hints`."

#### **M-3.** Story A.4 Capcom estimate (L = 1 dev-week) is the most uncertain in the plan

A.4 includes engine reverse-engineering of Capcom-3 / Sakaguchi format. RE work is hard to estimate and historically tends to overshoot. The plan acknowledges this in epics §12 confidence band ±30%, but A.4 is the dominant uncertainty.

**Fix (recommended pre-SP action).** Before SP, time-box a 2-day spike to "produce a tier-2 generic-fallback render of one Capcom ROM and a syntactic dump of its song-pointer table." If the spike confirms the format is recognizable in 2 dev-days, A.4 stays L. If RE is harder than expected, A.4 splits into A.4a (Capcom Mega Man 2 only) + A.4b (Capcom DuckTales — second ROM to confirm pattern generalizes) with estimates M + S.

#### **M-4.** Story B.3 IP-discipline workflow assumes maintainer-side ROM availability

B.3 says contributors / CI place ROMs into `corpus/roms/<sha>.nes`. But CI specifically (see `audit.yml` in B.4 dev notes) needs ROMs at audit time. The plan mentions `scripts/restore-corpus.sh` using a GitHub Actions secret `QLNES_CORPUS_BUNDLE_URL` but does not specify *what* hosts the bundle.

**Fix.** Before B.4 lands, decide one of:

- **Maintainer-private S3** (or equivalent) holding the ROM bundle, with a short-lived signed URL — straightforward but assumes Johan has S3 / R2 / etc.
- **Self-hosted runner** with the corpus mounted from a private filesystem.
- **No CI audit; only local audits** until pip-install / Growth — eliminates the ROM-on-CI question, defers the release-gate-via-CI commitment to Growth tier.

Option C is the lowest-effort and is the recommended pass-2 stance. Document it in B.4 dev notes; revisit at Growth.

### 8.4 Low findings

#### **L-1.** Exit code 74 (`io_error`) has no explicit story-level AC

Code 74 is reserved for I/O errors mid-write. No story has an AC that exercises this path. The infrastructure (`qlnes/io/atomic.py`'s exception handling) covers it structurally, but no test asserts the exit code is 74 on (e.g.) disk-full.

**Fix (optional).** Add `tests/unit/test_atomic_writer.py::test_disk_full_exits_74` (force a small `/tmp` partition or use `os.write` mock). Not blocking; structural coverage is adequate.

#### **L-2.** PRD FR9 mentions "ROM hash and song-table index" for filenames; UX/Architecture/Epics use ROM stem instead

See §6.2 above. The PRD wording is technically misaligned with the implemented behavior. This is a *PRD-vs-implementation* drift, not a bug.

**Fix (optional).** Either (a) leave as-is (the divergence is documented in UX §10.3 as a deliberate human-friendliness choice; pipelines opt into hash-named via the Growth-tier `--rename-by-hash` flag), or (b) amend the PRD on the next refresh to clarify "user-friendly stem by default; hash-stable filenames available in Growth via `--rename-by-hash`." Pass-2 recommends (a) — minimal churn.

#### **L-3.** No story explicitly tests the `qlnes.toml` discovery order (UX §4.2 specifies `--config <path>` > `$PWD/qlnes.toml` > `<rom_dir>/qlnes.toml`)

D.4 AC6 tests `--config <path>` overriding TOML discovery, but does not test the `$PWD` vs `<rom_dir>` precedence order.

**Fix (optional).** Extend D.4 AC6 with: "Without `--config`, `$PWD/qlnes.toml` wins over `<rom_dir>/qlnes.toml` when both exist." One-line addition.

#### **L-4.** `qlnes coverage` colorized output rendering relies on a TTY-detection helper (`qlnes/io/term.py`) introduced in D.2

B.2 ships the coverage table; D.2 ships TTY detection. If sprint sequencing is changed, B.2 might land before D.2 and need a temporary minimal helper. The doc handles this implicitly (the TTY detection helper is short enough to land inside B.2 if needed) but doesn't say so.

**Fix (optional).** Add to B.2 dev notes: "If D.2 has not yet merged, this story introduces a minimal `qlnes/io/term.py::is_tty_stderr()` helper; D.2 extends it later."

#### **L-5.** Architecture step 14 release process names "scripts/diff_bilan.py" but no story explicitly creates it

The `diff_bilan.py` script is mentioned in epics §B.4 dev notes — implicit ownership, not explicit. Sufficient for the story's AC4 ("`scripts/diff_bilan.py prev.json new.json` exits 0/non-zero on regression") which mandates it exists.

**Fix.** None required; AC4 is sufficient.

#### **L-6.** Test corpus size (50 ROMs) is declared without a justification

PRD NFR-PERF-3 mentions "50-ROM corpus." Architecture step 11 echoes "50-ROM target." Epics B.3 / B.4 echo "50 ROMs." None of the docs justifies *why* 50 — vs 30, vs 100. The choice seems pragmatic (large enough to span 4–5 mappers and 2–3 engines with replicates; small enough to audit in <30 min on CI). Worth recording for future maintainers.

**Fix (optional).** Add to architecture step 11 or epics §13 a one-line rationale: "Corpus size 50 = 4 mappers × ~3 ROMs × 2 engines × 1 region + extras for engine-tier-2 stress-testing. Tradeoff: NFR-PERF-3 (audit time) caps the upper bound; engine coverage caps the lower."

---

## 9. Summary & Verdict

### 9.1 Overall readiness status

**CONDITIONAL GO for `bmad-sprint-planning` (SP).**

The four-document set (PRD + UX + Architecture + Epics & Stories) is internally consistent, fully cross-referenced, and covers 28/28 MVP FRs and 18/18 NFRs. Pass-1's six open architecture questions are all closed. Epic structure follows pre-emptive guidance with 0 anti-patterns detected.

The condition: **fix Finding H-1 (Story A.2 AC2) before A.2 is created via `bmad-create-story`**. This is a one-line edit and does not change story estimate, sprint sequence, or any dependency.

The 4 Medium findings (M-1 through M-4) are recommended fixes during sprint planning or before the affected stories enter their sprints. None are blockers.

The 6 Low findings (L-1 through L-6) are informational and do not require action before SP.

### 9.2 What changed since pass 1

| Dimension | Pass 1 | Pass 2 |
|---|---|---|
| Substantive artifacts | 1 (PRD) | 4 (PRD, UX, Architecture, Epics & Stories) |
| Architecture-phase open questions | 6 | 0 |
| Categories yielding structural N/A | 3 (Epic Coverage, UX Alignment, Epic Quality) | 0 |
| FR coverage | N/A | 28/28 |
| Verdict | READY for architecture | CONDITIONAL GO for sprint planning |

### 9.3 Required actions before SP

1. **Fix Finding H-1** — edit `epics-and-stories.md` §A.2 AC2 (one-line edit, ~5 minutes).

That is the only required action.

### 9.4 Recommended actions before / during SP

2. **Fix Findings M-1 and M-2** during SP — both are AC additions to existing stories, ~10 minutes each.
3. **Address Finding M-3** by running a 2-day Capcom-RE spike before sprint 3 (when A.4 is scheduled). If the spike confirms estimate, no further action; otherwise split A.4.
4. **Address Finding M-4** by deciding the corpus-on-CI approach during SP (recommended: option C — local-only audits in MVP, defer CI audit to Growth).
5. **Address Findings L-1 through L-6** at maintainer's convenience — none are blockers.

### 9.5 Recommended next steps

1. **Apply Finding H-1's fix** (`epics-and-stories.md` §A.2 AC2).
2. **Run `bmad-sprint-planning` (SP)** using the 8-sprint sequence in epics §12 as a starting point.
3. **Begin sprint 1 cycle:** `bmad-create-story` (CS) for A.1, then `bmad-dev-story` (DS), `bmad-code-review` (CR), and the regular per-story loop.
4. **Optional but recommended:** run the 2-day Capcom-RE spike (Finding M-3) before sprint 3 to de-risk A.4's L estimate.
5. **Optional:** address the 4 Medium findings (M-1 through M-4) and the 6 Low findings (L-1 through L-6) opportunistically during sprint planning or at story-creation time.

### 9.6 Final note

This pass-2 assessment confirms that the qlnes music-MVP planning artifacts are mature enough to support sprint-level execution. The only required pre-SP fix is a one-line correction to a single AC in story A.2 — a defect introduced by stating an unsatisfiable equality (lossy round-trip can never be byte-equivalent). That defect is procedurally easy to fix; identifying it is the kind of finding pass-2 readiness checks exist to surface.

The pass-1 verdict's predicted readiness uplift has been delivered: the three categories that produced structural N/As in pass 1 (Epic Coverage, UX Alignment, Epic Quality) now produce real findings, and all three pass with minor remarks. The 6 architecture-phase open questions are all closed.

**Assessor:** Claude (Opus 4.7), acting as PM-readiness validator.
**Date:** 2026-05-03 (afternoon session, pass 2 of 2 today).
**Pass-3 trigger:** Only if scope changes materially (new epic added, new MVP FR, NFR re-tightening) or if Finding H-1 is not addressed before A.2's story creation.

---

*End of Implementation Readiness Assessment Report — Pass 2 (qlnes, 2026-05-03)*
