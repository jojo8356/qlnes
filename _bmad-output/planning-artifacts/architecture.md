---
stepsCompleted: ['step-01-init', 'step-02-context', 'step-03-starter']
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
  - _bmad-output/project-context.md
documentCounts:
  prd: 1
  ux: 0
  research: 0
  projectDocs: 1
  readinessReport: 1
projectMemoriesReferenced:
  - project_cli_only_no_public_api.md
  - project_audio_architecture_decisions.md
workflowType: 'architecture'
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
---

# Architecture Decision Document — qlnes

**Author:** Johan
**Date:** 2026-05-03

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements (40 total).** Six capability areas span 4 phase tiers (`Existing` / `MVP` / `Growth` / `Vision`):

| Area | FR range | MVP load |
|---|---|---|
| 1. ROM Ingestion & Static Analysis | FR1–FR4 | 0 new (4 already shipped) |
| 2. Audio Extraction | FR5–FR12 | **7 new MVP capabilities + 1 Growth** |
| 3. Code & Asset Round-Trip | FR13–FR16 | 0 new (existing + 1 Growth + 1 Vision) |
| 4. Equivalence Verification & Coverage | FR17–FR26 | **9 new MVP capabilities** |
| 5. Configuration & Invocation Surface | FR27–FR32 | **4 new MVP** + 1 Growth + 1 Vision |
| 6. Scripting & Robustness Contract | FR33–FR40 | **8 new MVP capabilities** |

Architecture must deliver **28 MVP FRs**, integrate with the 7 already-shipped FRs, and expose extension seams for the 3 Growth + 2 Vision FRs without designing them in detail.

**Non-Functional Requirements (18 total).** Quantified across 4 categories:

- **Performance** — 5 budgets (analyze < 2 s; audio render ≤ 2× real time; audit < 30 min on a 50-ROM corpus; coverage cache hit < 100 ms; peak RAM < 500 MB).
- **Reliability & Determinism** — 5 invariants (byte-identical PCM canonical hash target; no wall-clock / hostname / username in outputs; deterministic parallelism; atomic writes; crash-free on the supported corpus).
- **Portability** — Linux canonical, macOS Growth, Windows deferred, Python ≥ 3.11.
- **External Dependencies** — FCEUX as the only hard external in MVP; `cynes` feature-gated; `requirements.txt` floor-pinned; new hard external deps require PRD update.

### Architectural Locks (already decided — see project memory)

These six decisions were made before this architecture phase, are recorded in the PRD `amendmentLog`, and are inputs to architecture, not questions:

1. **APU emulation** — own implementation, not a port and not a binding to an existing emulator. FCEUX is the *oracle*, not the renderer.
2. **Test corpus** — local-only; the repo references ROMs by SHA-256 only and never ships ROM bytes. FCEUX reference outputs follow the same rule.
3. **Song-table detection** — per-engine handlers via `SoundEngine` ABC, plus a generic fallback that produces tier-2 (frame-accurate) output tagged `unverified`. Top-10 engines targeted in MVP+Growth.
4. **NSF output format** — NSF2 with embedded NSFe metadata chunks (`tlbl`, `time`, `fade`, `auth`, `plst`).
5. **Loop-boundary detection** — 3-tier (engine bytecode opcode → APU-write fingerprint → never PCM autocorrelation as primary).
6. **MP3 encoder** — `lameenc`, pinned `==`. Subprocess `lame` as fallback.

These decisions cascade into specific component shapes (an `ApuEmulator` module, a `SoundEngine` plugin registry, an `NsfWriter` that supports v2 + NSFe chunks, etc.) that this architecture document will pin.

### Scale & Complexity

- **Primary technical domain:** CLI tool + developer toolkit operating on binary file formats and emulating cycle-accurate hardware semantics.
- **Complexity level:** **high (technical)**, **low (operational)**. Operationally there is no multi-tenancy, no auth, no database, no real-time, no network surface. Technically this is several emulator-grade subsystems composed together with strict equivalence invariants and 100%-or-nothing pass criteria — that combination is unusual outside emulator projects themselves.
- **Estimated architectural component count:** **~17** (≈7 already shipped, ≈10 new for the music-MVP). Detailed breakdown deferred to the Patterns & Components steps.

### Technical Constraints & Dependencies

- **Brownfield baseline.** The existing pipeline (`Rom`, `RomProfile`, static disassembly via vendored `vendor/QL6502-src/`, asset extraction, round-trip via `py65`, optional dynamic discovery via `cynes` for mapper 0) must stay green. New audio code attaches to it without forking the run-as-module entry point.
- **Solo developer.** Phasing must be sliceable per engine; "ship Capcom before Konami" must not require an Konami-shaped scaffold to exist first. The plugin system is the lever.
- **CLI-only public contract.** Internal Python modules may be refactored at any time. Module boundaries inside the architecture serve internal clarity, not external stability. (This is a strong signal — over-engineered facade layers are a smell here.)
- **Linux MVP only.** Simplifies subprocess behaviour for FCEUX, audio device handling for capture, and shell-completion install paths.
- **Python ≥ 3.11.** Modern typing (`match`, generic `TypeAlias`, `typing.Self`) is available and should be used; no need for `typing_extensions` shims.
- **FCEUX is the oracle.** Subprocess invocation with deterministic flags; audio capture via Lua scripting (`audio_trace.lua` already exists as a starting point). Re-anchoring is allowed but is a versioned event recorded in `bilan.json`.

### Cross-Cutting Concerns

These will repeat in nearly every component and need a single canonical implementation each, surfaced as utility modules / decorators / mixins:

1. **Determinism discipline** (NFR-REL-1, NFR-REL-2, NFR-REL-3). Every output writer must avoid wall-clock, hostnames, random sources, and non-deterministic iteration order. JSON serialization uses sorted keys; filenames hash from canonical inputs only.
2. **Atomic file writes** (FR35). One shared helper used by every output path: write to sibling `.tmp`, `os.fsync`, then `os.replace`.
3. **Pre-flight validation** (FR36). Every command runs its own pre-flight predicate before any output is touched. Failures exit before the first byte is written.
4. **Sysexits-aligned exit codes + structured JSON `stderr`** (FR33, FR34). One central error-emission module that every command routes through; never raise raw `SystemExit` mid-flow.
5. **Tiered fidelity tagging** (FR11 post-amendment). Every audio output carries a `tier ∈ {1, 2, 3}` annotation that flows into `bilan.json` and into per-track NSFe metadata.
6. **`bilan.json` as the single source of truth for coverage** (FR19–FR26). One schema, one writer, one reader, schema-versioned; never hand-edited.
7. **Layered config resolution** (FR27–FR29). One resolver consumed by every command; per-command sub-section names match command names.

## Starter Template Evaluation

### Primary Technology Domain

CLI tool + developer toolkit (Python). No web stack, no mobile stack, no full-stack — `cli_tool` per the PRD classification.

### Starter Options Considered

**None applied.** The project is brownfield and the technology stack is already fully determined by (a) the existing codebase, (b) the PRD's *Project-Type Requirements* section, and (c) the six locked architecture decisions in project memory. Re-running a starter scaffold over a brownfield codebase with established conventions would be regression, not progress.

The de-facto "starter equivalent" is the union of:

- **Existing project layout** (in repository as of commit `c8fbc8f`):
  - `qlnes/` Python package, run as module via `python -m qlnes`
  - `qlnes/cli.py` — Typer entry point, no auto-completion (toggled on in MVP per FR30)
  - `qlnes/{rom,profile,parser,dataflow,ines,nes_hw,…}.py` — existing static-analysis modules
  - `vendor/QL6502-src/` — vendored C disassembler, built to `bin/ql6502`
  - `requirements.txt` — floor-pinned dependencies
  - `.gitignore` — already excludes ROM-derived artifacts and local config
  - `LICENSE` (MIT) and `README.md`
- **PRD-locked stack** (from *Project-Type Requirements* and NFRs):
  - Python ≥ 3.11
  - Typer for CLI
  - `py65` for 6502 reassembly (existing)
  - `cynes` feature-gated for dynamic discovery (existing)
  - `Pillow` for PNG export (existing)
  - **`lameenc` (pinned `==`)** for MP3 (new — Q6 decision)
  - FCEUX as oracle, invoked via subprocess (new — Q1/Q2/research-locked)
  - No `pyproject.toml` / no PyPI publication in MVP (FR31 deferred to Growth)
- **Cross-cutting utility modules to be added** (new — derived from the cross-cutting concerns identified in step 2):
  - `qlnes/io/atomic.py` — atomic-write helper used by every output writer
  - `qlnes/io/errors.py` — sysexits exit-code emitter + structured JSON `stderr`
  - `qlnes/io/preflight.py` — pre-flight predicate runner
  - `qlnes/config/loader.py` — 4-layer resolver
  - `qlnes/audit/bilan.py` — `bilan.json` schema, writer, reader, freshness check
  - `qlnes/det.py` — determinism utilities (canonical JSON, sorted iteration, deterministic-hash filename helpers)

### Selected Starter

**N/A — extend the existing project.** No starter command to run. Project initialization stories are not the right *first* implementation story for this brownfield codebase; the right first story is *"Add the cross-cutting utility modules listed above and migrate `cli.py` to route every command through them"*. That story unblocks every other epic without introducing user-facing capability, which means it is **infrastructure work that must be embedded inside a user-value story** (per the epic-quality guidance from the readiness report) — likely "Get music out of a ROM" / Marco's journey.

### Initialization Command

There is no fresh-project bootstrap command. The setup procedure for a new contributor (or a fresh CI environment) is:

```bash
git clone https://github.com/jojo8356/qlnes.git
cd qlnes
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p bin && gcc -O2 -o bin/ql6502 vendor/QL6502-src/*.c
./scripts/install_audio_deps.sh   # FCEUX + lame fallback (when relevant)
```

This is the existing flow; the architecture work does not change it for MVP.

### Architectural Decisions Already Provided by the Brownfield Baseline

- **Language & Runtime:** Python ≥ 3.11, no compiled-language ports for MVP.
- **CLI framework:** Typer (already chosen, in `cli.py`).
- **Code organization:** flat module layout under `qlnes/`. Sub-packages introduced in this PRD's MVP work (`qlnes/audio/`, `qlnes/audit/`, `qlnes/config/`, `qlnes/io/`) — design covered in step 6 (Repository Structure).
- **Testing framework:** *Not yet established.* No `tests/` directory exists in the brownfield baseline. CI runs only `deptry` weekly. Test-framework selection is a new decision for step 4 — the equivalence-invariant test harness (FR19, FR26) needs an actual runner. **Provisional orientation: `pytest`** (ecosystem dominant, fixture-rich, no compelling reason to deviate); to be formally pinned in step 4.
- **Linting / formatting:** *Not enforced today* (no `.ruff.toml`, no `.flake8`, no `mypy.ini`). Per *project-context.md* style is "informal but consistent". Whether to formalize this is a step-4 decision.
- **Build tooling:** Vendored C compile via `gcc -O2`, run-as-module Python. No bundler, no transpiler.
- **Project structure:** see step 6.
- **Development experience:** virtualenv + `python -m qlnes`. No hot-reload needed for a fire-and-forget CLI.
