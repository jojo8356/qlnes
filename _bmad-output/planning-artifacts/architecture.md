---
stepsCompleted:
  - 'step-01-init'
  - 'step-02-context'
  - 'step-03-starter'
  - 'step-04-tech-stack'
  - 'step-05-component-architecture'
  - 'step-06-repository-structure'
  - 'step-07-cross-cutting'
  - 'step-08-apu-emulator'
  - 'step-09-sound-engine-plugins'
  - 'step-10-fceux-oracle'
  - 'step-11-test-corpus'
  - 'step-12-data-models'
  - 'step-13-testing-strategy'
  - 'step-14-cicd'
  - 'step-15-nfr-mapping'
  - 'step-16-risks'
  - 'step-17-decision-log'
  - 'step-18-phasing'
  - 'step-19-sign-off'
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
  - _bmad-output/project-context.md
documentCounts:
  prd: 1
  ux: 1
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

## Technology Stack & Dependencies

This step pins the full stack and closes Q4 (NSF format), Q6 (MP3 encoder), and the testing-framework decision teased in step 3. Q1 (APU backend), Q3 (song-table detection), and Q5 (loop-boundary detection) were already locked in project memory and are designed in detail in steps 8–9.

### Stack — locked

| Concern | Choice | Pin | Rationale |
|---|---|---|---|
| Language | Python | `>=3.11` | Existing baseline; modern typing (`match`, `Self`, generic `TypeAlias`); free PEP-657 fine-grained tracebacks for `--debug`. |
| CLI framework | Typer | `>=0.12` (existing) | Already in `cli.py`; Click underneath; built-in shell-completion (FR30). |
| 6502 reassembly | `py65` | `>=1.2` (existing) | Proven on the existing round-trip path (FR13, FR17). No reason to switch. |
| 6502 disassembly (oracle) | Vendored `QL6502-src/` | gitref-pinned | Already vendored; built once via `gcc -O2` into `bin/ql6502`. |
| Dynamic discovery | `cynes` | `>=0.1.2` (existing), feature-gated | Mapper-0 only today (FR4); kept feature-gated so a missing `cynes` does not break the rest of the CLI (NFR-DEP-1). |
| PNG export | `Pillow` | `>=10` (existing) | Existing CHR-ROM → PNG path (FR14, FR15-Growth). |
| MP3 encoder | **`lameenc`** | **`==1.7.0`** (pinned `==`) | Closes Q6. Bundled libmp3lame, no system-`lame` required, deterministic per encoder version. The `==` pin makes byte-equivalence checks meaningful (NFR-REL-1). Subprocess `lame` is the documented fallback for MP3 if `lameenc` ever drops support for the host platform. |
| WAV writing | stdlib `wave` | n/a | RIFF is trivial; no third-party dep needed. |
| FCEUX (oracle) | system binary (subprocess) | `>=2.6.6` | Closes Q1's "FCEUX as oracle" half. Invoked headless with `--loadlua audio_trace.lua`. Version recorded in `bilan.json` provenance. |
| NSF output | hand-written writer (NSF2 + NSFe chunks) | n/a | Closes Q4. NSF2 (`version_byte=0x02`) supports MMC5/VRC6 expansion-audio bits we'll need at Growth tier; NSFe chunks (`tlbl`, `time`, `fade`, `auth`, `plst`) cover the per-track metadata UX §11.2 requires. No library exists with both. |
| Config | stdlib `tomllib` (3.11+) + custom `qlnes/config/loader.py` | n/a | TOML 1.0 is in the stdlib since 3.11; no need for `tomli`. |
| Atomic IO | stdlib `os.replace` + `os.fsync` + `tempfile` | n/a | Sufficient on POSIX (FR35); Windows portability is not MVP. |
| JSON | stdlib `json` with `sort_keys=True`, `separators=(",", ":")` | n/a | Determinism (NFR-REL-1, NFR-REL-2). The exact sort/separator pair becomes a project invariant — referenced by `qlnes/det.py`. |

### Dev / test stack — locked

| Concern | Choice | Pin | Rationale |
|---|---|---|---|
| Test framework | **`pytest`** | `>=8` | Closes step-3's provisional. Ecosystem standard; supports parametrization for engine × mapper × ROM matrices (the equivalence corpus). The few existing tests are vanilla `def test_*()` and migrate trivially. |
| Test layout | `pytest-xdist` | `>=3` | Parallel `audit` (NFR-PERF-3 — 50-ROM corpus < 30 min). Determinism preserved via PCM-hash compare, not bit-shift-by-shift order. |
| Test fixtures (audio) | per-ROM `tests/fixtures/audio/<sha>.wav` (FCEUX reference) | content-addressable | Files are referenced by SHA-256, identical to the corpus discipline. Generated by `scripts/generate_references.py` (new — step 11). |
| Coverage measurement | `coverage` `>=7` | n/a | Reports only. Not a release-gate (the equivalence corpus is the gate). |
| Lint | `ruff` `>=0.5` | n/a | Fast; no compelling reason for `flake8` + `isort` + `pycodestyle` separately. |
| Type check | `mypy` `>=1.10`, `--strict` on new modules only | n/a | Brownfield code stays warning-only; new MVP modules opt into `--strict` per directory via `mypy.ini` overrides. |
| Format | `ruff format` | n/a | Same tool, no `black` parallel install. |
| Dependency audit | `deptry` (existing weekly CI) | n/a | Already wired (`f320f05`, `291225a`). Catches floating dep declarations. |
| MP3 byte-check skip rule | tag `@pytest.mark.lameenc(version="1.7.0")` | n/a | Tests that compare MP3 bytes are skipped if `lameenc.__version__ != "1.7.0"`; PCM-hash tests run regardless. Documents the encoder-version coupling without hiding it. |

### `requirements.txt` — locked diff

```diff
 typer>=0.12
 py65>=1.2
 cynes>=0.1.2
 Pillow>=10
+lameenc==1.7.0
+# dev (in requirements-dev.txt to keep prod minimal):
+# pytest>=8
+# pytest-xdist>=3
+# coverage>=7
+# ruff>=0.5
+# mypy>=1.10
+# deptry>=0.16
```

A separate `requirements-dev.txt` keeps the runtime install footprint at five direct deps, all floor-pinned except `lameenc` (which is `==`-pinned for determinism). This honors NFR-DEP-1 (FCEUX as the only hard external — but FCEUX is a system binary, not a Python dep, so this stays consistent).

### What's intentionally NOT in the stack

- **`pyproject.toml` / Poetry / hatch / uv.** Out of MVP. `pip install qlnes` is FR31 (Growth). When that lands, it's a `pyproject.toml` migration story, not a Poetry adoption story.
- **`pydub` / `ffmpeg-python` / any ffmpeg dependency for the audio path.** The current `audio.py` uses `ffmpeg` for WAV→MP3 (`wav_to_mp3` in `audio.py:1-40`). **MVP migrates this off ffmpeg onto `lameenc`** — this is one of the first tech-debt items in epic A. Rationale: ffmpeg is a 400 MB system dep, `lameenc` is a 1.5 MB Python wheel with libmp3lame statically linked. Deterministic across hosts where ffmpeg isn't.
- **`numpy` / `scipy`.** Tempting for the synth path. Rejected: pure-Python int-arithmetic synth is fast enough at 44.1 kHz × 23 tracks (a 3-min track is ~8 M samples, ~2 s of int-arithmetic on the canonical hardware — well under the NFR-PERF-2 budget of `≤ 2× real time`). And: SciPy/NumPy add 50 MB of wheels, locale-dependent FFT determinism issues, and a soft-coupling to BLAS that complicates Linux-canonical reproducibility.
- **A Rust extension or PyO3 module.** Tempting for the APU emulator. Rejected for MVP: pure Python is fast enough (see profiling sketch in step 8); a Rust native module breaks `pip install qlnes` cleanly across distributions; once we know we need it (i.e. a real engine fails NFR-PERF-2), the APU emulator's pure Python implementation is *the* spec the Rust port would copy.
- **A database.** No persistent state across invocations except `bilan.json` (single file) and the test corpus directory. Adding SQLite for "caching" would invent failure modes (locking, corruption, schema migration) for negligible gain. `bilan.json` is the database.
- **A logging library (loguru, structlog, etc.).** Stdlib `logging` only, used sparingly. Most output is direct `typer.echo` to keep the formatting under our control (UX §5.4). Logging is for `--debug`-only internals.

## Component Architecture

### High-level component map

The architecture has **17 components**, of which 7 are already shipped (brownfield), 9 are net-new for the music-MVP, and 1 (`shell` REPL) is Vision-tier and explicitly out of MVP.

```
              ┌─────────────────────────────────────────────────────────┐
              │                   CLI surface (Typer)                   │
              │     analyze   recompile   verify   audio   nsf          │
              │                  audit    coverage                      │
              └───────┬─────────────┬───────────────┬───────┬───────────┘
                      │             │               │       │
              ┌───────▼─────┐ ┌─────▼──────┐ ┌──────▼────┐ ┌▼─────────┐
              │ pre-flight  │ │ config     │ │ errors    │ │ atomic   │
              │ runner      │ │ resolver   │ │ emitter   │ │ writer   │
              │ (cross-cut) │ │ (4 layers) │ │ (sysexits │ │ (FR35)   │
              └─────────────┘ └────────────┘ │ +JSON)    │ └──────────┘
                                              └───────────┘
              ┌────────────────────┬─────────────────────────────────┐
              │  Existing (brownfield)            │  New (MVP)        │
              ├────────────────────┼─────────────────────────────────┤
              │ Rom (ines.py)      │  ApuEmulator (qlnes/apu/*)       │
              │ RomProfile         │  SoundEngineRegistry              │
              │ QL6502 disasm      │  SoundEngine (ABC) + 4 plugins:   │
              │ AssetExtractor     │      famitracker, capcom,         │
              │ Recompiler (py65)  │      konami_kgen, generic_fallback│
              │ DynamicDiscovery   │  FceuxOracle (subprocess+Lua)     │
              │   (cynes, mapper0) │  AudioRenderer (engine→PCM→WAV)   │
              │ NsfWriter (v1, M0) │  NsfWriterV2 (NSF2 + NSFe chunks) │
              │                    │  Mp3Encoder (lameenc wrapper)     │
              │                    │  AuditRunner (corpus walker)      │
              │                    │  BilanStore (json schema)         │
              └────────────────────┴─────────────────────────────────┘
```

### Component table — what each does, where it lives, what it depends on

| # | Component | Status | Module | Depends on (project) | Depends on (external) |
|---|---|---|---|---|---|
| C1 | `Rom` (iNES parser) | existing | `qlnes/ines.py`, `qlnes/rom.py` | — | — |
| C2 | `RomProfile` (orchestrator) | existing, extended | `qlnes/profile.py` | C1, C3, C4, C5, C6 | — |
| C3 | QL6502 disassembler binding | existing | `qlnes/parser.py` + `vendor/QL6502-src/` | C1 | gcc, vendored C |
| C4 | Asset extractor (CHR→PNG) | existing | `qlnes/assets.py` | C1 | Pillow |
| C5 | Recompiler (ASM→.nes) | existing | `qlnes/recompile.py` | C3 | py65 |
| C6 | Dynamic discovery (cynes) | existing | `qlnes/profile.py` (M0 only) | C1 | cynes |
| C7 | NSF writer v1 (mapper-0) | existing | `qlnes/nsf.py` | C1 | — |
| C8 | **APU emulator** | **new (MVP)** | `qlnes/apu/` (pulse, tri, noise, dmc, mixer) | — | — |
| C9 | **Sound engine registry & ABC** | **new (MVP)** | `qlnes/audio/engine.py` | — | — |
| C9a | FamiTracker handler | new (MVP) | `qlnes/audio/engines/famitracker.py` | C9 | — |
| C9b | Capcom handler | new (MVP) | `qlnes/audio/engines/capcom.py` | C9 | — |
| C9c | Konami KGen handler | new (Growth) | `qlnes/audio/engines/konami_kgen.py` | C9 | — |
| C9d | Generic fallback handler | new (MVP) | `qlnes/audio/engines/generic.py` | C9 | — |
| C10 | **Audio renderer** | **new (MVP)** | `qlnes/audio/renderer.py` | C8, C9, C12 | — |
| C11 | **MP3 encoder wrapper** | **new (MVP)** | `qlnes/audio/mp3.py` | C10 | lameenc |
| C12 | **FCEUX oracle** | **new (MVP)** | `qlnes/oracle/fceux.py` + `qlnes/audio_trace.lua` | C1 | fceux (system binary) |
| C13 | **NSF writer v2 + NSFe** | **new (MVP)** | `qlnes/nsf2.py` (replaces C7 long-term) | C1, C9 | — |
| C14 | **Audit runner** | **new (MVP)** | `qlnes/audit/runner.py` | C2, C10, C12, C15 | pytest-xdist (test only) or stdlib `concurrent.futures` (runtime) |
| C15 | **Bilan store** | **new (MVP)** | `qlnes/audit/bilan.py` | — | — |
| C16 | **Config loader** (4-layer) | **new (MVP)** | `qlnes/config/loader.py` | — | tomllib (stdlib) |
| C17 | **Cross-cutting utilities** | **new (MVP)** | `qlnes/io/{atomic,errors,preflight}.py`, `qlnes/det.py` | — | — |

### Component contracts (interface-level)

Each new component exposes a small, named, typed interface. The interfaces are the architecture; the implementation details below are guidance.

```python
# qlnes/apu/__init__.py
class ApuEmulator:
    """Cycle-accurate 2A03 APU. Pulse1, Pulse2, Triangle, Noise (DMC stub for MVP)."""

    def __init__(self, sample_rate: int = 44_100) -> None: ...
    def write(self, register: int, value: int, cycle: int) -> None:
        """Schedule a register write at the given CPU cycle."""
    def render(self, until_cycle: int) -> bytes:
        """Render PCM samples up to (not including) `until_cycle`. Returns raw int16 LE."""
    def reset(self) -> None: ...

# qlnes/audio/engine.py
class SoundEngine(abc.ABC):
    """Base class for per-engine song-table walkers."""

    name: ClassVar[str]                 # e.g. "famitracker"
    tier: ClassVar[Literal[1, 2]]       # 1 = sample-equivalent, 2 = frame-accurate

    @abc.abstractmethod
    def detect(self, rom: Rom) -> DetectionResult: ...
    @abc.abstractmethod
    def walk_song_table(self, rom: Rom) -> list[SongEntry]: ...
    @abc.abstractmethod
    def render_song(self, rom: Rom, entry: SongEntry, oracle: FceuxOracle | None) -> PcmStream: ...
    @abc.abstractmethod
    def detect_loop(self, song: SongEntry) -> LoopBoundary | None: ...

# qlnes/oracle/fceux.py
class FceuxOracle:
    def __init__(self, fceux_path: str | None = None) -> None: ...
    def trace(self, rom: Path, frames: int) -> ApuTrace:
        """Run rom under fceux + audio_trace.lua, return APU register-write trace."""
    def reference_pcm(self, rom: Path, frames: int) -> bytes:
        """Return the FCEUX-rendered PCM, the equivalence reference."""

# qlnes/config/loader.py
@dataclass(frozen=True)
class ResolvedConfig:
    section: str   # "default", "audio", "verify", ...
    values: Mapping[str, Any]
    provenance: Mapping[str, Layer]   # which layer set each key
class ConfigLoader:
    def resolve(self, command: str, cli_overrides: Mapping[str, Any]) -> ResolvedConfig: ...

# qlnes/audit/bilan.py
class BilanStore:
    SCHEMA_VERSION: ClassVar[str] = "1"
    def read(self, path: Path) -> Bilan: ...           # validates schema
    def write(self, bilan: Bilan, path: Path) -> None: # atomic write
    def is_stale(self, bilan: Bilan, sources: list[Path]) -> bool: ...

# qlnes/io/atomic.py
def atomic_write_bytes(path: Path, data: bytes) -> None: ...
def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None: ...
def atomic_writer(path: Path) -> ContextManager[BinaryIO]: ...

# qlnes/io/errors.py
class QlnesError(Exception):
    code: int
    cls: str
    extra: dict[str, Any]
    hint: str | None = None
def emit(err: QlnesError, *, no_hints: bool = False, no_color: bool = False) -> NoReturn: ...

# qlnes/io/preflight.py
class Preflight:
    def __init__(self) -> None: ...
    def add(self, name: str, predicate: Callable[[], None]) -> None: ...
    def run(self) -> None:
        """Invoke each predicate; first raised QlnesError exits via emit()."""
```

These signatures are the architectural contract. Implementation evolves; signatures change only with a major version bump (per UX P4).

### Wiring diagram — `qlnes audio rom.nes --format wav` step-by-step

```
cli.audio()
  └─ ConfigLoader.resolve("audio", cli_kwargs)        ← 4-layer merge
  └─ Preflight.add(...)                                ← header valid, output writable, fceux on PATH
  └─ Preflight.run()                                   ← exits 64/65/66/73/70 here if anything fails
  └─ Rom.from_file(path)                               ← C1
  └─ RomProfile.from_rom(rom).analyze_static()         ← C2/C3
  └─ SoundEngineRegistry.detect(rom)                   ← C9 — returns FamiTracker (tier 1) or generic (tier 2)
  └─ engine.walk_song_table(rom)                       ← list of SongEntry
  └─ for each SongEntry:
        FceuxOracle.trace(rom, song)                   ← C12 — Lua-driven APU trace
        engine.render_song(rom, entry, oracle)         ← C8/C9 — APU emulator replays trace
        loop = engine.detect_loop(entry)
        wav = wrap_pcm_riff(pcm, loop)
        atomic_write_bytes(out_dir / filename, wav)    ← C17
  └─ stderr: ✓ N WAV écrits ...
```

The same wiring serves `--format mp3` (`C11.encode(pcm)` between `wrap_pcm_riff` and `atomic_write_bytes`) and `--format nsf` (`C13.write(rom, songs, out)` instead of per-track WAV emission).

## Repository Structure

### Target layout (after MVP work)

```
qlnes/                                  # repo root
├── _bmad/                              # BMad install — gitignored except customizations
├── _bmad-output/
│   └── planning-artifacts/             # PRD, UX, architecture, readiness, audit
├── bin/                                # built binaries — gitignored
│   └── ql6502
├── corpus/                             # test corpus — see step 11
│   ├── manifest.toml                   # per-ROM metadata, ROM-hash references only
│   └── references/                     # FCEUX-rendered PCM/WAV — see step 11
├── docs/                               # public docs (optional, for GitHub Pages)
│   ├── README.md
│   └── mapper-coverage.md              # auto-generated from bilan.json post-Growth
├── examples/                           # sample invocations, sample qlnes.toml
├── qlnes/                              # the package
│   ├── __init__.py                     # version, public name only
│   ├── __main__.py                     # `python -m qlnes` entry
│   ├── cli.py                          # Typer commands
│   ├── det.py                          # determinism utilities (sorted-json, sha256, …)
│   ├── ines.py                         # iNES header parsing (existing)
│   ├── rom.py                          # Rom dataclass (existing)
│   ├── profile.py                      # RomProfile orchestrator (existing, extended)
│   ├── parser.py                       # QL6502 disasm shellout (existing)
│   ├── ql6502.py                       # py65 reassembly (existing)
│   ├── recompile.py                    # round-trip recompile (existing)
│   ├── dataflow.py                     # static dataflow heuristics (existing)
│   ├── lang_detect.py                  # publisher/engine hints (existing)
│   ├── cross_ref.py                    # cross-reference graph (existing)
│   ├── annotate.py                     # ASM annotation (existing)
│   ├── asm_text.py                     # ASM rendering (existing)
│   ├── assets.py                       # CHR-ROM → PNG (existing)
│   ├── nes_hw.py                       # NES register name table (existing)
│   ├── ines.py                         # iNES (existing)
│   ├── audio_trace.lua                 # FCEUX Lua hook (existing, refined)
│   ├── apu/                            # NEW — APU emulator
│   │   ├── __init__.py                 # ApuEmulator
│   │   ├── pulse.py                    # PulseChannel × 2
│   │   ├── triangle.py
│   │   ├── noise.py
│   │   ├── dmc.py                      # stub for MVP, full in Growth
│   │   └── mixer.py                    # 2A03 nonlinear mixer
│   ├── audio/                          # NEW — engine plugins + renderer
│   │   ├── __init__.py
│   │   ├── engine.py                   # SoundEngine ABC, registry
│   │   ├── renderer.py                 # rendering pipeline
│   │   ├── mp3.py                      # lameenc wrapper
│   │   ├── wav.py                      # RIFF + 'smpl' loop chunk writer
│   │   └── engines/
│   │       ├── __init__.py
│   │       ├── famitracker.py
│   │       ├── capcom.py
│   │       ├── konami_kgen.py          # Growth
│   │       └── generic.py              # tier-2 fallback
│   ├── nsf2.py                         # NEW — NSF2 + NSFe writer (replaces nsf.py post-MVP)
│   ├── nsf.py                          # existing v1 writer; deprecated when nsf2.py covers M0
│   ├── oracle/                         # NEW — FCEUX subprocess + trace parsing
│   │   ├── __init__.py
│   │   └── fceux.py
│   ├── audit/                          # NEW — corpus walker, bilan store
│   │   ├── __init__.py
│   │   ├── runner.py
│   │   ├── bilan.py
│   │   └── corpus.py                   # corpus/manifest.toml reader
│   ├── coverage/                       # NEW — coverage CLI command formatting
│   │   ├── __init__.py
│   │   └── render.py                   # table + JSON formatters
│   ├── config/                         # NEW — 4-layer resolver
│   │   ├── __init__.py
│   │   └── loader.py
│   ├── io/                             # NEW — cross-cutting IO
│   │   ├── __init__.py
│   │   ├── atomic.py                   # atomic-write helper (FR35)
│   │   ├── errors.py                   # QlnesError + emitter (FR33, FR34)
│   │   └── preflight.py                # pre-flight runner (FR36)
│   └── emu/                            # existing — used by dynamic discovery
│       ├── __init__.py
│       ├── discover.py
│       └── runner.py
├── scripts/
│   ├── analyze_rom.py                  # existing helper
│   ├── install_audio_deps.sh           # existing — extended to pin lameenc
│   └── generate_references.py          # NEW — populate corpus/references/ from FCEUX
├── tests/
│   ├── conftest.py                     # corpus fixture, lameenc-version skip marker
│   ├── fixtures/                       # NEW: per-mapper sample ROMs, NSF references
│   │   └── ...                         # contents are SHA-named, never committed in raw
│   ├── invariants/                     # NEW — equivalence harness
│   │   ├── test_pcm_equivalence.py
│   │   ├── test_round_trip.py
│   │   ├── test_nsf_validity.py
│   │   └── test_determinism.py
│   ├── unit/                           # NEW — module-by-module unit tests
│   └── (existing test_*.py at top level migrate into unit/ or invariants/)
├── vendor/
│   └── QL6502-src/
├── .github/workflows/
│   ├── deptry.yml                      # existing
│   ├── test.yml                        # NEW — pytest on push/PR
│   └── audit.yml                       # NEW — full audit on tag, on schedule
├── qlnes.toml.example                  # NEW — documents the config schema
├── requirements.txt                    # floor-pinned runtime deps
├── requirements-dev.txt                # NEW — dev/test deps
├── mypy.ini                            # NEW — strict on new dirs only
├── ruff.toml                           # NEW — lint/format config
├── README.md                           # existing — refreshed with mapper-coverage badge
└── LICENSE
```

### Migration ordering — what moves first, second, third

The above structure is a target. Migrating to it happens in three waves, each landing in its own implementation story:

1. **Wave 1 — cross-cutting scaffolding** (story X-1, embedded in epic A's first vertical slice):
   - Add `qlnes/io/{atomic,errors,preflight}.py`, `qlnes/det.py`, `qlnes/config/loader.py`.
   - Refactor `cli.py` to route every existing command (`analyze`, `recompile`, `verify`, `audio`, `nsf`) through `errors.emit` for failure paths and `atomic_write_*` for output paths.
   - No new user-facing capability; no FR is closed by this story alone. **The story is justified only as part of a vertical slice that also closes a user-facing FR** (per the readiness report's epic-quality guidance). Recommended pairing: bundle this with FR5 / FR6 (the first sample-equivalent audio output) so the slice is "Marco gets one WAV out of mapper-0 with proper error handling end-to-end".

2. **Wave 2 — APU + engines** (epics A & B):
   - Add `qlnes/apu/`, `qlnes/audio/`, `qlnes/oracle/`. The brownfield `audio.py` ffmpeg-shellout path is replaced; `audio.py` is reduced to a thin compatibility shim that delegates to `audio/renderer.py`. Once the renderer is the only caller, `audio.py` is deleted in a follow-up story.
   - Add `qlnes/audit/`, `qlnes/coverage/`. `bilan.json` becomes the audit's only output.
   - `qlnes/nsf2.py` lands; `qlnes/nsf.py` keeps mapper-0 v1 compatibility for one release, then is removed.

3. **Wave 3 — repository hygiene** (one optional cleanup story near MVP exit):
   - Move existing top-level `tests/test_*.py` into `tests/unit/` and `tests/invariants/`.
   - Tighten `mypy.ini` to opt every new directory into `--strict`.
   - Add `qlnes.toml.example` and `examples/` README updates.

This wave ordering is informative for `bmad-create-epics-and-stories`, not prescriptive: epics will likely interleave Wave 1 & 2 along *user-value* boundaries rather than *infrastructure* boundaries.

## Cross-Cutting Module Designs

This step pins the implementation patterns for the seven cross-cutting concerns identified in step 2. These modules are tiny but are touched by *every* command, so their interfaces matter more than their LOC.

### `qlnes/io/atomic.py`

```python
"""Atomic file writes (FR35). Crash-safe across the whole product."""

from contextlib import contextmanager
import os, tempfile
from pathlib import Path

@contextmanager
def atomic_writer(target: Path, mode: str = "wb"):
    """Open a temp file in target's parent dir; rename on clean exit."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp",
                               dir=target.parent)
    try:
        with os.fdopen(fd, mode) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise

def atomic_write_bytes(target: Path, data: bytes) -> None:
    with atomic_writer(target, "wb") as f:
        f.write(data)

def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    with atomic_writer(target, "wb") as f:
        f.write(text.encode(encoding))
```

**Invariants enforced:**

- Temp file is in the *same directory* as the target — keeps `rename(2)` atomic on POSIX (cross-FS rename would fall back to copy+unlink, breaking atomicity).
- Temp file is hidden (`.`-prefix) so a directory listing during the write never shows it.
- `os.fsync` before rename — survives kernel crash, not just process crash. `--strict` makes the fsync mandatory; default behavior also fsyncs (NFR-REL-4 is a hard invariant).
- On any exception, the temp file is unlinked. The target file (if any) is untouched.

**Tested by:** `tests/invariants/test_determinism.py::test_atomic_write_kill` — spawns a subprocess that writes via `atomic_writer`, kills it mid-write, verifies the target file is unchanged or absent.

### `qlnes/io/errors.py`

```python
"""Sysexits-aligned error emitter with structured JSON stderr (FR33, FR34)."""

import json, sys
from dataclasses import dataclass, field
from typing import Any, NoReturn

# Locked taxonomy — UX §6.2
EXIT_CODES = {
    "usage_error":         64,
    "bad_format_arg":      64,
    "bad_rom":             65,
    "missing_input":       66,
    "internal_error":      70,
    "cant_create":         73,
    "io_error":            74,
    "unsupported_mapper":  100,
    "equivalence_failed":  101,
    "missing_reference":   102,
    "interrupted":         130,
}

DEFAULT_HINTS = {
    "usage_error":         "Run the command with --help to see valid usage.",
    "bad_format_arg":      "Run `<cmd> --help` to see valid values.",
    "bad_rom":             "Verify the file is a .nes ROM, not .nsf or .zip.",
    "missing_input":       None,                   # filled in dynamically
    "internal_error":      "Re-run with --debug and open an issue.",
    "cant_create":         "Add --force, or pick a different --output path.",
    "io_error":            "Check disk space and permissions.",
    "unsupported_mapper":  "Run `qlnes coverage` for the support matrix.",
    "equivalence_failed":  "Re-run with --debug to dump the divergence frame.",
    "missing_reference":   "Generate the reference: see corpus/README.md.",
    "interrupted":         None,                   # silent — user-initiated
}

@dataclass
class QlnesError(Exception):
    cls: str
    reason: str                                   # human one-line
    hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    @property
    def code(self) -> int: return EXIT_CODES[self.cls]

def emit(err: QlnesError, *, no_hints: bool = False, no_color: bool = False) -> NoReturn:
    sys.stderr.write(_red("qlnes: error: ", no_color) + err.reason + "\n")
    hint = err.hint or DEFAULT_HINTS.get(err.cls)
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    payload = {"code": err.code, "class": err.cls,
               "qlnes_version": _version(), **err.extra}
    sys.stderr.write(json.dumps(payload, sort_keys=True,
                                separators=(",", ":")) + "\n")
    sys.exit(err.code)
```

**Invariants enforced:**

- Three-line shape (UX §6.1) is structural — the function literally writes three regions in order.
- `--no-hints` and `--no-color` are caller-passed (not module globals), so unit tests can exercise both branches without env mucking.
- JSON is single-line, sorted keys, no spaces — same convention as `qlnes/det.py`. Lin's pipeline parses the last `stderr` line.
- `sys.exit` ends the process — there is no return path. Static type-checkers see `NoReturn` and mark callers' branches correctly.

**Caller pattern:**

```python
# in cli.py
try:
    do_audio(rom, ...)
except QlnesError as e:
    emit(e, no_hints=cfg.no_hints, no_color=(cfg.color == "never"))
except KeyboardInterrupt:
    emit(QlnesError("interrupted", "interrupted"))
except Exception as exc:                          # bug
    if cfg.debug: raise
    emit(QlnesError("internal_error", f"{type(exc).__name__}: {exc}",
                    extra={"detail": type(exc).__name__}))
```

This is the only place the CLI catches exceptions. Internal modules raise `QlnesError` for predictable failures and let everything else propagate. The contract is small, learnable, and machine-friendly.

### `qlnes/io/preflight.py`

```python
"""Pre-flight validation runner (FR36)."""

from typing import Callable
from .errors import QlnesError

class Preflight:
    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[], None]]] = []
    def add(self, name: str, check: Callable[[], None]) -> None:
        self._checks.append((name, check))
    def run(self) -> None:
        for name, check in self._checks:
            try: check()
            except QlnesError: raise
            except Exception as e:
                raise QlnesError("internal_error",
                                 f"preflight {name!r} crashed: {e}",
                                 extra={"check": name}) from e
```

**Pattern of use:** Each command declares its own pre-flight predicates, then runs them before touching any output:

```python
# cli.py audio()
pf = Preflight()
pf.add("rom_readable",  lambda: _check_rom_readable(rom))
pf.add("output_writable", lambda: _check_writable(out_dir, force=force))
pf.add("fceux_available", lambda: _check_binary("fceux"))
pf.add("lameenc_available_iff_mp3", lambda: _check_lameenc() if fmt == "mp3" else None)
pf.add("mapper_supported_for_audio", lambda: _check_mapper(rom_obj.mapper, "audio"))
pf.run()                    # exits before any byte is written
```

**Invariant enforced:** No write ever happens before `Preflight.run()` returns clean. Static guarantee plus a lint rule (custom `ruff` plugin in step 14) that flags `atomic_write_*` calls in command bodies that don't have a `Preflight.run()` lexically before them.

### `qlnes/det.py`

```python
"""Determinism utilities. Every output writer routes through these."""

import hashlib, json
from pathlib import Path
from typing import Any, Iterable

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))

def canonical_json_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")

def sha256_file(path: Path, _chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_chunk), b""):
            h.update(chunk)
    return h.hexdigest()

def stable_iter[T](items: Iterable[T], *, key=None) -> list[T]:
    """Sorted iteration, with a defensive total-order key requirement."""
    return sorted(items, key=key) if key else sorted(items)

def deterministic_track_filename(rom_stem: str, song_index: int, engine: str, ext: str) -> str:
    """UX §10.3 contract: <rom>.<idx:02>.<engine>.<ext>"""
    return f"{rom_stem}.{song_index:02d}.{engine}.{ext}"
```

**Why these utilities are central:**

- `canonical_json` is the *only* JSON serializer used in any artifact (`bilan.json`, `coverage --format json`, the structured `stderr` payload). The locked `(sort_keys=True, separators=(",", ":"))` pair is documented as a project invariant — anyone using `json.dumps` directly is violating NFR-REL-1 and is flagged by a custom lint rule.
- `sha256_file` is the canonical hash function for ROM identity and PCM equivalence. Hashes are *always* SHA-256, *always* lower-case hex, no other variants.
- `deterministic_track_filename` is the only function that builds output filenames in the audio path. Pipelines depend on UX §10.3's format; centralizing this prevents drift.

### `qlnes/config/loader.py`

The 4-layer resolver. Implementation sketch:

```python
"""Layered config (FR27, FR28, FR29)."""

import os, tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

class Layer(Enum):
    DEFAULT = 1; TOML = 2; ENV = 3; CLI = 4

@dataclass(frozen=True)
class ResolvedConfig:
    section: str
    values: dict[str, Any]
    provenance: dict[str, Layer]

class ConfigLoader:
    BUILTIN_DEFAULTS = {                                      # locked in code
        "default": {"output_dir": ".", "quiet": False,
                    "bilan_file": "./bilan.json", "strict": False,
                    "color": "auto", "hints": True, "progress": True},
        "audio":   {"format": "wav", "frames": 600,
                    "reference_emulator": "fceux"},
        "verify":  {"strict": True, "audio": False},
        "audit":   {"parallel": True, "corpus_dir": "./corpus"},
        "coverage": {"format": "table"},
    }
    ENV_PREFIX = "QLNES_"

    def __init__(self, *, config_path: Path | None = None,
                 cwd: Path | None = None) -> None:
        self._config_path = config_path
        self._cwd = cwd or Path.cwd()

    def resolve(self, command: str,
                cli_overrides: Mapping[str, Any]) -> ResolvedConfig:
        merged: dict[str, Any] = {}
        prov: dict[str, Layer] = {}
        # Layer 1
        defaults = {**self.BUILTIN_DEFAULTS["default"],
                    **self.BUILTIN_DEFAULTS.get(command, {})}
        merged.update(defaults)
        prov.update({k: Layer.DEFAULT for k in defaults})
        # Layer 2
        toml = self._load_toml()
        if toml:
            for k, v in {**toml.get("default", {}),
                          **toml.get(command, {})}.items():
                merged[k] = v; prov[k] = Layer.TOML
        # Layer 3
        for k, v in self._read_env(command).items():
            merged[k] = v; prov[k] = Layer.ENV
        # Layer 4
        for k, v in cli_overrides.items():
            if v is None: continue                            # un-set
            merged[k] = v; prov[k] = Layer.CLI
        return ResolvedConfig(command, merged, prov)
```

**Invariants enforced:**

- Layer 1 is hardcoded; tests assert that the in-code `BUILTIN_DEFAULTS` matches the table in UX §4.4 byte-for-byte. Drift is caught immediately.
- Unknown TOML keys log a warning (or fail under `--strict`) — see UX §4.4.
- `provenance` is exposed so `--debug` and the future `--explain-config` (Growth) can show "this value came from `QLNES_AUDIO_FORMAT`".
- TOML discovery: `--config <path>` > `$PWD/qlnes.toml` > `<rom_dir>/qlnes.toml`. First found wins — no merging across files.

### `qlnes/audit/bilan.py`

`BilanStore` is the schema authority. The schema itself is in step 12 (Data Models). Key behavioral invariants:

- **Read** validates against the locked schema (in `qlnes/audit/bilan_schema.json`); schema mismatch → `QlnesError("internal_error", "bilan.json schema mismatch", extra={...})`.
- **Write** uses `atomic_write_text(canonical_json_bytes(bilan))`. Sorted keys, deterministic ordering, no float locale traps.
- **Staleness**: `is_stale(bilan, sources)` returns True if any source mtime > `bilan.generated_at`. Source list is `qlnes/**/*.py` plus `corpus/manifest.toml`.
- **Schema versioning**: the `qlnes_version` field at the top of `bilan.json` plus a `schema_version: "1"` field (added in this MVP). Schema breaks bump `schema_version` and `qlnes_version`'s major.

### Tying it together — the 7 cross-cutting concerns from step 2

| # | Concern (step 2) | Implementation locked in step 7 |
|---|---|---|
| 1 | Determinism | `qlnes/det.py` — canonical JSON, sha256, deterministic filenames |
| 2 | Atomic writes | `qlnes/io/atomic.py` |
| 3 | Pre-flight | `qlnes/io/preflight.py` |
| 4 | Sysexits + JSON stderr | `qlnes/io/errors.py` |
| 5 | Tiered fidelity tagging | `SoundEngine.tier` ClassVar (step 9) + `BilanStore` engine sub-map (step 12) |
| 6 | Bilan as truth | `qlnes/audit/bilan.py` |
| 7 | Layered config | `qlnes/config/loader.py` |

Every command in `cli.py` post-MVP imports from at most these seven modules for cross-cutting work. No command implements its own atomic write, its own error format, or its own config. Drift is structurally hard.

## APU Emulator Architecture

This step closes Q1 (APU emulation backend) in design depth. The decision — **own implementation, FCEUX as oracle only** — was already locked in project memory; step 8 designs *how*.

### Why an own APU implementation is the right call

| Option considered | Verdict | Reason |
|---|---|---|
| **Own implementation** (chosen) | ✓ | Full control of cycle-accuracy, no third-party API contract risk, no native-build complexity, ports cleanly to a Rust extension later if NFR-PERF-2 ever fails. |
| Port of an existing OSS APU (FCEUX, Mesen, NSFPlay) | ✗ | License complexity (GPL contamination of qlnes's MIT), brittle once upstream re-architects, and a port is *more* work than from-spec for a 4-channel APU. |
| Use FCEUX as both oracle and renderer (subprocess every render) | ✗ | Couples runtime to FCEUX availability for *every* user (not just CI). 5–10× the per-track render time. Loses the "qlnes audio is byte-identical to FCEUX" claim — they'd be byte-identical because they ARE FCEUX, which is meaningless for the equivalence test. |

The NES 2A03 APU is well-documented (NESdev wiki) and small (~500 LOC of Python for the four channels + mixer is a generous upper bound). Sample-equivalence to FCEUX is the test contract; FCEUX implements the same wiki spec, so a clean-room implementation that passes the equivalence corpus IS sample-equivalent by definition.

### Module shape

```
qlnes/apu/
├── __init__.py          # ApuEmulator (public)
├── pulse.py             # PulseChannel (× 2: pulse1, pulse2)
├── triangle.py          # TriangleChannel
├── noise.py             # NoiseChannel
├── dmc.py               # DmcChannel — STUB in MVP, full in Growth
├── mixer.py             # 2A03 nonlinear mixer
└── tables.py            # length, period, noise period, mixer LUT
```

Each channel is a small pure-Python class with a clean state machine, driven by per-cycle `tick()` plus per-write `register_write(reg, value)`. The `ApuEmulator` orchestrates them and emits PCM samples at the requested sample rate via the mixer.

### Cycle-accuracy strategy

```
CPU cycles (NTSC 1.789 773 MHz) ──┐
                                   ├──> APU runs at CPU/2 (894 KHz)
Frame counter (4-step or 5-step) ──┘
                                                 │
                                                 ▼
                          per-channel tick() at APU rate
                                                 │
                                                 ▼
                                Channel outputs (4-bit each)
                                                 │
                                                 ▼
                                Nonlinear mixer (2A03 recipe)
                                                 │
                                                 ▼
                Resample to 44 100 Hz via integer-rational decimation
                                                 │
                                                 ▼
                                       int16 LE PCM
```

**Resampling.** From APU rate (894 886.5 Hz, half of CPU) to 44 100 Hz is the ratio 894886.5/44100 ≈ 20.29. Integer-rational form: `1789773 / (88200) = 20.292...` Use a polyphase FIR with a small precomputed window (24 taps) and integer-arithmetic accumulator. Determinism: identical FIR coefficients across hosts; integer accumulator overflow behaviour pinned by 32-bit explicit type.

**Why not float synthesis or scipy.signal.resample.** Float arithmetic is non-associative; cross-host bit-equivalence becomes platform-dependent. Integer math is a hard guarantee. The FIR coefficients are baked into a Python tuple (`tables.py`) and never recomputed.

### MVP channel scope

- **Pulse 1, Pulse 2.** Full envelope, sweep, length counter, duty cycles. Full sample-equivalence target.
- **Triangle.** Linear counter, length counter, period registers. Full target.
- **Noise.** Mode (short/long), period table, length counter, envelope. Full target.
- **DMC.** **Stub in MVP.** Channel ignored; bit 4 of $4015 reads as 0; writes to $4010-$4013 are recorded but not played. ROMs that use DMC heavily (sampled drums) are tagged tier-2 (frame-accurate, `unverified`) in MVP. Full DMC lands in Growth as a focused engine-coverage uplift, not as part of the MVP.

> **DMC scope decision.** Sampled-drum games are a small fraction of NES audio output (most NES OSTs use synthesized drums via the noise channel). MVP scope brutally narrows to: pulse + triangle + noise are sample-identical to FCEUX, on the corpus we choose. If a corpus ROM uses DMC, it's tagged `unverified` (tier 2) until Growth.

### Frame counter & IRQs

- **4-step mode** is the MVP default (most engines use it). Implements quarter/half-frame ticks at ~240 Hz / ~120 Hz.
- **5-step mode** lands in MVP; rarely used but Capcom games (one of the priority engines) use it for OST timing.
- **Frame-counter IRQ** is *captured* (the trace records when it fires) but is not propagated — the CPU is FCEUX in our pipeline, so we don't model an interrupt-handling CPU. We model the APU's *response* to writes that FCEUX makes; the IRQ is FCEUX's problem.

### Performance sketch

| Operation | per-call ~ns | calls per 3-min track | total |
|---|---|---|---|
| Channel tick | ~150 ns | 894886 × 180 ≈ 161 M | ~24 s |
| Mixer + resample | ~80 ns | 44100 × 180 ≈ 7.9 M | ~0.6 s |
| Total per track | | | **~25 s pure Python** |

**Target:** NFR-PERF-2 says ≤ 2× real time, i.e. ≤ 6 minutes for a 3-min track. Pure Python at 25 s/track is ~7× faster than the budget. Rust port is unnecessary for MVP. (If a real engine fails the budget, we can always JIT the inner channel-tick loop with PyPy or `cffi`-call into a C shim; both are post-MVP optimizations.)

### Test contract for the APU emulator

The APU emulator is the only component with a hard sample-equivalence target. Its tests are correspondingly strict:

- `tests/invariants/test_pcm_equivalence.py::test_apu_vs_fceux_per_channel` — feed the APU emulator the same register-write trace FCEUX produces (captured via Lua), compare PCM streams sample-by-sample. Pass = byte-identical.
- `tests/unit/test_apu_pulse.py` — per-register-write unit tests (envelope, sweep) against canonical NESdev test cases.
- `tests/invariants/test_determinism.py::test_apu_cross_run_identical` — render twice, hash, assert equality.

The APU is the most-tested component in the project. Its test suite is the one we don't compromise on.

## Sound Engine Plugin Architecture

This step closes Q3 (song-table detection) in design depth. The decision — **per-engine handlers via `SoundEngine` ABC + generic fallback** — was locked; step 9 designs the registry, the ABC contract, and the four concrete handlers' shapes.

### The plugin contract

```python
# qlnes/audio/engine.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Literal, Optional
from ..rom import Rom

@dataclass(frozen=True)
class DetectionResult:
    confidence: float                 # 0.0 .. 1.0
    evidence: list[str]               # human-readable signals
    metadata: dict                    # opaque, engine-specific

@dataclass(frozen=True)
class SongEntry:
    index: int
    label: Optional[str]              # if engine encodes a name
    referenced: bool                  # False for "unused" composer demos (FR10)
    metadata: dict

@dataclass(frozen=True)
class LoopBoundary:
    start_frame: int
    end_frame: int

class PcmStream:
    """Wrapper over a bytes-of-int16-LE buffer + sample rate + loop boundary."""
    samples: bytes
    sample_rate: int = 44100
    loop: Optional[LoopBoundary] = None

class SoundEngine(ABC):
    name: ClassVar[str]                          # canonical handle
    tier: ClassVar[Literal[1, 2]]                # 1 = sample-eq target, 2 = frame-accurate
    target_mappers: ClassVar[frozenset[int]]     # for fast pre-filter

    @abstractmethod
    def detect(self, rom: Rom) -> DetectionResult: ...
    @abstractmethod
    def walk_song_table(self, rom: Rom) -> list[SongEntry]: ...
    @abstractmethod
    def render_song(self, rom: Rom, song: SongEntry,
                    oracle: "FceuxOracle | None") -> PcmStream: ...
    @abstractmethod
    def detect_loop(self, song: SongEntry,
                    pcm: PcmStream) -> LoopBoundary | None: ...
```

### Detection registry & resolution

```python
# qlnes/audio/engine.py (continued)
class SoundEngineRegistry:
    """Iterate all registered engines, run detect(), pick the highest-confidence."""

    _engines: list[type[SoundEngine]] = []

    @classmethod
    def register(cls, engine: type[SoundEngine]) -> type[SoundEngine]:
        cls._engines.append(engine)
        return engine                            # decorator-style

    @classmethod
    def detect(cls, rom: Rom, *, threshold: float = 0.6
              ) -> tuple[SoundEngine, DetectionResult]:
        candidates = []
        for E in cls._engines:
            if rom.mapper not in E.target_mappers and E.target_mappers:
                continue
            inst = E()
            r = inst.detect(rom)
            if r.confidence >= threshold:
                candidates.append((inst, r))
        if not candidates:
            return GenericEngine(), DetectionResult(0.0, ["no specific engine"], {})
        # Highest confidence wins; ties broken by registration order (deterministic).
        return max(candidates, key=lambda ir: ir[1].confidence)
```

### The four MVP+Growth handlers

| Handler | Tier | Mappers it targets | MVP / Growth | What it knows |
|---|---|---|---|---|
| `FamiTrackerEngine` | 1 (sample-eq) | M0, M1, M4, M66 | MVP | FT's sequence-of-pattern bytecode (`Cxx`, `Dxx`, `Bxx`), pointer-table layout (`song_list_l`/`song_list_h` pair), instrument table. |
| `CapcomEngine` (Sakaguchi/Capcom-3) | 1 | M0, M1, M2, M3, M4, M66 | MVP | Capcom's two-byte note-event format, note-length lookup, master-loop sentinel byte. |
| `KonamiKGenEngine` | 1 | M1, M4, M5 | **Growth** | KGen's variable-rate frame counter, VRC6 expansion-audio support (Growth-tier). |
| `GenericEngine` | 2 (frame-acc) | * | MVP | No engine semantics. Replays APU writes from FCEUX trace into the emulator at frame granularity (~16.6 ms NTSC). Detects loops by APU register-write fingerprinting only. Output tagged `unverified`. |

**MVP closes 2 sample-equivalent engines + the generic fallback.** Growth adds Konami KGen and (engine-by-engine) the rest of the top-10. Each handler is its own implementation story, testable in isolation against its corpus subset.

### The generic fallback's tier-2 contract

The generic handler is what makes "any ROM produces some output" true while preserving the "no false positives in `bilan.json`" invariant:

- **Render:** replays the APU register-write trace captured by FCEUX through the qlnes APU emulator. PCM is frame-accurate (≈16.6 ms NTSC) — the trace timestamp granularity bounds it.
- **Loop detection:** none (returns `None`). PCM is emitted as a one-shot at the requested duration.
- **`bilan.json`:** every audio entry produced by `GenericEngine` is recorded under the synthetic `engines.unknown` sub-map with `status: "unverified"`. Per FR25 / UX §5.3, `unknown` is *never* `pass`.
- **`--strict` interaction:** under `--strict`, ROMs whose engine detection scored below threshold raise `QlnesError("equivalence_failed", "engine not recognized; --strict refuses tier-2 fallback")` instead of falling back. This is how CI rejects unverified output.

### Loop-boundary detection (Q5 closure)

Three-tier strategy, prioritized:

1. **Engine-bytecode tier (tier-1 only).** Every engine handler implements `detect_loop` against its bytecode dialect's loop-sentinel opcodes (FT `Bxx`, Capcom `0xFE`, etc.). When the engine identifies a loop opcode, the loop boundary is exact down to the frame.
2. **APU-fingerprint tier (tier-1 fallback, tier-2 baseline).** Watch the APU register-write stream; when the same N-second windowed fingerprint repeats, declare a loop. Used when bytecode is too obfuscated. Frame-accurate.
3. **Never PCM autocorrelation as the primary path.** PCM autocorrelation is brittle on noise/percussion-heavy NES tracks and is explicitly excluded. (Per the locked PRD decision; recorded as a forbidden technique.)

The three tiers are tried in order; first hit wins. A loop boundary, when found, is encoded into the WAV's `'smpl'` chunk (RIFF sample-loop chunk, type 0 = forward loop, native to game-engine WAV consumers).

### Adding a new engine — the contributor flow

1. Drop `qlnes/audio/engines/<name>.py` with the four required methods.
2. Decorate the class with `@SoundEngineRegistry.register`.
3. Add an entry to `corpus/manifest.toml` for ROMs targeting this engine.
4. Generate FCEUX reference outputs via `python scripts/generate_references.py --engine <name>`.
5. Run `qlnes audit`. The engine is integrated when its corpus subset is at 100% pass.

This flow is intentionally short — the friction of adding an engine is the friction of *correctness*, not of *plumbing*. Plumbing is already done.

## FCEUX Oracle Integration

This step closes Q1's other half — *how* qlnes calls FCEUX. The decision is locked: subprocess + Lua scripting, deterministic invocation, version recorded in `bilan.json`.

### Subprocess invocation contract

```python
# qlnes/oracle/fceux.py
class FceuxOracle:
    DEFAULT_ARGS = (
        "--no-config", "1",       # do not read user config
        "--mute", "1",             # silent (we capture via Lua, not via host audio device)
        "--frameskip", "0",        # ensure every frame's APU writes are observed
        "--video", "0",            # no video render; we don't need it
        "--sound", "0",            # no host audio output
    )
```

**Invariants:**

- `--no-config 1` removes locale and user-preference dependencies (NFR-REL-1).
- Lua script (`qlnes/audio_trace.lua`) emits a deterministic TSV of `(cpu_cycle, register, value)` tuples to a temp file we read after FCEUX exits. The file path is passed as an env var `QLNES_TRACE_PATH`; the Lua script writes to that path.
- Exit code propagation: FCEUX exits 0 normal, non-zero on crash. Non-zero → `QlnesError("internal_error", ...)` with the FCEUX exit code in `extra.fceux_exit`.
- Timeout: each oracle call is wrapped in a per-frame budget (50 ms × frame_count + 5 s overhead). Timeouts → `internal_error` with `extra.timeout=True`.

### Why subprocess and not a Python binding

- **No maintained Python binding to FCEUX exists** that's recent enough for our 2.6.6+ requirement.
- **Subprocess gives us license isolation.** FCEUX is GPL-2; loading its library into our MIT-licensed process would risk derivative-work claims. Forking a process keeps qlnes's distribution clean.
- **Subprocess gives us crash isolation.** FCEUX has a long history; a broken ROM that crashes it crashes the subprocess only, not qlnes. Pre-flight survives.

### Lua script (`audio_trace.lua`) shape

The existing file is a starting point. The MVP locks this shape:

```lua
-- qlnes/audio_trace.lua
local frames = tonumber(os.getenv("QLNES_FRAMES")) or 600
local out = io.open(os.getenv("QLNES_TRACE_PATH"), "w")
out:write("# qlnes-trace v1\n")  -- schema-versioned

memory.registerwrite(0x4000, 0x18, function(addr, size, val)
    out:write(string.format("%d\t%d\t%d\n",
              emu.framecount(), addr, val))
end)

emu.frameadvance()
for i = 2, frames do emu.frameadvance() end
out:close()
emu.exit()
```

**Trace format** is a versioned plain-text TSV, parsed by `qlnes/oracle/fceux.py`. Schema version in the header; bumped on any column change.

### Reference-PCM capture (for `qlnes verify --audio`)

For PCM equivalence we don't *just* need the trace — we need FCEUX's rendered PCM as the reference signal. Two strategies were considered:

| Strategy | Verdict | Reason |
|---|---|---|
| **Lua-driven WAV capture** (chosen) | ✓ | The same Lua script that captures the trace also captures FCEUX's per-frame audio buffer (`sound.get`), writes a `.wav.tmp` next to the trace, atomically renamed to `.wav` after `emu.exit()`. Bundled with the trace, no separate FCEUX invocation. |
| Run FCEUX with audio output to a wav-capture file via host audio device | ✗ | Host-audio-dependent; non-deterministic across distros. Several known FCEUX bugs around capture-on-Linux. |

The reference-WAV path is the FCEUX `sound.get` API, sample-rate 44100 (FCEUX's native). The path is integrated into `FceuxOracle.reference_pcm()` and is what `tests/invariants/test_pcm_equivalence.py` asserts against.

### Version pinning

`bilan.json` records `reference_emulator_version: "2.6.6"`. Re-running an audit on a different FCEUX version that produces a different reference PCM is a *re-anchoring* event:

- The bilan's `qlnes_version` major bumps if the schema reference changes.
- A `corpus/RE-ANCHOR.md` file records the why (FCEUX bug fix, version cut) — auditable history.
- Re-anchoring is a manual approval step, not a silent behaviour.

This makes the equivalence claim falsifiable: "qlnes 0.5.x is sample-equivalent to FCEUX 2.6.6 on corpus C" is a precise, time-bounded statement.

## Test Corpus & IP Discipline

This step closes Q2 — the highest-impact unknown per the readiness report. The repo *cannot* ship commercial NES ROMs (copyright). What we can ship:

- **ROM hashes** (SHA-256) and metadata (mapper, engine, region, expected song count) — facts about ROMs, not the ROMs.
- **Generated reference outputs** (FCEUX-rendered PCM) — derivative works of FCEUX's emulation, not of the ROM. This is debatable copyright territory; we ship the *hashes* of the references and require users to generate them locally from their own ROM copies. **MVP does not commit reference WAVs to the repo.**

### The corpus/manifest.toml format

```toml
# corpus/manifest.toml — committed, no ROM bytes, no audio bytes.
schema_version = "1"

[[rom]]
name = "Mega Man 2"
sha256 = "8d4f...ef02"
mapper = 1
region = "ntsc"
engine = "capcom"
song_count = 28              # expected, used to detect song-table walk regressions
notes = "Cap_M2 — Capcom 4-channel engine, 5-step frame counter"

[[rom]]
name = "DuckTales"
sha256 = "3a1b...c901"
mapper = 2
region = "ntsc"
engine = "capcom"
song_count = 12

# ... 50 ROMs targeted for MVP corpus ...

[[reference]]
rom_sha256 = "8d4f...ef02"
artifact = "audio"
fceux_version = "2.6.6"
pcm_sha256 = "9e2c...18a4"          # the FCEUX-rendered PCM hash. Generated locally; committed.
generated_at = "2026-04-12T09:33:21Z"

[[reference]]
rom_sha256 = "8d4f...ef02"
artifact = "nsf"
fceux_version = "2.6.6"
nsf_sha256 = "11ef...77b3"
generated_at = "2026-04-12T09:33:21Z"
```

**What's committed:** the manifest with hashes only.

**What's NOT committed:** the ROMs (`corpus/roms/*.nes`) or the reference outputs (`corpus/references/*.wav`, `*.nsf`). Both go in `.gitignore`.

**What contributors do:** they place their own legally-obtained ROMs into `corpus/roms/` (filename = the SHA-256 + `.nes`), then run `python scripts/generate_references.py` to produce `corpus/references/`, and `qlnes audit` validates that the produced reference-PCM hash matches the manifest entry. If a contributor's ROM dump differs from the canonical one (different region, header-edit), their hash mismatch is caught immediately and the audit refuses to use that ROM — preserves the corpus invariant.

### Distribution chain (FR31 — Growth)

When `pip install qlnes` lands (Growth):

- The wheel ships `qlnes/audio_trace.lua`, the Python code, and the manifest **without ROMs or references**.
- A first-time user who wants to run `qlnes audit` runs `qlnes corpus init` (new sub-command, Growth) which lists what they need to provide and where to drop it. We never ship ROM bytes via PyPI.

### Privacy & telemetry

There is none. `qlnes` makes zero network calls in MVP. `bilan.json` is committed by the maintainer; no upload happens automatically. (FR40 also forbids leaking host info into artifacts.)

### Legal posture

- ROMs: not redistributed, ever. Hashes only.
- FCEUX: GPL-2; subprocess use only. License notice carries forward in our README.
- `lameenc`: MIT for the wrapper, libmp3lame is LGPL-2; the wheel's static-link of LAME is the wrapper's responsibility, not ours; we depend on `lameenc==1.7.0` and document this license chain in NOTICE.
- `py65`: BSD-3.
- `cynes`: MIT.
- `Pillow`: HPND.
- Everything qlnes ships: MIT.

The license fan-in is clean. A `NOTICE.md` summarizing third-party licenses lands in the same MVP story as the corpus/manifest doc.

## Data Models & Schemas

This step pins every persisted-format the architecture introduces. Each schema is versioned; each version is the contract.

### `bilan.json` schema (v1)

JSON Schema sketched:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["schema_version", "qlnes_version", "generated_at",
               "reference_emulator", "reference_emulator_version",
               "corpus", "results"],
  "properties": {
    "schema_version": {"const": "1"},
    "qlnes_version": {"type": "string"},
    "generated_at": {"type": "string", "format": "date-time"},
    "reference_emulator": {"const": "fceux"},
    "reference_emulator_version": {"type": "string"},
    "corpus": {
      "type": "object",
      "required": ["rom_count", "mapper_breakdown", "manifest_sha256"],
      "properties": {
        "rom_count": {"type": "integer", "minimum": 0},
        "mapper_breakdown": {
          "type": "object",
          "patternProperties": {
            "^[0-9]+$": {"type": "integer", "minimum": 0}
          }
        },
        "manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    },
    "results": {
      "type": "object",
      "patternProperties": {
        "^[0-9]+$": {                              // mapper number as string
          "type": "object",
          "patternProperties": {
            "^(analyze|nsf|audio|verify)$": {
              "type": "object",
              "required": ["status", "rom_count", "fail_count"],
              "properties": {
                "status": {"enum": ["pass","partial","fail",
                                     "unverified","missing"]},
                "rom_count": {"type": "integer"},
                "fail_count": {"type": "integer"},
                "failing_rom_sha256s": {
                  "type": "array",
                  "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                },
                "engines": {                       // present for audio/nsf only
                  "type": "object",
                  "patternProperties": {
                    "^[a-z_]+$": {                 // engine name (incl. "unknown")
                      "type": "object",
                      "required": ["status","rom_count","fail_count"],
                      "properties": {
                        "status": {"enum":["pass","partial","fail","unverified"]},
                        "rom_count": {"type": "integer"},
                        "fail_count": {"type": "integer"},
                        "format": {"type": "string"}   // e.g. "nsf2+nsfe"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

Stored at `qlnes/audit/bilan_schema.json` and *validated* on every `BilanStore.read`. Schema version 1 covers MVP. Schema breaks bump to "2".

### Track filename convention (locked)

Per UX §10.3:

```
<rom-stem>.<song-index-2-digit>.<engine>.<format>
```

Where `<engine>` ∈ `{famitracker, capcom, konami_kgen, unknown, ...}` and `<format>` ∈ `{wav, mp3, nsf}`. This is a project invariant — see `qlnes/det.py::deterministic_track_filename`.

### NSF2 + NSFe layout (locked, FR5 + Q4)

NSF version byte is `0x02` (NSF2). NSFe metadata chunks appended after the PRG payload:

```
+----------------------------+ offset 0
| NSF2 header (128 bytes)    |
+----------------------------+ offset 0x80
| PRG bytes                  |
| ...                        |
+----------------------------+ offset 0x80 + len(PRG)
| NSFe metadata chunks       |
|   tlbl  track labels       |
|   time  per-track lengths  |
|   fade  per-track fadeouts |
|   auth  author info        |
|   plst  playlist order     |
+----------------------------+
```

NSFe chunks are the optional metadata format that NSF2 supports. They give Sara (PRD Journey 2) per-track titles in her NSF player.

### qlnes.toml schema

Locked in UX §4.4. Validated at config-load time. Unknown keys warn (or, with `--strict`, error). `qlnes.toml.example` ships in the repo as the canonical reference.

### Trace format (`qlnes/audio_trace.lua` output)

Versioned TSV. Schema-version in the first comment line: `# qlnes-trace v1`. Three columns: `cpu_frame`, `register_addr`, `register_value`. UTF-8, LF-only, no header-row beyond the version comment.

A schema bump (v2) is what happens if we ever want to capture additional registers (e.g. mapper-expansion-audio writes for VRC6/MMC5 in Growth). MVP is v1.

### Structured-stderr JSON payload

Locked in UX §6.3. Per error class, the required fields are documented; per-class extras are open-ended for future additions but never *removed* without a major version bump. The `qlnes_version` field in every payload is the project version (matching `qlnes/__init__.py::__version__`).

## Testing & Equivalence Harness

The equivalence corpus is the release gate (FR26). The test architecture is therefore organized around three layers, in order of unit cost:

### Test layout

```
tests/
├── conftest.py                    # shared fixtures
├── unit/                          # pure-function tests, fast, run on every commit
│   ├── test_apu_pulse.py
│   ├── test_apu_triangle.py
│   ├── test_engine_famitracker.py
│   ├── test_engine_capcom.py
│   ├── test_config_loader.py
│   ├── test_atomic_writer.py
│   ├── test_errors_emitter.py
│   ├── test_bilan_store.py
│   ├── test_det.py
│   └── ...
├── integration/                   # one component + its real deps, no corpus
│   ├── test_audio_pipeline.py     # rom → engine → APU → wav (one ROM)
│   ├── test_audit_runner.py       # audit on a 3-ROM mini-corpus
│   ├── test_cli_audio.py          # subprocess qlnes, parses stderr JSON
│   └── ...
└── invariants/                    # full corpus, slow, run on tag and weekly
    ├── test_pcm_equivalence.py
    ├── test_round_trip.py
    ├── test_nsf_validity.py
    ├── test_determinism.py
    └── test_atomic_kill.py
```

### Test taxonomy by purpose

| Layer | Speed | Run when | Failure means |
|---|---|---|---|
| `unit/` | < 1 s each | every commit, `pytest tests/unit` | logic bug |
| `integration/` | seconds | every commit, `pytest tests/integration` | wiring bug |
| `invariants/` | minutes–tens of minutes | weekly + on tag, `pytest tests/invariants -n auto` | release blocker (FR26) |

Per-mapper / per-engine tests are *parametrized* — one test function takes the corpus-manifest entries as a parameter, so adding a ROM adds N tests automatically.

### The equivalence harness — `test_pcm_equivalence.py` shape

```python
# tests/invariants/test_pcm_equivalence.py
import pytest
from qlnes.audit.corpus import load_manifest
from qlnes.audio.renderer import render
from qlnes.oracle.fceux import FceuxOracle

CORPUS = load_manifest("corpus/manifest.toml")

@pytest.mark.parametrize("rom_entry",
    [r for r in CORPUS.roms if r.engine != "unknown"],
    ids=lambda r: f"{r.engine}-{r.sha256[:8]}")
def test_pcm_byte_equivalent_to_fceux(rom_entry, oracle):
    rom_path = CORPUS.local_path(rom_entry.sha256)
    if not rom_path.exists():
        pytest.skip(f"ROM not present locally: {rom_entry.sha256}")
    pcm_qlnes = render(rom_path, format="wav").pcm_only()
    pcm_ref = oracle.reference_pcm(rom_path, frames=rom_entry.frames)
    assert sha256(pcm_qlnes) == sha256(pcm_ref)
```

**Key behaviors:**

- Skip-on-missing-ROM (not fail) — contributors without the corpus run no equivalence checks but the unit + integration suites still pass.
- `oracle` fixture in `conftest.py` instantiates `FceuxOracle()` once per session; cached reference PCM is read from `corpus/references/<sha>.wav` when present, generated otherwise.
- Failure dumps the divergence frame to `tests/_artifacts/<sha>.divergence.json` for triage.

### Determinism tests

```python
# tests/invariants/test_determinism.py
def test_render_twice_identical(tmp_path, sample_rom):
    a = render(sample_rom, out_dir=tmp_path / "a")
    b = render(sample_rom, out_dir=tmp_path / "b")
    for fa, fb in zip(sorted(a), sorted(b)):
        assert sha256_file(fa) == sha256_file(fb)

def test_atomic_write_kill_safe(tmp_path):
    # Spawn subprocess, kill mid-write, assert no partial file remains.
    ...

def test_no_wallclock_in_artifact(tmp_path, sample_rom):
    out = render(sample_rom, format="nsf", out_dir=tmp_path)
    bytes_ = out.read_bytes()
    # Today's date in any common format must NOT appear in the artifact.
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assert today.encode() not in bytes_
```

These tests guard NFR-REL-1, NFR-REL-2, NFR-REL-4. Failures here are release blockers.

### Coverage measurement vs corpus gate

Code coverage (`coverage.py`) is reported, never gated. The release gate is the corpus pass rate (FR26). A new module with 0% line coverage but 100% corpus pass is acceptable; a module with 100% line coverage but 50% corpus pass is not.

## CI/CD & Release Process

### CI workflows

Three GitHub Actions workflows, each in `.github/workflows/`:

#### `test.yml` — every push & PR

```yaml
name: test
on: [push, pull_request]
jobs:
  unit-and-integration:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: gcc -O2 -o bin/ql6502 vendor/QL6502-src/*.c
      - run: ruff check qlnes tests
      - run: ruff format --check qlnes tests
      - run: mypy qlnes
      - run: pytest tests/unit tests/integration
```

Fast: ~3–5 minutes typical. Block merges on red.

#### `audit.yml` — weekly + on tag

```yaml
name: audit
on:
  schedule: [{cron: "0 6 * * 0"}]    # Sundays
  push: { tags: ["v*"] }
  workflow_dispatch:
jobs:
  full-audit:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: ./scripts/install_audio_deps.sh
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: gcc -O2 -o bin/ql6502 vendor/QL6502-src/*.c
      - run: ./scripts/restore-corpus.sh   # pulls ROMs from a private GH secret-protected source; not committed
      - run: pytest tests/invariants -n auto
      - run: python -m qlnes audit --strict --bilan ./bilan.json
      - uses: actions/upload-artifact@v4
        with: { name: bilan, path: bilan.json }
```

The audit runner produces the canonical `bilan.json` for the version under test. On tag, it uploads the artifact attached to the GitHub release. Weekly, it commits the new bilan as a maintainer-merged PR (or fails loudly if regressions appear).

#### `deptry.yml` — already exists (`291225a`)

Keeps as-is. Covers undeclared / unused dependencies.

### Release process

1. Tag `v0.X.0` on `master`.
2. `audit.yml` runs against the tag.
3. Maintainer reviews the produced `bilan.json` for regressions vs the previous tag's bilan.
4. If clean: `gh release create v0.X.0 --generate-notes` + `bilan.json` artifact attached.
5. (Growth) `pyproject.toml` build + PyPI upload runs on tag — out of MVP.

**Release gates:**

- Every MVP FR has at least one corresponding test in `unit/` or `integration/`.
- All `tests/unit` and `tests/integration` green.
- All `tests/invariants` green on the supported portion of the corpus (FR26).
- No new mapper × artifact entry has regressed from `pass` to anything else vs the previous bilan. Going from `pass` to `partial` is a release blocker.

## NFR Mapping & Determinism Strategy

This step maps each NFR to the architectural mechanism that satisfies it. Every NFR has a verification test (FR-link).

### Performance

| NFR | Budget | Mechanism | Verification |
|---|---|---|---|
| NFR-PERF-1 | analyze < 2 s on 32 KB ROM | Static analyzer is single-pass + QL6502 vendored binary | `tests/integration/test_analyze_perf.py` measures wall-time, asserts < 2 s |
| NFR-PERF-2 | audio render ≤ 2× real time | Pure-Python APU emulator; integer arithmetic; performance sketch (step 8) shows ~7× headroom | `tests/integration/test_audio_perf.py` |
| NFR-PERF-3 | audit < 30 min on 50-ROM corpus | `pytest-xdist -n auto` parallel; each ROM independent; `concurrent.futures` for pure-Python parallelism in `audit.runner` | `audit.yml` weekly metrics; CI fails if mean run-time exceeds 25 min trend over 4 weeks |
| NFR-PERF-4 | coverage cache hit < 100 ms | `BilanStore.read` is one fopen + one json parse + one schema validate | `tests/integration/test_coverage_perf.py` |
| NFR-PERF-5 | peak RAM < 500 MB per invocation | APU emulator emits PCM in chunks (no full-track buffer in RAM); per-track files written before next track renders | `tests/invariants/test_memory_ceiling.py` uses `resource.getrusage` |

### Reliability & Determinism

| NFR | Mechanism | Verification |
|---|---|---|
| NFR-REL-1 | byte-identical PCM canonical hash target | Integer-arithmetic APU; deterministic FIR resampler; sorted JSON; `qlnes/det.py` invariants | `tests/invariants/test_pcm_equivalence.py`, `test_determinism.py::test_render_twice_identical` |
| NFR-REL-2 | no wall-clock / hostname / username in outputs | `qlnes/det.py` provides only deterministic primitives; no `datetime.now()` in any artifact-writer; ruff custom rule flags forbidden APIs in writer modules | `tests/invariants/test_determinism.py::test_no_wallclock_in_artifact` |
| NFR-REL-3 | deterministic parallelism | Audit splits per-ROM jobs; per-ROM rendering is independent; output assembly is `sorted_by(rom_sha256)` before write | `tests/invariants/test_determinism.py::test_parallel_vs_serial_identical` |
| NFR-REL-4 | atomic writes | `qlnes/io/atomic.py` used by every writer | `tests/invariants/test_atomic_kill.py` |
| NFR-REL-5 | crash-free on supported corpus | Pre-flight runner (FR36) + structured error emission (FR33/34); audit refuses unsupported mapper×artifact pairs cleanly | corpus pass-rate gate at release |

### Determinism strategy in concrete terms

- **No `datetime.now()`** in any artifact-writer module. The single exception is `bilan.json::generated_at`, written through a single named function `qlnes.audit.bilan.now_iso()` so its callers are exhaustively known.
- **No `random` / `secrets`.** Period. If we ever need pseudo-randomness it's a seeded `random.Random(seed)` with a documented seed input.
- **Sorted iteration everywhere.** Dict iteration order is stable in 3.11 but we don't trust input dicts; `det.stable_iter()` is the project's iteration primitive.
- **Integer arithmetic where bit-equivalence matters.** APU mixer uses 16-bit accumulator; FIR resampler uses 32-bit. No floats in the audio rendering path.
- **No environment leakage.** `bilan.json` records `qlnes_version` and `reference_emulator_version` only; not `LANG`, `TERM`, hostname, user, or path.
- **Locale-independent number formatting.** `json.dumps` always; no `f"{x:n}"` ever.

### Portability

| NFR | Mechanism | Verification |
|---|---|---|
| NFR-PORT-1 | Linux canonical | CI matrix is Ubuntu 22.04 only in MVP | `test.yml` |
| NFR-PORT-2 | macOS Growth | CI matrix adds macos-13 in Growth | future workflow update |
| NFR-PORT-3 | Windows deferred | Not tested | n/a |
| NFR-PORT-4 | Python ≥ 3.11 | `requirements.txt` floor; CI uses 3.11 | `test.yml` |

### External dependencies

| NFR | Mechanism | Verification |
|---|---|---|
| NFR-DEP-1 | FCEUX only hard external | `cynes` feature-gated import (`_have_cynes()` pattern from existing `cli.py`) | `tests/integration/test_no_cynes.py` runs CLI with `cynes` mocked-absent |
| NFR-DEP-2 | requirements.txt floor-pinned, `lameenc` `==`-pinned | `requirements.txt` review checked in `deptry.yml` | weekly |
| NFR-DEP-3 | new hard external dep requires PRD update | manual gate; mentioned in README and architecture doc | n/a |

## Risk Register

The risks below are ranked by impact × likelihood. Each has a designated mitigation that is part of the architecture, not a wish-list item.

| # | Risk | Impact | Likelihood | Mitigation in this architecture |
|---|---|---|---|---|
| R1 | APU emulator falls short of sample-equivalence on a corpus ROM | release-blocking (FR26) | medium | Per-channel unit tests (step 8); FCEUX trace + reference-PCM oracle catches divergence frame-by-frame; tier-2 fallback always available so the ROM is *covered* even if not *passing* |
| R2 | FCEUX 2.6.6 deprecated / new version produces different reference PCM | re-anchor cost; bilan churn | low | `corpus/RE-ANCHOR.md` process documented (step 10); `reference_emulator_version` in bilan freezes the claim |
| R3 | `lameenc==1.7.0` removed from PyPI / wheel unavailable on a future Python | MP3 path breaks | low | Subprocess `lame` documented fallback (step 4); MP3 byte-equivalence is acknowledged-fragile (skip marker `pytest.mark.lameenc`); PCM equivalence still the canonical claim |
| R4 | Test corpus IP exposure | legal | medium | Manifest is hashes-only, no ROM bytes; `corpus/roms/` gitignored; corpus restoration is a manual step contributors / CI runners do (step 11) |
| R5 | `cynes` deprecated upstream | dynamic discovery breaks for mapper 0 | low | Feature-gated, optional; FR4 has `[Existing]` tier and cynes-free fallback path is the analyze command minus `--no-dynamic` flag is already silent |
| R6 | `pytest-xdist` non-deterministic test order causes flaky equivalence test | CI flakes | medium | Equivalence tests parametrized per-ROM, each ROM isolated; xdist scheduler doesn't affect per-test outcome; if flake appears, drop xdist for invariants only |
| R7 | NSF2 + NSFe player compatibility — Sara loads `ost.nsf`, player rejects NSFe chunks | UX failure for content creators | low | Two NSF players targeted in NSFe-validity test (`tests/invariants/test_nsf_validity.py`): NSFPlay, GME. Both have NSFe support. CI loads the produced NSF in GME and asserts decode succeeds. |
| R8 | Solo-developer bus factor | continuity | high | Architecture is documented (this file + UX); test suite is the executable spec; no in-head-only knowledge |
| R9 | Mapper-66 audio extraction (recently shipped, FR mention) regresses with the new pipeline | functional regression | medium | The existing test (`test_engines_assets.py`, `test_real_rom.py`) plus the new corpus test cover mapper-66 explicitly; pre-merge CI catches |
| R10 | Loop-boundary detection's three-tier fallback chain misclassifies a loop | wrong loop in `'smpl'` chunk | medium | Per-engine bytecode tier is exact; APU-fingerprint tier has unit tests with synthesized loop patterns; PCM autocorrelation explicitly forbidden so no silent failure mode |
| R11 | Determinism violation slips in via a third-party dep (e.g. `Pillow` PNG metadata) | NFR-REL-2 break | low | `tests/invariants/test_determinism.py::test_no_wallclock_in_artifact` runs against every output type, including PNGs from `analyze --assets` |
| R12 | DMC-heavy ROM in corpus → tier-2 unverified flood | UX confusion (Marco sees `unverified` for a ROM he expected supported) | medium | DMC scope explicitly documented (step 8); Growth-tier promotion of DMC is a roadmap item; coverage matrix tagging makes DMC's tier-2 status visible to the user |

## Architecture Decision Log (ADRs)

These are the load-bearing architectural decisions made in this document. Each is reversible only with the cost noted.

| ID | Decision | Made in | Reverse cost |
|---|---|---|---|
| ADR-01 | Python ≥ 3.11, no compiled-language port for MVP | step 4 | Low — Rust extension can be added piecewise behind the APU module's Python interface |
| ADR-02 | Own APU emulator (Q1) | step 8 | Medium — porting a third-party APU would require licence work + integration |
| ADR-03 | FCEUX subprocess + Lua trace as oracle (Q1 cont.) | step 10 | Medium — switching oracle to Mesen requires re-anchor across whole corpus |
| ADR-04 | `lameenc==1.7.0` for MP3, `==`-pinned (Q6) | step 4 | Low — subprocess `lame` is a documented fallback |
| ADR-05 | `pytest` as test framework | step 4 | Low — existing tests are vanilla |
| ADR-06 | `SoundEngine` ABC + plugin registry, four MVP+Growth handlers (Q3) | step 9 | Low — adding/removing engines is plugin-local |
| ADR-07 | Three-tier loop-boundary detection, never PCM autocorrelation as primary (Q5) | step 9 | Low — per-engine logic; revisited per-engine if needed |
| ADR-08 | NSF2 + NSFe metadata chunks (Q4) | steps 4 & 12 | High — NSF1 readers already in the wild; backwards regression problematic |
| ADR-09 | Hashes-only test corpus, no ROM redistribution (Q2) | step 11 | High — would require legal review to ship ROM bytes |
| ADR-10 | `bilan.json` is the single source of truth for coverage; `audit` writes, `coverage` reads | steps 7, 12 | Medium — splitting writers would require re-shaping the coverage CLI surface |
| ADR-11 | Four-layer config (default < TOML < env < CLI) | step 7 | Low — adding/removing layers would require minor version bump |
| ADR-12 | Three-line error shape + structured JSON stderr | step 7, UX §6 | High — Lin's pipeline parses last line; behavior change is a major version bump |
| ADR-13 | Atomic writes everywhere; SIGINT leaves no half-file | step 7 | Low — pure addition over baseline |
| ADR-14 | Determinism is a release-blocking NFR; integer arithmetic in audio path | step 15 | Medium — float arithmetic is faster but loses cross-host equivalence |
| ADR-15 | `unverified` is the only fidelity tier between `pass` and `fail`; `unknown` engine never reports `pass` | UX P3, step 9 | Low — invariant baked into `BilanStore` write path |
| ADR-16 | Tests organized into unit / integration / invariants; corpus pass-rate is the release gate, not coverage % | step 13 | Low — internal organization |
| ADR-17 | CI: weekly audit + on-tag audit; in-PR run is unit + integration only | step 14 | Low — workflow tweak |
| ADR-18 | DMC channel stub in MVP, full in Growth | step 8 | Medium — ROMs depending on DMC stay tier-2 unverified until promoted |
| ADR-19 | Linux canonical for MVP; macOS at Growth; Windows deferred | step 4, NFR-PORT | Low — CI matrix expansion |
| ADR-20 | No public Python API; CLI is the only stable contract | UX P4, PRD | High — consumers lock in via subprocess; library API is a Vision-tier offering |

## Phasing & Story Seams (Inputs to `bmad-create-epics-and-stories`)

The architecture above naturally decomposes into vertical-slice epics that close user-value FRs while embedding the cross-cutting infrastructure stories inside them. Below is the recommended seam structure for `CE`. **These are inputs to story-writing, not the stories themselves.**

### Epic seam A — *Get music out of a ROM* (FR5–FR11, FR27–FR30, FR33–FR40 partial)

**User value.** Marco's journey 1: `qlnes audio rom.nes --format wav --output tracks/` produces sample-equivalent WAVs for one engine on one supported mapper.

**Embedded infrastructure.** Wave-1 cross-cutting modules (`atomic`, `errors`, `preflight`, `det`, `config`); APU emulator (Pulse 1, Pulse 2, Triangle, Noise, no DMC); FamiTracker engine handler; `audio_trace.lua` refinements; `lameenc` integration (for MP3 sub-flow tested but optional in slice 1); WAV `'smpl'` chunk loop encoding.

**Suggested story slicing.**

- A.1 — Cross-cutting scaffold + `qlnes audio … --format wav` on mapper-0 FT (one ROM, one engine, full pipeline). Marco's path on his happiest input.
- A.2 — `--format mp3` lights up via `lameenc`. Same pipeline, different sink.
- A.3 — Loop boundary detection (engine bytecode tier) + WAV `'smpl'` chunk emission.
- A.4 — Capcom engine handler + corpus expansion to mapper 2/4.
- A.5 — Generic fallback + `unverified` tagging. Closes FR11.

### Epic seam B — *Trustworthy coverage* (FR19–FR26, FR36–FR38)

**User value.** "What works today?" — `qlnes coverage` answers definitively, the corpus says yes.

**Embedded infrastructure.** Audit runner; bilan store + JSON Schema; corpus/manifest format; FCEUX reference-output generation script; coverage CLI rendering (table + JSON); freshness check.

**Suggested story slicing.**

- B.1 — `BilanStore` + `qlnes audit` minimal (just FR19, writes `bilan.json` for one ROM).
- B.2 — `qlnes coverage` table + JSON formatters (FR21, FR23, FR24).
- B.3 — Corpus manifest TOML format + `scripts/generate_references.py`.
- B.4 — Audit walks the full corpus with `pytest-xdist` parallelism (NFR-PERF-3).
- B.5 — Stale-bilan warning + `--refresh` (FR23, FR24).

### Epic seam C — *NSF + per-track metadata* (FR5, FR8 partial)

**User value.** Sara's journey 2: `qlnes nsf rom.nes --output ost.nsf` produces NSF2 + NSFe metadata that NSFPlay loads with per-track titles.

**Embedded infrastructure.** `NsfWriterV2` (`qlnes/nsf2.py`); NSFe chunk encoders (`tlbl`, `time`, `fade`, `auth`, `plst`); player-compatibility test (NSFPlay, GME).

**Suggested story slicing.**

- C.1 — NSF2 header + PRG payload (no NSFe chunks). Mapper-0 first.
- C.2 — NSFe metadata chunks. Player loads with track names.
- C.3 — Mapper-66 NSF (one of the experimental targets).
- C.4 — `tests/invariants/test_nsf_validity.py` against NSFPlay & GME.

### Epic seam D — *Pipeline-grade contract* (FR33–FR40, FR27–FR30)

**User value.** Lin's journey 3: subprocess invocation with stable exit codes, structured stderr JSON, refuse-to-overwrite, `--strict`, atomic writes, deterministic filenames. The vast majority of this is cross-cutting work — but it must be exercised by a subprocess-driven test that mimics Lin's pattern.

**Embedded infrastructure.** Refines `cli.py` to route every command through the cross-cutting machinery; ships `qlnes.toml.example`; ships completion install (FR30); ships `--strict`, `--force`, `--quiet`, `--debug`, `--no-progress`, `--no-hints`, `--color`.

**Suggested story slicing.**

- D.1 — Refactor `cli.py` to route every command through `qlnes/io/errors.py` and `atomic.py`. Add three-line error shape across all commands.
- D.2 — Pre-flight runner + per-command predicates.
- D.3 — `--strict`, `--force`, `--no-progress`, `--no-hints`, `--color` end-to-end.
- D.4 — `tests/integration/test_cli_audio.py` simulating Lin's subprocess pattern, including JSON parse on failure.

### Epic seam E — *Round-trip & assets — keep green* (FR1–FR4, FR13, FR14, FR17)

**User value.** Existing capabilities don't regress as the music workstream lands.

**Embedded infrastructure.** Tests porting from `tests/test_*.py` into `tests/unit/` or `tests/invariants/`; `analyze`, `recompile`, `verify` (round-trip variant) integration tests.

This epic is small (mostly testing/refactoring) but has independent user value: it's the regression net. **Recommended placement: parallelizable with epic A**, since it doesn't depend on any new module.

### Recommended sequencing

```
        ┌─ Epic E (Existing — regression net) ─────────────────┐
        │                                                       │
Epic A ─┴─→ Epic B (audit/coverage) ─→ Epic D (pipeline contract)
            │                          │
            │                          └─→ release v0.5 (MVP)
            │
            └─→ Epic C (NSF) — parallelizable with B from B.1 onwards
```

Epic A unlocks every other epic. Epic E is independent and runs alongside. Epic B follows A.5 (or earlier if A's first slice ships a useful bilan entry). Epic C parallels B from B.1. Epic D wraps the visible pipeline-contract refinements and ships the MVP.

This is *suggestion-grade* — `bmad-create-epics-and-stories` is the authoritative ordering.

### Anti-patterns the readiness report flagged — and how this seam structure avoids them

The readiness report's *Pre-emptive Epic Guidance* called out several common epic-shape violations. Mapped to this architecture's seam structure:

- ✓ **No technical-milestone epics.** None of A–E are "Build the APU emulator" or "Set up CI". They're user-value units. The APU emulator lands inside A.1.
- ✓ **No forward dependencies.** Epic A depends on nothing except the brownfield baseline. B/C/D depend on A. E is independent.
- ✓ **Each epic delivers user-visible value.** A = "Marco gets one WAV." B = "user sees coverage." C = "Sara gets NSF2+NSFe." D = "Lin's subprocess works against the locked contract." E = "existing features still green."
- ✓ **Each story inside an epic is a vertical slice.** A.1 includes the cross-cutting scaffold (infrastructure) bundled with the WAV emission (user value). The infrastructure does not stand alone as a story.

## Sign-off

This document is complete for the music-MVP and authorizes the next BMad phase: **`bmad-create-epics-and-stories` (CE)**.

### What this document delivers

- **Closes Q1** (APU backend) — own implementation, designed in step 8.
- **Closes Q2** (corpus / IP) — hashes-only manifest, no ROM redistribution, designed in step 11.
- **Closes Q3** (song-table detection) — `SoundEngine` ABC + four handlers, designed in step 9.
- **Closes Q4** (NSF format) — NSF2 + NSFe chunks, designed in steps 4 & 12.
- **Closes Q5** (loop-boundary detection) — three-tier strategy, designed in step 9.
- **Closes Q6** (MP3 encoder) — `lameenc==1.7.0`, fallback documented, in step 4.
- **Pins** the full tech stack (step 4) and dev/test tooling (step 4 + step 13).
- **Specifies** all 17 architectural components, their interfaces, and their wiring (step 5).
- **Locks** the repository structure (step 6) with a wave-based migration plan.
- **Designs** seven cross-cutting utility modules in interface depth (step 7).
- **Maps** every NFR to its enforcing mechanism with a verification test pointer (step 15).
- **Records** twenty ADRs with reverse cost (step 17) and twelve risks with mitigations (step 16).
- **Provides** epic seams for `CE` that match the readiness report's pre-emptive guidance (step 18).

### Acceptance criteria for `bmad-check-implementation-readiness` (next pass)

When `IR` re-runs after architecture and epics:

- ✓ Architecture exists (this file).
- ✓ Architecture answers all six readiness-report open questions.
- ✓ Architecture maps every PRD FR to one or more components (table in step 5).
- ✓ Architecture maps every NFR to a verification mechanism (step 15).
- ✓ Architecture provides epic seams compatible with PRD FR tags (step 18).

The PRD's 28 MVP FRs are explicitly addressed:

| FR range | Components closing | Epic seam |
|---|---|---|
| FR1–FR4 | C1, C2, C3, C6 | E |
| FR5 | C13, C9, C10 | A.1 (mapper-0), C.* (NSF flavor) |
| FR6, FR7 | C10, C11 | A.1, A.2 |
| FR8 | CLI flag | A.1 |
| FR9 | `det.deterministic_track_filename` | A.1 |
| FR10 | C9 (per-engine `walk_song_table`) | A.1+A.4 |
| FR11 | C8 (APU) + C12 (oracle) + C9 (engines) | A.1, A.4, A.5 |
| FR13–FR15 | C5, C4 | E |
| FR17, FR18 | C5, C8, C12 | E (round-trip), A.* (audio variant) |
| FR19–FR26 | C14, C15 | B.* |
| FR27–FR29 | C16 | A.1 (scaffold), D.* (polish) |
| FR30 | Typer install-completion | D.* |
| FR33–FR40 | C17 (`io/{atomic,errors,preflight}`) | A.1 (scaffold), D.* |

### Next BMad action

**Run `bmad-create-epics-and-stories` (CE).** Use:

- this architecture's step 18 as the seam structure;
- the UX design's §14 epic suggestions as a sanity check;
- the readiness report's pre-emptive epic guidance to avoid common shape violations.

Then **re-run `bmad-check-implementation-readiness` (IR)** for a real FR↔epic↔story coverage audit.

---

*End of Architecture Decision Document — qlnes (steps 01–19, 2026-05-03)*
