---
artifact_type: sprint-plan-and-status
project_name: qlnes
mvp_target: v0.5.0 (music workstream)
date_created: 2026-05-03
date_updated: 2026-05-03 (A.1 + E.1 merged ; A.2 + D.1 done ; A.3 partial — chunk infra ready, FT-Bxx detection deferred to fixture ROM)
created_by: bmad-sprint-planning (SP)
created_after_readiness: implementation-readiness-report-2026-05-03-pass-2.md (CONDITIONAL_GO, H-1 resolved)
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/epics-and-stories.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03-pass-2.md
sprint_count: 8
total_stories: 23
solo_developer: Johan
velocity_assumption: 5 dev-days / sprint (1 work-week)
confidence_band: ±30%
next_action: bmad-create-story (CS) for story A.1
next_story: A.1
status_legend: [BACKLOG, READY, IN_PROGRESS, IN_REVIEW, DONE, BLOCKED]
---

# Sprint Plan & Status — qlnes Music-MVP

**Project:** qlnes
**Target:** `v0.5.0` (music workstream MVP)
**Author:** Johan (solo developer)
**Source of truth for `bmad-create-story` (CS) → `bmad-dev-story` (DS) → `bmad-code-review` (CR) cycle.**

---

## 0. Pre-flight

### 0.1 Readiness gate

Pass-2 readiness check returned `CONDITIONAL_GO` with one High-severity finding:

- **H-1** (Story A.2 AC2 — lossy round-trip cannot be byte-equivalent) — **resolved 2026-05-03** by editing `epics-and-stories.md` §A.2 AC2 to use a perceptual mean-error budget (< 1 % full-scale) instead of byte-identity.

The 4 Medium findings (M-1, M-2, M-3, M-4) are folded into this sprint plan as explicit per-story dev notes or per-sprint risk items (see §3.1, §3.3, §3.5).

### 0.2 Velocity assumption

Solo developer; ~5 dev-days per sprint (one work-week). Estimates from epics §2:

- `S` = ≤ 1 dev-day
- `M` = 2–3 dev-days
- `L` = 1 dev-week

23 stories: 13 × S, 9 × M, 1 × L → ~35.5 dev-days → ~7 work-weeks (5 d/w). Sprints add coordination overhead → **8 sprints planned** with deliberate slack in sprints 4 and 8.

### 0.3 Definition of Ready (DoR) — for a story to enter a sprint

A story is **READY** when:

1. Its dependencies (per epics §9 dependency graph) are **DONE**.
2. Its acceptance criteria are testable as written (verified by pass-2 readiness check or by `bmad-create-story` validation).
3. Required external artifacts (corpus ROM, FCEUX install, etc.) are available locally.
4. The dev environment can run the story's test layer (unit / integration / invariants).
5. No M-class finding from the readiness report blocks entry without resolution.

### 0.4 Definition of Done (DoD) — for a story to leave a sprint

A story is **DONE** when:

1. All acceptance criteria pass (CI green for relevant test layers).
2. Code review (`bmad-code-review` / `CR`) has no `must-fix` items.
3. The story's NFR touches are verified by their named tests (epics §11 table).
4. No regression introduced in `tests/unit` or `tests/integration` (pre-merge CI).
5. New files / modules conform to the architecture's repo layout (architecture step 6).
6. Dev notes from the story are reflected in `qlnes/`-side comments **only where non-obvious** (per Johan's CLAUDE.md preference: no commentary explaining what the code does).
7. Story status updated to **DONE** in this file's §4 tracking table.

### 0.5 Definition of Done — for a sprint

A sprint is **DONE** when:

1. Every story planned for the sprint is **DONE** or has been re-planned to a later sprint (with documented reason).
2. The sprint goal (per §3) is met or explicitly deferred.
3. Sprint retrospective notes appended to §6 *Retrospective Log*.
4. Sprint exit metric (per §3) is satisfied.

---

## 1. Sprint Roster (overview)

| # | Sprint goal | Stories | Total est. (d) | Sprint exit metric |
|---|---|---|---|---|
| 1 | First WAV out of a ROM | A.1, E.1 | 6 | `qlnes audio rom.nes --format wav` produces a sample-equivalent WAV for one fixture FT mapper-0 ROM |
| 2 | Format & loop fidelity | A.2, A.3, D.1 | 3 | MP3 + loop-aware WAV `'smpl'` chunks + refuse-to-overwrite |
| 3 | Capcom + generic engines | A.4, A.5 | 7 | A second tier-1 engine (Capcom) passes equivalence; tier-2 fallback works for any unrecognized ROM |
| 4 | Coverage matrix | B.1, B.2, A.6 | 6 | `qlnes audit` writes valid `bilan.json`; `qlnes coverage` renders table + JSON; `verify --audio` works |
| 5 | Corpus & release gate | B.3, B.4, B.5 | 7 | Full audit on 50-ROM corpus completes < 30 min; release-gate diff script catches regressions |
| 6 | Sara's NSF | C.1, C.2, C.3 | 7 | NSF2 + NSFe loads in NSFPlay/GME with track titles for mapper-0 + mapper-66 (experimental) |
| 7 | Pipeline polish | D.2, D.3, D.4, D.5, C.4 | 7 | Lin's subprocess pattern works against the full pipeline-mode flag set; legacy `nsf.py` removed |
| 8 | Hardening + tag | E.2, E.3, release prep | 3 | Round-trip + asset regression tests green; `v0.5.0` tag pushed; `audit.yml` produces canonical `bilan.json` |
| | **Total** | **23 stories** | **~46 d** (with slack) | — |

**Total estimate including slack:** ~46 dev-days ≈ 9.2 work-weeks at 5 d/w. Confidence band ±30% per readiness pass 2.

---

## 2. Critical path & parallelism

```
        ┌─ Epic E (regression net) ─────────────────────────────────┐
        │                                                            │
A.1 ────┴─→ A.2, A.3, D.1 ─→ A.4 ─→ A.5 ─→ A.6 (verify)
            │                       │
            │                       ├─→ B.1 ─→ B.2 ─→ B.5
            │                       │
            │                       └─→ B.3 ─→ B.4
            │
            ├─→ C.1 ─→ C.2 ─→ C.3 ─→ C.4
            │
            └─→ D.2 ─→ D.3, D.4 ─→ D.5
```

**Critical path (longest sequence of strict dependencies):**

```
A.1 → A.4 → A.5 → B.3 → B.4 → B.5
```

6 stories, ~14 dev-days end-to-end. Anything off this path is parallelizable; SP exploits this in sprints 1 & 4 by mixing critical-path with off-path stories.

**Parallelism in MVP (independent sub-trees):**

- Epic E is fully independent of A–D after E.1.
- Epic C (NSF) only depends on A.1 and A.4 — runs alongside epic B once those land.
- Epic D (pipeline polish) only depends on A.1 — runs anytime sprint 2+.

---

## 3. Per-Sprint Detail

---

### Sprint 1 — First WAV out of a ROM

**Sprint goal.** Marco (or Johan running smoke-test) types `python -m qlnes audio <fixture-rom.nes> --format wav --output tracks/` and gets a sample-equivalent WAV file from one FT mapper-0 ROM. Cross-cutting scaffold lands.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| A.1 | Render one mapper-0 FamiTracker ROM to sample-equivalent WAV | L (5d) | 8 | BACKLOG |
| E.1 | Migrate existing tests into the unit/integration/invariants layout | S (1d) | 4 | BACKLOG |

**Capacity check.** L + S = 6 dev-days. Slightly over the 5-day target — sprint 1 gets a 20% overrun buffer because A.1's APU emulator is the highest-uncertainty work. If A.1 ships in 4 days, both fit.

**Sprint risks.**

- **R-S1-1.** APU emulator's per-channel sample-equivalence is the riskiest deliverable in the entire MVP. Mitigation: the architecture's per-channel unit-test plan (architecture step 8) lands inside A.1's dev work; FCEUX trace + reference-PCM oracle catches divergence frame-by-frame.
- **R-S1-2.** FCEUX install on the dev machine. Mitigation: `scripts/install_audio_deps.sh` (existing, will be touched in A.1 to add `lameenc==1.7.0`).

**Sprint exit metric.** `pytest tests/invariants/test_pcm_equivalence.py::test_apu_vs_fceux_per_channel[<fixture-fname>]` passes on the chosen mapper-0 FT fixture ROM.

**Inputs to `bmad-create-story` (CS) for A.1.**

- Pre-condition: none (A.1 is the entry node).
- Embedded scaffolding: see epics §A.1 *Embedded scaffolding* (12 modules / files).
- Test fixtures: 1 mapper-0 FT ROM in `tests/fixtures/<sha>.nes` — Johan to provide a legally-redistributable homebrew test ROM (or, if none on hand, any mapper-0 NSF source that can be back-converted).
- Pre-flight predicates introduced: `_check_rom_readable`, `_check_output_writable`, `_check_fceux_on_path`.

---

### Sprint 2 — Format & loop fidelity

**Sprint goal.** WAV output gains loop boundaries (`'smpl'` chunk); MP3 output is added; `--force` is required to overwrite existing outputs. Marco's J1 happy path is fully usable for one engine, both formats, with proper looping.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| A.2 | Render the same ROM to MP3 via lameenc | S (1d) | 5 | BACKLOG |
| A.3 | Encode loop boundaries into WAV `'smpl'` chunks | S (1d) | 5 | BACKLOG |
| D.1 | Refuse to overwrite by default; `--force` to override | S (1d) | 4 | BACKLOG |

**Capacity check.** 3 × S = 3 dev-days. Comfortable.

**Sprint risks.**

- **R-S2-1.** `lameenc==1.7.0` wheel availability on Linux Python 3.11. Mitigation: this is the version currently published on PyPI; A.2's pre-flight will detect mismatch and emit `warning: mp3_encoder_version` (Finding M-1 fix folded in here — see §A.2 dev notes amendment below).

**Sprint exit metric.** `qlnes audio rom.nes --format mp3 --output tracks/` produces 23 deterministic MP3 files; `qlnes audio` re-run without `--force` exits 73; one `Bxx` loop opcode in the FT corpus produces a valid `'smpl'` RIFF chunk.

**M-1 fix — A.2 dev-notes amendment to apply during CS.**

> Pre-flight emits `warning: mp3_encoder_version` if `lameenc.__version__ != "1.7.0"`. JSON payload `{"class":"mp3_encoder_version","installed":"<version>","expected":"1.7.0"}`. Suppressed by `--no-hints`. Becomes a hard error under `--strict`.

---

### Sprint 3 — Capcom + generic engines

**Sprint goal.** A second tier-1 engine (Capcom) passes equivalence on its mapper × ROM subset. The generic fallback works for any unrecognized ROM and tags output `unverified`.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| A.4 | Add Capcom engine handler + corpus to mappers 1, 2, 4, 66 | L (5d) | 5 | BACKLOG |
| A.5 | Surface unrecognized-engine output as `unverified` (generic fallback) | M (2–3d) | 5 | BACKLOG |

**Capacity check.** L + M ≈ 7 dev-days. **Sprint 3 is the most uncertain in the plan.** If A.4 overruns, A.5 slides to sprint 4 and B.1 gets postponed.

**Sprint risks.**

- **R-S3-1 (Finding M-3 from readiness pass-2).** Capcom RE may be harder than estimated. **Mitigation: time-boxed 2-day spike before sprint 3 starts.** Spike deliverable: produce a tier-2 generic-fallback render of one Capcom ROM and a syntactic dump of its song-pointer table. If the spike confirms format recognizability in 2 dev-days, A.4 stays L. Otherwise, A.4 splits into A.4a (Capcom Mega Man 2 only, M) + A.4b (Capcom DuckTales generalization, S).
- **R-S3-2.** Mapper-66 multi-bank pipeline (recently shipped, commit `c8fbc8f`) regresses with the new audio pipeline. Mitigation: A.4 AC2 explicitly tests the existing mapper-66 path stays green.

**Sprint exit metric.** `qlnes audio` against ≥ 6 Capcom ROMs in the corpus produces sample-equivalent WAVs; `qlnes audio` against an unrecognized-engine ROM produces tier-2 WAVs tagged `unverified` in the eventual `bilan.json`.

**M-2 fix — A.5 AC amendment to apply during CS.**

> AC6 (new) — Without `--strict`, the run emits a warning line `qlnes: warning: engine not recognized; output is frame-accurate (tier 2), not sample-equivalent` to stderr after the success line. JSON payload `{"class":"unknown_engine","rom_sha256":"...","tier":2}`. Suppressed under `--no-hints`. Under `--strict`, escalates to the `equivalence_failed` exit-101 path already specified in AC3.

---

### Sprint 4 — Coverage matrix

**Sprint goal.** `qlnes audit` writes a valid `bilan.json`; `qlnes coverage` renders the table or JSON; `qlnes verify --audio` works per-ROM.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| B.1 | Audit one ROM and write `bilan.json` | M (2–3d) | 5 | BACKLOG |
| B.2 | See the coverage matrix as table or JSON | M (2–3d) | 5 | BACKLOG |
| A.6 | Verify a single ROM's audio against FCEUX | S (1d) | 5 | BACKLOG |

**Capacity check.** M + M + S ≈ 6 dev-days. Slight overrun; A.6 (S) is the buffer that slips to sprint 5 if needed.

**Sprint risks.**

- **R-S4-1.** `bilan.json` schema-validation choice (hand-rolled vs `jsonschema` dep). Mitigation: B.1 dev notes already commit to hand-rolled in MVP; revisit at Growth.
- **R-S4-2.** Coverage table layout drift from UX §5.3. Mitigation: B.2 AC1 anchors the table format byte-for-byte to the UX spec.

**Sprint exit metric.** `qlnes audit && qlnes coverage` round-trip produces the UX §5.3 table; `qlnes coverage --format json | jq '.results."0".audio.status'` returns a valid status string.

---

### Sprint 5 — Corpus & release gate

**Sprint goal.** The full corpus (target 50 ROMs) is auditable in parallel under 30 minutes; release-gate diff script catches regressions; `bilan.json` becomes the public scoreboard.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| B.3 | Set up corpus manifest + reference-generation script | M (2–3d) | 5 | BACKLOG |
| B.4 | Audit full corpus in parallel + release gate | M (2–3d) | 5 | BACKLOG |
| B.5 | Refresh the bilan automatically when stale | S (1d) | 5 | BACKLOG |

**Capacity check.** M + M + S ≈ 7 dev-days. Within ±30% of the 5-day baseline.

**Sprint risks.**

- **R-S5-1 (Finding M-4 from readiness pass-2).** Corpus-on-CI workflow under-specified. **Mitigation: SP commits to option C** — local-only audits in MVP, defer CI-audit to Growth. B.4 dev notes amendment below makes this explicit. `audit.yml` is reduced to a stub that documents the manual procedure; full CI audit is a Growth story.
- **R-S5-2.** Corpus IP coordination (legal-side review of the manifest's `[[reference]]` table). Mitigation: hashes-only manifest is uncontroversial under copyright (see architecture step 11); `NOTICE.md` carries the third-party license stack.
- **R-S5-3.** `pytest-xdist` non-determinism on the equivalence corpus. Mitigation: per-ROM jobs are isolated; aggregation is sorted by `rom_sha256`. Falling back to serial mode (no xdist) for invariants-only is documented.

**Sprint exit metric.** `qlnes audit --corpus corpus/ --bilan ./bilan.json` on the 50-ROM corpus completes < 30 min; `bilan.json` is committed to `master`; `scripts/diff_bilan.py` exits 0 against the prior bilan (if any).

**M-4 fix — B.4 dev-notes amendment to apply during CS.**

> CI audit decision (per readiness pass-2 Finding M-4): MVP ships **local-only audits**. `audit.yml` is a documentation stub that links to `corpus/README.md` for the manual maintainer procedure. Full GitHub-Actions CI audit (with `scripts/restore-corpus.sh` + secret bundle) is deferred to Growth — entered as `epics §13 → Growth` and tracked separately. This decision keeps MVP scope tight and avoids the corpus-distribution-on-CI legal review.

---

### Sprint 6 — Sara's NSF

**Sprint goal.** Sara loads the produced `ost.nsf` in NSFPlay and sees track titles, lengths, fadeouts. Mapper-66 NSF works under `--experimental`.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| C.1 | Emit a valid NSF2 file for one mapper-0 ROM | M (2–3d) | 4 | BACKLOG |
| C.2 | Embed NSFe metadata (titles, lengths, fadeout, author, playlist) | M (2–3d) | 5 | BACKLOG |
| C.3 | Best-effort NSF for mapper-66 (experimental flag) | M (2–3d) | 4 | BACKLOG |

**Capacity check.** 3 × M ≈ 7 dev-days. Sprint 6 is well-defined and predictable; M-class stories on a relatively new code path.

**Sprint risks.**

- **R-S6-1.** NSFPlay / GME compatibility (Risk R7 from architecture). Mitigation: C.4 in sprint 7 lands the player-validity test suite; C.1–C.3 ship with manual NSFPlay smoke-test as AC.
- **R-S6-2.** Mapper-66 NSF banking is non-trivial despite the architecture's "best-effort" framing. Mitigation: `--experimental` flag clearly tags output as `partial`; not on the release-blocker path.

**Sprint exit metric.** `qlnes nsf <mapper-0-rom> --output ost.nsf` produces an NSF2+NSFe file that loads cleanly in NSFPlay with track titles; `qlnes nsf <mapper-66-rom> --experimental --output ost.nsf` produces a loadable NSF (audio quality not yet verified).

---

### Sprint 7 — Pipeline polish

**Sprint goal.** Lin's subprocess pattern works against the full pipeline-mode flag set (`--strict`, `--no-progress`, `--no-hints`, `--color`, `--debug`). Layered config + env vars + per-command sections fully implemented. Shell completion installed. Legacy `nsf.py` removed.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| D.2 | `--strict`, `--no-progress`, `--no-hints`, `--color {auto,always,never}` | M (2–3d) | 6 | BACKLOG |
| D.3 | `--debug` adds resolved config, per-step timings, full tracebacks | S (1d) | 5 | BACKLOG |
| D.4 | Layered config + env vars + per-command sections | M (2–3d) | 6 | BACKLOG |
| D.5 | Install shell completion | S (1d) | 4 | BACKLOG |
| C.4 | Verify NSF compatibility (NSFPlay/GME) + remove legacy `nsf.py` | S (1d) | 4 | BACKLOG |

**Capacity check.** 2 × M + 3 × S ≈ 7 dev-days. Largest sprint by story-count; mostly polish, low individual risk.

**Sprint risks.**

- **R-S7-1.** `--color` ANSI handling on `dumb` terminal / `script(1)` recording / non-TTY contexts. Mitigation: D.2 AC4–AC5 covers; UX §5.4 and §9.1 lock the behavior.
- **R-S7-2.** GME-Python binding availability on Linux. Mitigation: C.4 dev notes already document the subprocess `gme_player` fallback.

**Sprint exit metric.** `tests/integration/test_cli_audio.py` (Lin's subprocess pattern) is green end-to-end; `qlnes --install-completion zsh` installs cleanly; `git grep -l 'qlnes.nsf '` (legacy module, with trailing space) returns nothing.

---

### Sprint 8 — Hardening + tag

**Sprint goal.** Existing capabilities (`analyze`, `recompile`, `verify` round-trip, asset extraction) have a regression net. `cynes` feature-gating is verified. Tag `v0.5.0`.

**Stories.**

| ID | Title | Est | AC count | Status |
|---|---|---|---|---|
| E.2 | Lock down round-trip and asset-extraction tests | S (1d) | 3 | BACKLOG |
| E.3 | Confirm cynes-feature-gating still degrades gracefully | S (1d) | 3 | BACKLOG |
| (release) | `v0.5.0` tag + CHANGELOG + final manual smoke-tests | S (1d) | n/a | BACKLOG |

**Capacity check.** 3 × S = 3 dev-days. Sprint 8 has slack on purpose — it's the integration sprint where polish from earlier sprints' overruns can be absorbed.

**Sprint risks.**

- **R-S8-1.** Last-sprint scope creep ("just one more thing"). Mitigation: cut, defer to v0.5.1 / Growth. The MVP is sharp.

**Sprint exit metric.** `git tag v0.5.0` pushed; `bilan.json` regenerated from the tagged commit; CHANGELOG updated; manual run-through of all 4 PRD user journeys is green.

---

## 4. Story Tracking Table

The single source of truth for `bmad-sprint-status` (SS), `bmad-create-story` (CS), `bmad-dev-story` (DS), and `bmad-code-review` (CR). Update **status** as work progresses.

| ID | Title | Sprint | Estimate | Status | Depends on | FRs | NFRs | Story file | Dev-story branch |
|---|---|---|---|---|---|---|---|---|---|
| A.1 | Render one mapper-0 FT ROM to WAV | 1 | L | IN_REVIEW (7.1-7.6 ✓ ; 7.7 = fixture ROM + perf opt) | (none) | FR6, FR9, FR11, FR8/wav, FR10/ref | PERF-2 ⚠xfail, REL-1, REL-2, REL-4 | `stories/A.1.md` | master |
| E.1 | Migrate tests to unit/integration/invariants | 1 | S | DONE | A.1 (touches files) | (refactor) | — | (no separate story file) | master |
| A.2 | Render to MP3 via lameenc | 2 | S | DONE (lameenc==1.8.2 pin, M-1 warning wired) | A.1 | FR7, FR8/mp3 | DEP-2, REL-1 | — | master |
| A.3 | Loop boundaries → WAV `'smpl'` chunk | 2 | S | PARTIAL — chunk infra ready; FT-Bxx detection deferred to fixture ROM | A.1 | FR6/loop, FR10 | REL-1 | — | master |
| D.1 | Refuse to overwrite + `--force` | 2 | S | DONE (verifs added: --force doesn't bypass other preflight, multi-file first-conflict reported) | A.1 | FR37 | REL-4 | — | master |
| A.4 | Capcom engine + corpus broadening | 3 | L | BACKLOG | A.1, A.3 | FR11/capcom | PERF-3 | — | — |
| A.5 | Generic fallback (tier-2 unverified) | 3 | M | BACKLOG | A.1, A.3 | FR10/full, FR11/full | REL-5 | — | — |
| B.1 | Audit + `bilan.json` (single-ROM) | 4 | M | BACKLOG | A.1 | FR19, FR20, FR25 | REL-1, REL-2, REL-4 | — | — |
| B.2 | `qlnes coverage` table + JSON | 4 | M | BACKLOG | B.1 | FR21, FR25 | PERF-4 | — | — |
| A.6 | `qlnes verify --audio` per-ROM | 4 | S | BACKLOG | A.1, A.5 | FR18 | REL-1 | — | — |
| B.3 | Corpus manifest + reference-gen script | 5 | M | BACKLOG | B.1, A.1, A.4 | (FR19–26 enabling) | DEP-1 | — | — |
| B.4 | Full audit + release gate | 5 | M | BACKLOG | B.1, B.2, B.3, A.5 | FR19, FR26 | PERF-3, REL-3 | — | — |
| B.5 | Stale bilan + `--refresh` | 5 | S | BACKLOG | B.1, B.2, B.4 | FR22, FR23, FR24 | PERF-4 | — | — |
| C.1 | NSF2 base for mapper-0 | 6 | M | BACKLOG | A.1 | FR5/base | REL-1 | — | — |
| C.2 | NSFe metadata chunks | 6 | M | BACKLOG | C.1 | FR5/full | REL-1 | — | — |
| C.3 | Mapper-66 best-effort NSF (`--experimental`) | 6 | M | BACKLOG | C.2, A.4 | FR5/m66 | REL-5 | — | — |
| D.2 | `--strict`, `--no-progress`, `--no-hints`, `--color` | 7 | M | BACKLOG | A.1 | FR38, FR39 | REL-1 | — | — |
| D.3 | `--debug` | 7 | S | BACKLOG | D.2 | FR40 | — | — | — |
| D.4 | Full layered config + env vars + sections | 7 | M | BACKLOG | A.1, B.1, B.2 | FR27, FR28, FR29 | REL-1 | — | — |
| D.5 | Shell completion install | 7 | S | BACKLOG | A.1 | FR30 | PORT-1 | — | — |
| C.4 | NSFPlay/GME validity tests + remove legacy `nsf.py` | 7 | S | BACKLOG | C.1, C.2, C.3 | (cleanup) | REL-5 | — | — |
| E.2 | Round-trip + asset regression net | 8 | S | BACKLOG | E.1 | (validate FR1–4, 13, 14, 17) | REL-1, REL-2 | — | — |
| E.3 | Cynes feature-gating verification | 8 | S | BACKLOG | E.1 | (validate FR4) | DEP-1 | — | — |

### 4.1 Status legend (recall)

- **BACKLOG** — known, estimated, not yet ready for current sprint.
- **READY** — DoR satisfied, can be picked up by `bmad-create-story` (CS).
- **IN_PROGRESS** — `CS` done, `DS` underway.
- **IN_REVIEW** — `DS` done, `CR` pending or running.
- **DONE** — `CR` clean, story merged to `master`, all ACs green.
- **BLOCKED** — known impediment; requires `bmad-correct-course` (CC) to unblock.

### 4.2 Updating this table

When a story changes state:

1. Update its `Status` column.
2. If transitioning to **IN_PROGRESS**, fill `Story file` (path to `_bmad-output/implementation-artifacts/stories/<story-id>.md` produced by CS) and `Dev-story branch` (git branch name).
3. If transitioning to **DONE**, append to §6 *Retrospective Log*.
4. Bump `date_updated` in this file's frontmatter.

This is the contract `bmad-sprint-status` (SS) reads from.

---

## 5. Cross-cutting risk & blocker tracker

### 5.1 Active blockers

(None as of 2026-05-03 sprint-plan creation.)

### 5.2 Watch-list (risks not yet realized)

| ID | Risk | First sprint affected | Mitigation status |
|---|---|---|---|
| R-S1-1 | APU sample-eq shortfall | 1 | Mitigation built into A.1 (per-channel unit tests + FCEUX oracle); not yet exercised |
| R-S3-1 | Capcom RE harder than estimated | 3 | **Spike scheduled** before sprint 3 starts (2 dev-days, time-boxed) |
| R-S3-2 | Mapper-66 regression with new pipeline | 3 | A.4 AC2 covers; not yet tested |
| R-S5-1 | Corpus-on-CI under-specified | 5 | **Resolved by SP** — local-only audits in MVP (option C); CI deferred to Growth |
| R-S6-1 | NSFPlay/GME compatibility | 6 | C.4 covers in sprint 7; manual smoke-tests in sprints 6 ACs |

### 5.3 Re-planning triggers

If any of the following happen, run `bmad-correct-course` (CC) before continuing:

- A sprint ends with > 2 stories sliding to the next sprint.
- A.1 (sprint 1) does not pass the per-channel APU equivalence tests by end of sprint 1.
- A.4 RE-spike (before sprint 3) reveals Capcom format takes > 4 dev-days — split A.4.
- Pass-2 Finding H-1 fix is regressed (AC2 reverts to byte-identity claim).
- Architecture's risk register has any item escalate from "tracked" to "realized" — particularly R1 (APU shortfall), R7 (NSFPlay incompat), R10 (loop misclass).

---

## 6. Retrospective Log

(Empty — appended after each sprint's exit.)

### Template per sprint retro

```
### Sprint <N> retrospective — <YYYY-MM-DD>

**Goal achieved?** Yes / Partially / No — <reason>
**Stories DONE.** A.x, B.y, ...
**Stories slipped.** <none> / <list with reason>
**Velocity actual vs planned.** <X> dev-days actual / <Y> planned.
**Surprises.** <list>
**Decisions for next sprint.** <list>
**Risk register changes.** <list>
```

---

## 7. Out-of-MVP — Growth & Vision tracker

Items deferred from MVP per epics §13. Tracked here so they don't get lost between MVP exit (`v0.5.0`) and Growth kickoff.

### 7.1 Growth (post-v0.5.0, pre-v1.0.0)

- **FR12** — Per-engine coverage extension (Konami KGen, Sunsoft 5B, Namco 163, …).
- **FR15** — PNG ↔ CHR-ROM round-trip.
- **FR31** — `pip install qlnes` (`pyproject.toml` migration).
- **macOS portability** (NFR-PORT-2).
- **DMC channel** full implementation (architecture ADR-18).
- **Expansion-audio mappers** (MMC5, VRC6) for both audio rendering and NSF emission.
- **CI audit workflow** (deferred from sprint 5 per Finding M-4).
- UX §13 deferred items: `--explain-config`, `--rename-by-hash`, mapper-aware completion, README badge, localization scope decision, `--profile` named flag bundles.

### 7.2 Vision (v1.0.0+)

- **FR16** — Gameplay data tables (drop tables, RNG seeds, AI scripts).
- **FR32** — `qlnes shell <rom>` interactive REPL.
- **Public Python API** (currently CLI-only per UX P4 / ADR-20).
- **Windows portability** (NFR-PORT-3).

These are **not** part of the MVP sprint plan. They are recorded here so that during sprint 8's release prep, the Growth/Vision boundary stays sharp.

---

## 8. Capacity-vs-estimate accountancy

| Sprint | Stories | Sum of estimates (d) | Effective capacity (d) | Buffer | Notes |
|---|---|---|---|---|---|
| 1 | A.1, E.1 | 6 (5 + 1) | 5 | -1 | Overrun absorbed because A.1's APU-emu spike lives inside the L estimate |
| 2 | A.2, A.3, D.1 | 3 (1 + 1 + 1) | 5 | +2 | Buffer for overflow from sprint 1 |
| 3 | A.4, A.5 | 7 (5 + 2.5) | 5 | -2 | **Highest-risk sprint.** Pre-sprint-3 spike absorbs A.4 uncertainty |
| 4 | B.1, B.2, A.6 | 6 (2.5 + 2.5 + 1) | 5 | -1 | A.6 slides to sprint 5 if needed |
| 5 | B.3, B.4, B.5 | 7 (2.5 + 2.5 + 1) | 5 | -2 | Local-only audits (M-4 resolution) keep B.4 at M, not L |
| 6 | C.1, C.2, C.3 | 7.5 (2.5 × 3) | 5 | -2.5 | Slips C.3 (mapper-66 experimental) to sprint 7 if needed; not on critical path |
| 7 | D.2, D.3, D.4, D.5, C.4 | 7 (2.5 + 1 + 2.5 + 1 + 1) | 5 | -2 | Most-stories sprint; mostly polish, low individual risk |
| 8 | E.2, E.3, release | 3 (1 + 1 + 1) | 5 | +2 | **Slack sprint** — absorbs prior overruns. Tag `v0.5.0` only when sprint 8 is comfortable |
| **Total** | **23 + release** | **46.5 d** | **40 d** | **-6.5** | Total deficit of ~6.5 dev-days = ±1.3 sprints. Within ±30% confidence band |

**If total slips by > 1.5 sprints (8 dev-days):** trigger re-planning via `bmad-correct-course` (CC). Consider deferring epic D's lowest-impact stories (D.5 shell completion, D.3 `--debug`) to v0.5.1 to land MVP.

---

## 9. Story-creation order (input to `bmad-create-story` / CS)

The exact order in which stories should be authored by `bmad-create-story` (CS). Each call to CS produces a `_bmad-output/implementation-artifacts/stories/<story-id>.md` story file with full context for `bmad-dev-story` (DS).

```
1.  A.1   ← start here (next CS target)
2.  E.1
3.  A.2
4.  A.3
5.  D.1
    ── Capcom RE spike (2 dev-days, time-boxed; not a story) ──
6.  A.4
7.  A.5
8.  B.1
9.  B.2
10. A.6
11. B.3
12. B.4
13. B.5
14. C.1
15. C.2
16. C.3
17. D.2
18. D.3
19. D.4
20. D.5
21. C.4
22. E.2
23. E.3
    ── v0.5.0 tag ──
```

**Story-file naming convention.** `_bmad-output/implementation-artifacts/stories/<id>.md` (e.g. `stories/A.1.md`, `stories/B.4.md`). Stories that split (e.g. A.4a / A.4b under risk R-S3-1) get suffix files (`A.4a.md`, `A.4b.md`).

---

## 10. Sign-off & Next Action

This sprint plan is **READY for the sprint cycle.**

### Required next action

**Run `bmad-create-story` (CS) for story A.1.**

Input to CS: this file's §3 *Sprint 1*, the architecture's component table for A.1's modules, and the epics doc's full §A.1 spec.

Expected output: `_bmad-output/implementation-artifacts/stories/A.1.md` — a full story file with implementation-ready spec, AC test fixtures listed, and the cross-cutting scaffold's file-level outline.

After A.1's story file exists: status `A.1` to **READY** in §4, then `bmad-dev-story` (DS) picks up A.1 and produces the implementation.

### Optional pre-sprint-1 action

Smoke-test the dev environment:

```bash
cd /home/jojokes/Documents/programmation/projets/autres/qlnes
python3.11 -m venv .venv-mvp && source .venv-mvp/bin/activate
pip install -r requirements.txt
mkdir -p bin && gcc -O2 -o bin/ql6502 vendor/QL6502-src/*.c
fceux --help >/dev/null 2>&1 && echo "✓ fceux on PATH"  # required for A.1
python -m qlnes --help                                   # smoke
pytest tests/ -x                                         # baseline green
```

If anything in this smoke-test fails, that's the first impediment to unblock — log it as the first entry of §6 *Retrospective Log* under "Pre-sprint-1 setup".

### Sign-off line

This sprint plan implements the readiness pass-2 verdict's CONDITIONAL_GO. The required H-1 fix has been applied (epics-and-stories.md §A.2 AC2 corrected). The 4 Medium findings are folded into per-sprint dev-note amendments (M-1 in sprint 2, M-2 in sprint 3, M-3 in sprint 3 spike, M-4 in sprint 5 dev notes). The 6 Low findings are deferred to maintainer's convenience.

**Plan author:** Claude (Opus 4.7), acting as `bmad-sprint-planning` (SP).
**Date:** 2026-05-03 (afternoon session, post-readiness-pass-2).
**Next BMad action:** `bmad-create-story` (CS) for `A.1`.

---

*End of Sprint Plan & Status — qlnes Music-MVP (v1, 2026-05-03)*
