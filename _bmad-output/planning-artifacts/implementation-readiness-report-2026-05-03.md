---
stepsCompleted: ['step-01-document-discovery', 'step-02-prd-analysis', 'step-03-epic-coverage-validation', 'step-04-ux-alignment', 'step-05-epic-quality-review', 'step-06-final-assessment']
completedAt: '2026-05-03'
filesIncluded:
  prd: '_bmad-output/planning-artifacts/prd.md'
  architecture: null
  epics: null
  ux: null
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
---

# Implementation Readiness Assessment Report

**Date:** 2026-05-03
**Project:** qlnes

## Document Inventory

### PRD Files Found

**Whole Documents:**
- `_bmad-output/planning-artifacts/prd.md` (~31 KB, modified 2026-05-03) ✓

**Sharded Documents:** none

### Architecture Files Found

**Whole Documents:** none
**Sharded Documents:** none

### Epics & Stories Files Found

**Whole Documents:** none
**Sharded Documents:** none

### UX Design Files Found

**Whole Documents:** none
**Sharded Documents:** none — N/A (CLI tool, no UX layer)

## PRD Analysis

### Functional Requirements

The PRD defines **40 numbered functional requirements** (FR1–FR40), each tagged with a scope tier (`[Existing]` / `[MVP]` / `[Growth]` / `[Vision]`), grouped into 6 capability areas.

| Capability area | FR range | Count | Phase mix |
|---|---|---|---|
| 1. ROM Ingestion & Static Analysis | FR1–FR4 | 4 | 4 Existing |
| 2. Audio Extraction (MVP focus) | FR5–FR12 | 8 | 7 MVP, 1 Growth |
| 3. Code & Asset Round-Trip | FR13–FR16 | 4 | 2 Existing, 1 Growth, 1 Vision |
| 4. Equivalence Verification & Coverage Reporting | FR17–FR26 | 10 | 1 Existing, 9 MVP |
| 5. Configuration & Invocation Surface | FR27–FR32 | 6 | 4 MVP, 1 Growth, 1 Vision |
| 6. Scripting & Robustness Contract | FR33–FR40 | 8 | 8 MVP |

**MVP-tagged FRs (count = 28):** FR5–FR11, FR18–FR30, FR33–FR40. These are the FRs that must be implementable from this PRD without further requirements work. **Growth-tagged FRs (count = 3):** FR12, FR15, FR31. **Vision-tagged FRs (count = 2):** FR16, FR32. **Existing-tagged FRs (count = 7):** FR1–FR4, FR13, FR14, FR17.

Each FR is implementation-agnostic, single-actor (`User can …`), and testable. No FR contains subjective adjectives ("fast", "easy", "user-friendly"), and no FR leaks implementation choices (no library names, no internal class structure).

### Non-Functional Requirements

The PRD defines **18 numbered NFRs** across 4 categories.

| Category | Range | Count | Quantified? |
|---|---|---|---|
| Performance | NFR-PERF-1 → NFR-PERF-5 | 5 | Yes — all five with explicit numeric budgets (2 s, ≤ 2× real time, 30 min, 100 ms, 500 MB) |
| Reliability & Determinism | NFR-REL-1 → NFR-REL-5 | 5 | Yes — invariants (byte-identical, no-timestamp-by-default) and exit-code-anchored crash policy |
| Portability | NFR-PORT-1 → NFR-PORT-4 | 4 | Yes — Linux canonical, macOS Growth-tier, Windows deferred, Python ≥ 3.11 |
| External Dependencies | NFR-DEP-1 → NFR-DEP-4 | 4 | Yes — FCEUX is the only hard external, `cynes` feature-gated, `requirements.txt` floor-pinned |

NFR coverage notes:
- **Security** — explicitly assessed and ruled non-applicable (no auth, no PII, no network surface). This is a documented exclusion, not a gap.
- **Scalability** — explicitly out of scope (single-user CLI).
- **Accessibility** — explicitly out of scope (no UI).
- **Integration** — explicitly N/A beyond the dependency NFRs.

### Additional Requirements & Constraints

The PRD also enshrines the following non-numbered, but binding, requirements that an architect must honor:

- **Equivalence-invariant table** (Success Criteria → Technical Success). Each artifact (NSF, MP3/WAV, ASM, CHR, gameplay data) has a defined invariant and a defined verification method. These are tighter than any FR — they are *correctness contracts*.
- **Reference emulator: FCEUX**, locked. Re-anchoring is allowed but must be a versioned, explicit event recorded in `bilan.json`.
- **Test corpus** — versioned `.nes` ROM set covering each supported mapper, with FCEUX reference outputs for every ROM. A release ships for a mapper only if every invariant passes for every corpus ROM of that mapper.
- **`bilan.json` schema** — versioned, machine-generated, single source of truth for the coverage matrix.
- **Layered configuration model** — defaults → `qlnes.toml` → `QLNES_*` env vars → CLI flags. Each layer overrides the previous one.
- **Exit-code table** — 12 codes mapped to sysexits.h plus a qlnes-specific extension range (`100`/`101`/`102`).
- **Negative scope (binding exclusions):** no public Python API in MVP, no interactive REPL in MVP, no Windows support in MVP, no GUI ever, no app-store distribution ever.

### PRD Completeness Assessment

**Strengths.**

- High requirement density: every FR/NFR carries weight; no filler.
- Explicit phasing on every FR — an architect can scope MVP work without ambiguity.
- Quantified NFRs across all four applicable categories.
- Negative space documented (what is *not* in scope) — closes off scope-creep ambiguity.
- Single-source-of-truth artifacts named (`bilan.json`, the test corpus) — no parallel sources to drift.
- Failure modes mapped to specific exit codes, removing implementer judgment calls.

**Gaps an architect will need to close (not PRD blockers, but to flag).**

1. **Test corpus composition is referenced but not enumerated.** Which ROMs ship in the corpus? Where do they live? How are they distributed (legal IP for commercial ROMs is non-trivial)? — *Architecture concern.*
2. **Song-table detection mechanism is implicit.** FR10 says "qlnes walks the song-pointer table exhaustively"; the PRD does not specify whether table location is auto-detected per-engine, configured per-ROM, or supplied by user. — *Architecture concern.*
3. **NSF format version not specified.** FR5 references "a single `NSF` file" but does not pin NSF v1, NSF v2, or NSFe. Bankswitching expansion-audio mappers (MMC5, VRC6) need NSF v2 or NSFe. — *Architecture concern, may surface during MMC5 Growth work.*
4. **APU emulation backend not specified.** FR11 says PCM output is sample-identical to FCEUX, but the PRD does not say *how* qlnes synthesizes its PCM — own APU emulator, port of someone else's, or FCEUX as both reference and renderer? — *Architecture concern, central to delivering MVP.*
5. **Loop-boundary detection** (FR6, FR10) is not specified. Some NES audio engines use sentinel bytes; some loop forever; some have explicit length. — *Architecture concern.*
6. **`requirements.txt` vs `qlnes.toml` ownership.** New deps will accrue (audio encoding libs for MP3 — likely `lameenc` or similar). `requirements.txt` is the project's dep manifest today; the PRD does not say if that stays canonical. — *Architecture concern.*

**No PRD-level gaps blocking architecture work.** All gaps above are appropriately deferred to architecture/design — they are *design decisions*, not requirements gaps.

## Epic Coverage Validation

### Coverage Matrix

| FR Number | PRD Requirement (summary) | Epic Coverage | Status |
|---|---|---|---|
| FR1–FR40 | All 40 FRs from the PRD | **No epics document exists yet** | ⚠️ Cannot validate |

### Coverage Statistics

- **Total PRD FRs:** 40
- **FRs covered in epics:** 0 (no epics document exists)
- **Coverage percentage:** N/A — measurement is impossible without an epics document

### Assessment

This step's purpose is to validate that every PRD FR has at least one epic/story tracing to it. The check is **structurally impossible** at this point because the epics-and-stories artifact has not been created yet.

This is **not a PRD failure** — the epics workflow follows architecture in the BMad pipeline, and architecture itself has not been started. The expected sequence from here is: Architecture → Epics & Stories → Stories → Implementation. Coverage validation makes sense after epics exist; running it now would be premature.

**Recommendation deferred to the final assessment:** re-run this readiness check after `/bmad-create-epics-and-stories` produces an epics artifact, at which point a real coverage matrix can be built (28 MVP FRs need explicit epic/story coverage; 3 Growth FRs and 2 Vision FRs are intentionally out of MVP epic scope).

## UX Alignment Assessment

### UX Document Status

**Not Found — and explicitly N/A by product design.**

The PRD is unambiguous on this: `qlnes` is a CLI tool with no UX layer. From the *Project-Type Overview* section: *"Each invocation is fire-and-forget … No public Python API. The CLI surface — commands, flags, exit codes, structured `stderr` error prefixes — is the project's only stable public contract."* From the *Implementation Considerations* section: *"`visual_design`, `ux_principles`, `touch_interactions`, `store_compliance` are intentionally not part of this product (CLI tool, no GUI, no app store)."*

### "Implied UX" check

A UX document is *implied* only if the product has a user interface. `qlnes` does not. The closest things to UX surfaces are:

- **CLI ergonomics** — the *Configuration & Invocation Surface* and *Scripting & Robustness Contract* sections of the PRD already specify command structure, flag semantics, exit codes, and error formatting. These are the *equivalent* of UX specs for a CLI: they pin the user-visible behaviour. They are PRD-resident, not UX-document-resident, and that is appropriate for a CLI.
- **Output artifact format** — `STACK.md`, `bilan.json`, annotated ASM, NSF/MP3/WAV file naming. All specified in the PRD (Success Criteria, FR9, FR21, FR25 and the `bilan.json` schema block).
- **REPL** — explicitly Vision-tier (`[Vision]`/FR32) and not in MVP. If/when that lands, a small UX spec for the interactive surface may be warranted; out of scope for this readiness check.

### Alignment Issues

None applicable — there is no UX artifact to misalign with the PRD or with an absent architecture.

### Warnings

- **No warning to issue.** The PRD's CLI-only positioning is explicit, justified by the product type, and the user-visible behaviour is fully specified inside the PRD itself. Skipping a UX document is *correct* here, not a gap.

## Epic Quality Review

### Status

**No epics document exists yet.** Epic quality review is structurally impossible at this point.

### What this step would normally check

Per the create-epics-and-stories standards, this review would catch:

- 🔴 **Critical** — technical epics with no user value (e.g. "Setup the APU emulator"), forward dependencies between epics, epic-sized stories that cannot be independently completed.
- 🟠 **Major** — vague acceptance criteria, stories that require future stories, database/state creation upfront instead of just-in-time.
- 🟡 **Minor** — formatting inconsistencies, traceability documentation gaps.

### Pre-emptive guidance for when epics are authored

To accelerate the eventual epic-creation pass and pre-empt the most common violations, the following observations from the PRD are worth recording now:

1. **Strong candidate epics, user-value-shaped, derivable from the PRD's MVP capability areas:**
   - *Get music out of a ROM* — covers FR5–FR11 (the audio extraction commands), traceable to Marco's and Sara's journeys.
   - *Validate that audio matches the original* — covers FR18 (`verify --audio`), FR11 (FCEUX-anchored sample equivalence).
   - *Run an audit and read the coverage matrix* — covers FR19–FR26 (the `audit` and `coverage` commands and `bilan.json`).
   - *Configure qlnes for my project* — covers FR27–FR30 (layered config, shell completion).
   - *Use qlnes safely from a script* — covers FR33–FR40 (exit codes, atomic writes, JSON stderr, `--strict`, `--force`, `--debug`).
2. **Anti-patterns to avoid when epic-writing.** Under no circumstance should an epic read like:
   - "Build the APU emulator" — implementation milestone, no user value.
   - "Set up the test corpus" — supporting work, must be embedded in user-value epics, not stand alone.
   - "Refactor cli.py" — pure refactor, not a user-facing capability.
3. **Independence constraint.** The PRD's phasing already enforces this: every MVP-tagged FR can be implemented without any Growth or Vision capability, by construction. Epics that follow the FR phase tags inherit this property for free.
4. **Brownfield context.** `qlnes` is brownfield (per the PRD classification). Epic 1 should not be "Set up initial project from starter template" — that work is already done. Instead, Epic 1 should be a user-value epic that integrates with the existing pipeline.
5. **Existing-tier FRs (FR1–FR4, FR13, FR14, FR17) need no epics** — they are documented as already-shipped. Epic creation should focus on the 28 MVP FRs.

### Findings

- 🔴 Critical violations found: **0** (no epics to violate standards yet).
- 🟠 Major issues found: **0**.
- 🟡 Minor concerns found: **0**.
- ⚠️ **Re-run this step after `/bmad-create-epics-and-stories` produces an epics artifact.**

## Summary and Recommendations

### Overall Readiness Status

**READY for Architecture work. NOT YET READY for direct implementation (because epics do not exist yet — that is expected at this point in the BMad pipeline).**

The PRD is **internally complete and self-consistent**. There are no PRD-level gaps that an architect would need to bounce back to product. The downstream artifacts (architecture, epics, stories) simply have not been authored yet, which is the expected state immediately after PRD completion. This readiness check found:

- **0 critical issues** in the PRD itself.
- **0 alignment issues** (no other artifacts to misalign with).
- **0 quality violations** (no epics to violate quality rules yet).
- **6 design questions** for the architecture phase to close (see *PRD Completeness Assessment*).

### What's strong about this PRD

- **Strict-equivalence quality bar is unambiguous.** "100%, not 99%, partial passes block release" — leaves no room for interpretive drift downstream.
- **Phase tags on every FR** make MVP/Growth/Vision boundaries machine-readable. An architect can scope MVP without negotiation.
- **Negative space is documented.** "No public Python API", "no GUI", "no Windows in MVP" close off scope-creep ambiguity.
- **Single sources of truth named** (`bilan.json`, the test corpus, the FCEUX reference). No duplicate-state drift to manage.
- **Failure modes are exit-coded** (sysexits-aligned table). Implementers do not invent their own error model.
- **Solo-developer constraint** is acknowledged in the scoping; the phasing is sized accordingly.

### Critical Issues Requiring Immediate Action

**None.** No PRD-level rework is required before starting architecture.

### Architecture-Phase Open Questions (not blockers, but to close during `/bmad-create-architecture`)

These are *design decisions* the PRD intentionally did not pre-empt; they belong in architecture, not in a revised PRD.

1. **APU emulation backend** — own implementation, port of existing OSS, or use FCEUX itself as both reference and renderer? Central to delivering the FR11 sample-equivalence promise.
2. **Test corpus composition and distribution.** Which `.nes` ROMs ship with the repo? IP/legal handling? FCEUX reference outputs are derived data — can they be committed instead of (or alongside) the ROMs?
3. **Song-table detection mechanism.** Per-engine handlers (KGen, FT, Capcom, etc.), heuristic auto-detection, or per-ROM configuration? FR10 ("exhaustive song-table walk") needs this resolved.
4. **NSF format version.** v1 / v2 / NSFe? Pinned by capability, since expansion-audio mappers (MMC5, VRC6) need v2 or NSFe. Affects FR5.
5. **Loop-boundary detection algorithm.** FR6 / FR10 promise loop-aware output. Engine-specific sentinels vs heuristic detection vs explicit per-ROM override.
6. **MP3 encoder library choice.** New dependency for FR7. `lameenc` / `pydub` / others. Affects `requirements.txt` and NFR-DEP-2.

### Recommended Next Steps

1. **Run `/bmad-create-architecture`** to address the 6 open architecture questions above. The PRD is the input; the architecture document is the output. Particular attention required on items 1 (APU backend) and 2 (test corpus IP/distribution) — these are the highest-impact unknowns.
2. **After architecture is approved, run `/bmad-create-epics-and-stories`** to convert the 28 MVP-tagged FRs into a backlog. Use the pre-emptive guidance in *Epic Quality Review → Pre-emptive guidance* above to avoid the most common epic-shape violations (technical-milestone epics, forward dependencies).
3. **After epics exist, re-run `/bmad-check-implementation-readiness`** to actually validate FR-to-epic traceability and epic quality. Steps 3 and 5 of this readiness skill will then produce real findings rather than the structural N/A they produced today.
4. **Establish the test corpus and FCEUX reference outputs early.** Several invariants and 28 of the 40 FRs depend on the corpus existing. This work blocks meaningful audio implementation regardless of how the architecture is sliced — schedule it in the first epic.
5. **Resolve the IP question for the test corpus before publishing anything.** Even Growth-tier distribution (`pip install qlnes`) must not redistribute commercial ROMs. Plan for ROM-hash-only references plus user-supplied ROM paths.

### Final Note

This assessment identified **0 PRD defects** and **6 architecture-phase open questions** across **2 substantive evaluation categories** (PRD Analysis, Pre-emptive Epic Guidance). Three of the six standard categories (Epic Coverage, Epic Quality, UX Alignment) yielded structural N/A because the corresponding artifacts do not exist yet — which is the expected state immediately after PRD completion. The PRD is ready to feed architecture work. Address the 6 design questions during `/bmad-create-architecture`, not by amending the PRD.

**Assessor:** Claude (Opus 4.7), acting as PM-readiness validator.
**Date:** 2026-05-03.
