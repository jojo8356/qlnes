---
stepsCompleted: ['step-01-init', 'step-02-principles', 'step-03-ia', 'step-04-interaction', 'step-05-output', 'step-06-errors', 'step-07-progress', 'step-08-help', 'step-09-accessibility', 'step-10-pipelines', 'step-11-samples', 'step-12-locked-decisions']
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03.md
  - _bmad-output/project-context.md
  - qlnes/cli.py
projectType: 'cli_tool+developer_tool'
workflowType: 'ux-design'
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
scope_note: |
  PRD Section "Implementation Considerations" explicitly skips visual_design,
  ux_principles (graphical), touch_interactions, store_compliance — qlnes is a
  CLI tool with no GUI and no app store. This document covers the dimensions
  that DO apply to a CLI/scripting product: IA, interaction model, terminal
  output, error UX, progress feedback, help, accessibility (TTY/color/locale),
  and pipeline ergonomics.
---

# UX Design Document — qlnes

**Author:** Johan
**Date:** 2026-05-03
**Status:** Draft v1 — locks the UX surface for the music-MVP. Updated when MVP feedback identifies friction.

---

## 1. Overview & Scope

### 1.1 Project type & affordances

`qlnes` is a Typer-based Python CLI invoked via `python -m qlnes <command>` (and, post-Growth, via the bare entry point `qlnes <command>`). It is a **fire-and-forget batch tool** — every invocation takes a ROM, runs a single workflow, writes one or more artifacts to disk, and exits. There is no daemon, no REPL (deferred to Vision FR32), no networked surface, and no GUI.

The product has **two equally-weighted user surfaces**:

1. **Human terminal users** (Marco, Sara from PRD journeys) — interactive shell, expects helpful output, colors when supported, formatted tables, learnable command names.
2. **Pipeline consumers** (Lin from PRD journeys) — `subprocess`-driven, expects deterministic exit codes, structured `stderr` payloads, machine-readable `stdout`, and zero ceremony (no spinners, no prompts).

These two surfaces share the same binary. The behavioural differences (color on/off, progress bar on/off, table vs JSON) are driven by **runtime detection of TTY-ness** and a small set of explicit flags. There is no `--script` mode, no `--interactive` mode — the tool reads its environment.

### 1.2 What this document is not

Per PRD §Implementation Considerations, the following sections are **not part of this product**:

- Visual / graphical design (no GUI).
- Iconography, typography, color systems beyond ANSI terminal palettes.
- Touch / gesture / pointer interactions.
- App-store compliance (icons, screenshots, ratings).
- Onboarding flows beyond `--help` and `README`.

Anything in this document that resembles "visual design" is terminal-text-rendering only.

### 1.3 In scope (this document locks)

1. **UX principles** — the few invariants every command must respect.
2. **Information architecture** — command tree, sub-noun grammar, naming rules.
3. **Interaction model** — invocation grammar, layered configuration, flag semantics, mutual exclusivity.
4. **Output design** — `stdout` content per command, `stderr` content, line shape, color rules, locale rules.
5. **Error UX** — taxonomy, message shape, structured JSON payload, hint conventions.
6. **Progress feedback** — TTY detection rules, what gets a spinner / bar / nothing.
7. **Help & discoverability** — `--help` style, `--version`, completion install, coverage matrix as discovery surface.
8. **Accessibility** — color independence, screen-reader friendliness, locale.
9. **Pipeline UX** — determinism, atomicity, exit-code contract usage patterns.
10. **Sample sessions** — terminal mockups for every PRD journey + the most likely error paths.

---

## 2. UX Design Principles

The product has six UX invariants. Every command, every flag, every message must respect all six. When two invariants conflict, the one higher in this list wins.

### P1 — One command, one artifact, one format, one exit

Every invocation does **exactly one thing**. Compound operations (e.g. "extract audio AND verify AND build NSF") are achieved by piping multiple invocations, not by stacking flags. This keeps the mental model linear, makes scripting trivial, and removes ambiguity in error reporting.

> **Why.** The PRD defines `qlnes` as fire-and-forget. Every flag added that changes the artifact written is a flag the pipeline integrator (Lin) has to know about. Single-purpose commands keep the contract small.

**Implication.** If a feature feels like it wants to be `audio --and-verify`, that's a sign it should be its own command (`audit` already exists for this reason).

### P2 — Determinism is a UX feature

For the same ROM and same flags, output filenames, output bytes, and output ordering are identical across runs and across hosts. Wall-clock timestamps, hostnames, and locale-formatted numbers are forbidden from any artifact (PRD NFR-REL-2). The single audited exception is `bilan.json`'s `generated_at` field — which is provenance metadata, not part of any equivalence-checked artifact.

> **Why.** Determinism enables pipeline caching, byte-identical CI runs, and trust. A user who can't predict the filename of `track-04.wav` can't write a pipeline against it.

**Implication.** No `Last modified by ...` lines. Locale-independent number formatting in artifacts (no `1 234,5` — always `1234.5`). Stable iteration order on dicts and sets.

### P3 — Loud failure, never partial output

If `qlnes` cannot produce the full requested artifact correctly, it produces **nothing** for that artifact and exits non-zero. Atomic writes (PRD FR35) ensure a crash never leaves a half-written file on disk. There is no `WARNING: track 4 came out wrong, you got 1, 2, 3` — that's a failure of the whole invocation.

> **Why.** Silent partial success destroys trust and produces hard-to-diagnose downstream bugs. The product's value proposition is strict equivalence; degraded fallbacks contradict it.

**Exception.** The `unverified` audio engine fallback (FR11) is the *only* graceful degradation. It is loudly tagged in `bilan.json` and `coverage`, never reported as `pass`, and is opt-out via `--strict`.

### P4 — The CLI is the contract, the code is not

Command names, flag names, flag semantics, exit codes, structured `stderr` JSON keys, and `stdout` schemas are versioned under the project's semver discipline. **Internal Python modules are not** (PRD §169). Users and pipelines may rely on the CLI; they may not import `qlnes.audio`.

> **Why.** Without this rule, every refactor breaks consumers. With this rule, the team can move fast inside the codebase while presenting a stable surface.

**Implication.** New flags are additive. Renaming a flag is a major version bump. `--help` text is part of the contract (machine-parsed by Typer-completion users); breaking changes to `--help` shape need release-note callouts.

### P5 — Two audiences, one binary, zero modes

Behaviour adapts to the environment, not to a flag. When `stdout` is a TTY, color is enabled, tables are aligned, and progress is shown. When `stdout` is piped, color is stripped, progress is silent, and machine-readable formats (JSON when the command supports it) are preferred or available via flag. There is no `--interactive` flag; there is no `--script` flag; there is `NO_COLOR`, `--no-progress`, and `--format json` for explicit overrides.

> **Why.** A "mode flag" is a foot-gun: pipelines forget to set it and humans forget to unset it. Environment detection plus a small explicit-override set covers every case. This mirrors the well-established conventions of `git`, `ripgrep`, `cargo`.

### P6 — Errors carry their fix

Every error message answers three questions in this order: **what failed, why, what to do**. Stack traces are suppressed by default (FR40); the human-readable line is curt; the structured JSON line carries the machine fields. Hint text (`hint: ...`) appears on a separate line and is the "what to do" channel.

> **Why.** A mapper-5 user (Marco journey 4) does not need a Python traceback; they need to know that mapper 5 audio is not yet supported, that static analysis still works for them, and where to track the work. Errors that include the next action keep the user out of the issue tracker.

**Implication.** Every error class in the taxonomy below has a default hint string. Hints are written in second person, present tense, action-first ("Run `qlnes coverage`…"). Hints can be silenced with `--no-hints` for pipelines that find them noisy.

---

## 3. Information Architecture

### 3.1 Command tree (locked for MVP)

```
qlnes
├── analyze          [Existing]   produce STACK.md, optionally ASM, optionally assets
├── recompile        [Existing]   reassemble annotated ASM → byte-identical .nes
├── verify           [Existing]   round-trip equivalence on a single ROM
│   └── --audio                   run the audio equivalence invariant against FCEUX
├── audio            [Existing*]  render audio (--format wav|mp3|nsf)
├── nsf              [Existing*]  emit a standalone NSF
├── audit            [MVP-new]    run every invariant on the test corpus → bilan.json
├── coverage         [MVP-new]    print/JSON the per-mapper, per-engine support matrix
└── shell            [Vision]     interactive REPL — out of MVP scope
```

`*` Existing commands receive new flags / contract refinements in the MVP (see PRD §Music-MVP additions); the command name is unchanged.

### 3.2 Naming rules

- **Verbs only as command names.** `analyze`, `verify`, `recompile`, `audit` — what the tool *does*. `audio` and `nsf` are nouns, kept for backwards compatibility (already shipped); they implicitly mean "render audio" / "emit NSF". A new noun-named command is a smell — challenge it before adding.
- **Lowercase, single word, no separators.** No `verify-audio`, no `extract_assets`. Sub-functionality is a flag (`--audio`, `--assets`).
- **Flags follow GNU long-form convention.** `--output`, `--format`, `--strict`. Short forms exist only for the four most-used: `-o` (output), `-q` (quiet), `-f` (force, where applicable), `-h` (help — Typer default).
- **Boolean flags are positive by default.** `--force`, `--strict`, `--debug`. Negative flags (`--no-dynamic`, `--no-progress`, `--no-hints`) opt *out* of an enabled-by-default behaviour. The `--no-X` form is reserved for that semantic — never used as a primary flag name.
- **Never both.** A flag that can be set positively and negatively (e.g. `--color` / `--no-color`) is one flag with the standard `--color {auto,always,never}` enum, not two booleans.

### 3.3 Argument vs flag

- **Positional argument:** the ROM. Always exactly one ROM per invocation. No globs handled by `qlnes` — the shell expands them, and `qlnes` rejects multiple ROMs with a clear error. The user composes via `xargs` or a `for` loop.
- **Output (`-o` / `--output`):** the *destination*. Always a flag, never positional. This is opposite to `cp`'s convention but correct for a single-input → single-output tool — the input is the salient noun, the output is parametric.
- **Behaviour flags:** `--strict`, `--force`, `--quiet`, `--debug`, `--no-progress`, `--no-hints`, `--format`. All optional. All have defaults that suit the human-TTY case; pipelines opt into stricter / quieter behaviour explicitly.

### 3.4 Input/output discipline (the noun-rules)

| Concept | Singular | Plural | Notes |
|---|---|---|---|
| ROM | One per invocation | Never | Compose via shell |
| Tracks | Per-track filenames are deterministic | Lives in a directory | `audio --output tracks/` writes N files |
| `bilan.json` | One per repo | Never | `--bilan path` overrides |
| Coverage | Read from `bilan.json`, never recomputed in `coverage` unless stale | Never | `audit` is the only writer |

This split — `audit` writes, `coverage` reads, `bilan.json` is the boundary — keeps each command single-purpose (P1) and makes coverage near-instant (NFR-PERF-4).

---

## 4. Interaction Model

### 4.1 Invocation grammar

```
qlnes <command> [<positional>] [<flags>...]
```

- Exactly one `<command>`. Subcommands are flat (no `qlnes audio render`).
- Exactly zero or one positional argument per command (the ROM, or for `verify`: original + optional recompiled).
- Flags are order-independent, may appear before or after the positional.
- `--` ends flag parsing. Filenames starting with `-` must come after `--`.
- `qlnes` with no args prints `--help` and exits `0` (Typer's `no_args_is_help=True`).
- `qlnes <command>` with no args, where the command requires the ROM, exits `64` and prints the command-specific `--help`.

### 4.2 Layered configuration (PRD FR27)

Four layers, lowest to highest precedence:

1. **Built-in defaults.** Hard-coded in code. Examples: `--format wav` for `audio`, `--no-strict`, `--color auto`, `--bilan ./bilan.json`.
2. **`qlnes.toml`** — searched in this order: `--config <path>` (if passed), `$PWD/qlnes.toml`, ROM's parent directory's `qlnes.toml`. The first found wins; merging across files is intentionally not supported (would defeat the layering).
3. **Environment variables** — every flag has a corresponding `QLNES_<UPPER_SNAKE>` variable. `--format wav` ⇔ `QLNES_FORMAT=wav`. The `QLNES_` prefix is reserved.
4. **CLI flags** — final say. Anything on the command line overrides every layer below.

**Precedence display.** `qlnes <cmd> --explain-config` (post-MVP, Growth) prints the resolution chain for every flag — useful for debugging "why is the bilan path wrong in CI". MVP has no built-in introspection; users debug by running with `--debug`, which logs the resolved config to `stderr` after pre-flight.

**Layer types.** Every layer accepts the same value space — strings, booleans (`true`/`false`/`yes`/`no`/`1`/`0` for env, native bool for TOML, presence-of-flag for CLI), enums (validated), paths. No JSON in env vars. No `qlnes.toml` includes. Simple beats clever.

### 4.3 Flag semantics & mutual exclusivity

The full music-MVP flag inventory (additive over the existing CLI):

| Flag | Type | Commands | Purpose |
|---|---|---|---|
| `-o, --output PATH` | path | all writers | Destination file or directory. Required for `audio`, `nsf`, `recompile`. |
| `--format {wav,mp3,nsf}` | enum | `audio` | Output container. One per invocation. |
| `--bilan PATH` | path | `audit`, `coverage` | Override `bilan.json` location. |
| `--refresh` | bool | `coverage` | Force re-`audit` even if cached `bilan.json` is fresh. |
| `--strict` | bool | all | Warnings become errors. CI passes this. |
| `--force` | bool | all writers | Permit overwriting an existing output. Default: refuse with code `73`. |
| `-q, --quiet` | bool | all | Suppress informational `stdout`. Errors still go to `stderr`. |
| `--debug` | bool | all | Log internal state and stack traces to `stderr`. |
| `--no-progress` | bool | long-running | Silence progress bars/spinners (forced silent in non-TTY). |
| `--no-hints` | bool | all | Strip `hint:` lines from error output. |
| `--color {auto,always,never}` | enum | all | Color override; default `auto`. `NO_COLOR` env beats `auto`. |
| `--config PATH` | path | all | Override `qlnes.toml` discovery. |
| `--frames INT` | int | `audio` | Render duration in NTSC frames (existing flag). |
| `--keep-intermediate` | bool | `audio` | Keep TSV trace + intermediate WAV. |
| `--no-dynamic` | bool | `analyze` | Disable cynes-based dynamic discovery. |
| `--asm PATH` | path | `analyze` | Also write annotated ASM. |
| `--assets PATH` | path or `auto` | `analyze` | Extract assets into directory. |
| `--verify` | bool | `analyze` | Run round-trip after analysis. |
| `--audio` | bool | `verify` | Run audio equivalence rather than ROM round-trip. |
| `--install-completion {bash,zsh,fish,powershell}` | enum | top-level | Typer's built-in completion installer (FR30). |
| `--version` | bool | top-level | Print `qlnes <version>` and exit. |
| `-h, --help` | bool | all | Help (Typer default). |

**Mutual exclusivity rules:**

- `-q` and `--debug` are mutually exclusive (cannot suppress info AND emit verbose). Setting both → exit `64` with `qlnes: error: --quiet and --debug are mutually exclusive`.
- `--color always` and `NO_COLOR=1` — explicit flag wins. Document this in `--help`.
- `--format mp3` requires LAME; if missing, fail pre-flight with code `70` and a hint pointing at `scripts/install_audio_deps.sh`.
- `audit --refresh` is meaningless (`audit` always refreshes) and is silently ignored — no error, no warning. `coverage --refresh` is the meaningful spelling.

### 4.4 The `qlnes.toml` schema (locked)

```toml
# qlnes.toml — sits at repo root or beside the ROM. UTF-8, TOML 1.0.

[default]
output_dir = "./out"             # default for --output where applicable
quiet = false
bilan_file = "./bilan.json"
strict = false
color = "auto"                   # auto | always | never
hints = true                     # show hint: lines on errors
progress = true                  # show progress bars in TTY mode

[audio]
format = "wav"                   # wav | mp3 | nsf
frames = 600                     # default render length, NTSC frames
reference_emulator = "fceux"     # locked in MVP; future: "mesen"

[verify]
strict = true                    # CI-style: warnings fatal
audio = false                    # default to round-trip; opt into audio

[audit]
parallel = true                  # opt-out for debugging
corpus_dir = "./corpus"          # location of the test ROM corpus

[coverage]
format = "table"                 # table | json
```

- **Unknown keys** trigger a warning by default, an error under `--strict`. Typo protection.
- **Unknown sections** are warned (not errored) under `--strict` — gives the user room to forward-declare future sections.
- **Per-command sections override `[default]`**; `[default]` is the floor.
- **Environment variables** map: `QLNES_AUDIO_FORMAT=mp3` overrides `[audio] format`. Hierarchy preserved via underscore.

---

## 5. Output Design

### 5.1 The two output streams

`qlnes` distinguishes between `stdout` and `stderr` strictly:

- **`stdout`** — *the artifact's data or the user-requested output*. For `coverage`: the table or JSON. For `audit`: nothing in the default mode (the artifact is `bilan.json` on disk); JSON summary if `--format json`. For `audio`/`nsf`/`analyze`/`recompile`: nothing meaningful — these write files, not data streams.
- **`stderr`** — *informational logs, progress, warnings, errors*. Everything that is not the requested output. `-q` silences only the informational subset of `stderr`; errors and warnings still pass through (with `--quiet --strict`, warnings are fatal so they pass too).

This separation is a hard invariant. A pipeline doing `qlnes coverage --format json | jq` must work without mangling.

### 5.2 Default `stdout` per command (MVP)

| Command | Default `stdout` | `--quiet` `stdout` | `--format json` `stdout` |
|---|---|---|---|
| `analyze` | (empty — writes to disk) | (empty) | n/a |
| `recompile` | (empty) | (empty) | n/a |
| `verify` | (empty; on success a single line `"ok: <summary>"` to stdout) | (empty) | `{"status":"pass","details":...}` (Growth) |
| `audio` | (empty — writes WAV/MP3/NSF) | (empty) | n/a |
| `nsf` | (empty — writes NSF) | (empty) | n/a |
| `audit` | (empty — writes `bilan.json`) | (empty) | one-line JSON summary |
| `coverage` | aligned table (see §5.3) | aligned table (still useful even quiet) | one JSON document |

> **Note on `verify`'s `ok:` line.** This is the one place the CLI prints to `stdout` outside of `coverage`. Rationale: `verify` is the only command whose *output* is a verdict, not a file. The verdict has to live somewhere; `stdout` is the right place. The line is short, deterministic, and parsable: `ok: round-trip identical (32768 PRG bytes, 8192 CHR bytes)`.

### 5.3 Coverage table format

`qlnes coverage` (default, TTY) — example:

```
mapper  artifact  status      pass     total   engines
0       analyze   ✓ pass        15/15
0       nsf       ✓ pass        15/15            famitracker:15
0       audio     ✓ pass        15/15            famitracker:15
0       verify    ✓ pass        15/15
1       analyze   ✓ pass        12/12
1       audio     ⚠ partial      8/12            famitracker:8 unknown:0/4 (unverified)
1       nsf       ⚠ partial      8/12            famitracker:8 unknown:0/4 (unverified)
1       verify    ✓ pass        12/12
4       analyze   ✓ pass         3/3
4       audio       missing                       (mapper 4 audio not yet supported)
66      analyze   ✓ pass         8/8
66      audio     ✓ pass         8/8             famitracker:8

Generated: 2026-05-03T14:30:00Z (qlnes 0.x.y, fceux ref)
Bilan: ./bilan.json
```

Rules:

- **Symbols.** `✓ pass`, `⚠ partial`, `✗ fail`, `… unverified`, `· missing`. Symbols prefix the status text — never replace it. Color (when active) tints the symbol+status: green pass, yellow partial/unverified, red fail, dim missing.
- **Locale.** ASCII fallback automatic when terminal locale is not UTF-8: `[OK] pass`, `[WARN] partial`, `[FAIL] fail`, `[??] unverified`, `[--] missing`.
- **Sort order.** Mapper ascending, then artifact in the canonical order `analyze, nsf, audio, verify` (deterministic). Never sorted by status.
- **Engine column.** Empty for non-audio rows. For audio/nsf rows, list every engine present, format `name:passed[/total][ note]`. The synthetic `unknown` engine always carries the `(unverified)` note.

`qlnes coverage --format json` — emits `bilan.json` as-is to `stdout`. No transformation. No re-formatting. The on-disk file *is* the JSON contract. (This is the same reason `audit` writes JSON to disk and not to `stdout` by default — disk is where it belongs; `stdout` just happens to be a faithful echo.)

### 5.4 Default `stderr` per command (informational lines)

The existing CLI uses an arrow-glyph prefix style: `→ lecture de <rom>`, `✓ STACK.md écrit`. The MVP locks this style for all commands.

```
→ <progressive action sentence in active voice>      # something happened
✓ <completed action with result location>            # success milestone
⚠ <warning, non-fatal>                                # warning (only with --strict, fatal)
✗ <failure in this step>                             # only when proceeding past it (rare)
```

Locale: French is the default for `stderr` info lines (existing code is in French; the user is francophone). English fallback gated by `LANG=en_*` or `QLNES_LANG=en`. Errors and warnings have French + English variants in the message catalog (post-MVP localization scaffolding); MVP ships French informational + English errors as a pragmatic compromise (errors are more often grepped by pipelines, which expect English keywords).

> **Decision.** Match the codebase's existing tone: French informational (`→ analyse statique…`), English error keywords (`qlnes: error: unsupported_mapper`). Pipeline integrators (Lin) pattern-match on the English `error:` token and the JSON. End-users (Marco, Sara) read the French progress lines.

Color in `stderr`: arrow-glyphs are dim, `✓` green, `⚠` yellow, `✗` red. `qlnes: error:` prefix is bold red. The JSON line after an error is dimmed (it's machine-only). Color obeys `--color`/`NO_COLOR`/TTY detection.

### 5.5 Quiet, debug, and the line budget

- **Default mode.** Every command emits at most ~1 line per phase to `stderr`. A typical successful `audio` run is 4–6 lines. `audit` is the exception — it emits one line per ROM in the corpus to give the user (or CI log) traceability.
- **`--quiet`.** Suppresses every informational line (`→`, `✓`). Warnings and errors still pass.
- **`--debug`.** Adds: resolved configuration (post-pre-flight), per-step timings, per-ROM cache hit/miss for `audit`, full Python tracebacks on errors. Debug output lines are prefixed `debug:` and dimmed in color mode.

Rule of thumb: **no command should ever emit more than one line of output per second in default mode** (excluding progress bars). If a command is silent for 10+ seconds, it must be running an explicit progress indicator.

---

## 6. Error UX

### 6.1 Error message anatomy

Every error follows this exact shape on `stderr`:

```
qlnes: error: <one-line, lower-case, machine-friendly reason>
hint: <one-line, sentence-case, action-first guidance>
{"code": <int>, "class": "<snake_case>", ...class-specific fields...}
```

Three lines, in this order. The first is the human-grepable summary; the second is the next action; the third is the machine-parsable payload. `--no-hints` suppresses line 2. `--debug` appends a fourth, fifth, … set of `debug:` lines with the traceback.

### 6.2 Error class taxonomy (locked)

| `class` | Exit | When | Example reason | Example hint |
|---|---|---|---|---|
| `usage_error` | 64 | Bad CLI invocation | `--quiet and --debug are mutually exclusive` | `Pass only one of these flags.` |
| `bad_format_arg` | 64 | Invalid enum value | `--format expects one of {wav,mp3,nsf}, got 'flac'` | `Run \`qlnes audio --help\` to see valid formats.` |
| `bad_rom` | 65 | Not iNES / corrupt header | `not an iNES ROM (magic bytes mismatch)` | `Verify the file is a .nes ROM, not .nsf or .zip.` |
| `missing_input` | 66 | File not found | `ROM not found: <path>` | `Check the path; cwd is <pwd>.` |
| `internal_error` | 70 | Bug | `internal error: <short class name>` | `Re-run with --debug and open an issue.` |
| `cant_create` | 73 | Output unwritable | `cannot write <path>: file exists (use --force to overwrite)` | `Add --force, or pick a different --output path.` |
| `io_error` | 74 | Mid-write I/O failure | `I/O error during write to <path>` | `Check disk space and permissions on <dir>.` |
| `unsupported_mapper` | 100 | Mapper × artifact unsupported | `mapper 5 (MMC5) audio extraction is not yet covered` | `Run \`qlnes coverage\` to see what's supported. Static analysis still works.` |
| `equivalence_failed` | 101 | Audio/round-trip diff | `audio PCM mismatch vs FCEUX reference (frame 14283)` | `Re-run with --debug to dump the divergence frame.` |
| `missing_reference` | 102 | FCEUX corpus output absent | `FCEUX reference not found for ROM <sha256>` | `Generate the reference: see corpus/README.md.` |
| `interrupted` | 130 | SIGINT | `interrupted` | (no hint — the user did this on purpose) |

### 6.3 The structured JSON payload

Every error emits a single-line JSON object on the line after the `qlnes: error:` line (or after the `hint:` line if present). Required fields:

- `code` (int) — matches the exit code.
- `class` (string) — one of the snake_case names above.
- `qlnes_version` (string) — for bug reports.

Class-specific fields:

| Class | Extra fields |
|---|---|
| `bad_rom` | `path`, `rom_sha256` (if computable), `magic_bytes_seen` (hex) |
| `missing_input` | `path`, `cwd` |
| `cant_create` | `path`, `cause` (`exists`, `permission_denied`, `not_a_directory`, `parent_missing`) |
| `unsupported_mapper` | `mapper`, `artifact`, `rom_sha256`, `engine` (if relevant), `track_url` (URL to coverage matrix in repo) |
| `equivalence_failed` | `rom_sha256`, `artifact`, `divergence_frame` (int, audio) or `divergence_offset` (int, ROM bytes), `expected_hash`, `actual_hash` |
| `missing_reference` | `rom_sha256`, `expected_path` |

JSON is **single-line** — the parser is line-based. Newlines inside string values are escaped. UTF-8 throughout. Numbers are JSON numbers (no `0x` hex even for mappers).

> **Why JSON-on-stderr instead of structured logging or syslog.** Pipelines parse `stderr`. Adding a side-channel (file, syslog, JSON-on-fd-3) doubles the integration surface. JSON-on-stderr after a grep-able prefix line gives Lin a one-liner: `qlnes audio … 2>&1 | grep '^{' | jq '.'`. Conventional, predictable, no extra plumbing.

### 6.4 Hint conventions

Hints are written as **imperative sentences in second person, action first**. Compare:

> ✗ "It would be a good idea to perhaps consider re-running with --debug for more information."
> ✓ "Re-run with --debug to see the divergence frame."

Hints reference flags or commands the user can run *right now*. They never reference internal modules ("see `qlnes/audio.py:render_rom_audio`"). They link to public docs (URLs in the README) for ongoing work like the mapper-coverage page. Hints are 1 line; if the explanation is longer, the hint points to a doc URL instead of trying to fit on one line.

Hints can be deferred — when the cause is unknown and only a class name is available, the hint is a generic but useful starting point ("Re-run with --debug and open an issue with the trace.") rather than nothing.

### 6.5 Warning UX

Warnings (without `--strict`) follow a similar three-line shape but to `stderr` only and without an exit:

```
qlnes: warning: <reason>
hint: <action>
{"class": "<snake_case>", ...}
```

Warning classes (initial set; extensible):

- `bilan_stale` — `bilan.json` older than source mtimes (FR23). Hint: `Run \`qlnes coverage --refresh\`.`
- `unknown_engine` — audio engine not recognized; output is frame-accurate, not sample-identical. Hint: `Run \`qlnes coverage\` to see covered engines.`
- `mp3_encoder_version` — encoder version differs from `bilan.json` lockfile, `MP3` byte-equivalence not guaranteed (PCM still is). Hint: `Pin LAME to <version> for byte-equivalent MP3.`

Under `--strict`, warnings re-class as the corresponding error and exit non-zero (`code: 70` if no specific code applies; `code: 101` for `unknown_engine` strict-mode).

---

## 7. Progress Feedback

### 7.1 The TTY decision tree

When a command starts, `qlnes` decides at most one of three feedback modes:

```
                  ┌─────────────────────┐
                  │  start of command   │
                  └─────────┬───────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
   --no-progress?    quiet AND no             stderr.isatty()?
         │           --debug?                  │
        Yes              Yes              ┌────┴────┐
         │                │              Yes        No
   silent             silent              │          │
                                     animated     line-per-step
                                     spinner/bar  (default for pipes)
```

Truth table summary:

| Condition | Feedback |
|---|---|
| `--no-progress` | none |
| `--quiet` (no `--debug`) | none |
| `stderr` not TTY | line-per-step only (no animation) |
| `stderr` is TTY, default | animated spinner/bar where appropriate, line-per-step elsewhere |
| `--debug` (regardless of TTY) | line-per-step + per-step timings + resolved config dump |

### 7.2 Where animation is and isn't used

Animations (spinner, % bar) are used **only** for steps with no informative interim output and a duration likely > 2 seconds:

- ✓ `→ analyse statique…` (a few seconds, opaque) → spinner
- ✓ `→ rendering audio (track 4 / 23)…` → progress bar with ETA
- ✓ `→ audit corpus (12 / 50 ROMs)…` → progress bar with ROM-rate
- ✗ `→ lecture de <rom>` (millisecond) → no animation
- ✗ `→ STACK.md écrit` (instant, success line) → no animation

Animation rules:

- **30 fps cap** for spinners; 1 Hz for `%`-bar redraws (no faster than the eye can read).
- **Fall back to plain text** when the terminal lacks `\r` cursor-up support (rare; `dumb` terminals).
- **Fall back to plain text** when output is being recorded by `script(1)` (heuristic: `TERM=dumb` or `SCRIPT=` set; not perfect but conventional).
- **One animation at a time** — never nested progress bars. If a step contains sub-steps, the bar is the parent and sub-steps log to a single replaced line above it.

### 7.3 Cancellation

Ctrl-C (SIGINT) at any point during an animated step:

1. The animation stops immediately.
2. A single line `qlnes: error: interrupted` is emitted to `stderr`.
3. JSON `{"code": 130, "class": "interrupted"}` follows.
4. Atomic-write semantics ensure no partial file remains on disk.
5. Process exits 130.

No "Are you sure?" prompt. No clean-up confirmation. SIGTERM is treated identically.

---

## 8. Help & Discoverability

### 8.1 `--help` style

Typer's default help output is acceptable as-is, with three customizations applied across all commands:

1. **A one-line `Description:` line** before the first paragraph, crisp and free of marketing language. *Bad:* "Powerful tool for next-gen ROM analysis." *Good:* "Analyse une ROM NES et génère STACK.md (+ ASM annoté + assets)."
2. **Examples section** at the end of every command's `--help`, two examples max (typical use, one less-common use). Inline, copy-pastable.
3. **A footer line** linking to the full doc URL — only when the command has a longer-form discussion that doesn't fit on screen.

`qlnes --help` (top-level) lists every command in the canonical order: `analyze, recompile, verify, audio, nsf, audit, coverage`. One-line description per command.

### 8.2 Version

`qlnes --version` prints exactly:

```
qlnes <semver>
```

No build date, no commit hash by default (would violate determinism if leaked into artifacts). `--version --debug` prints `qlnes <semver> (commit <sha>, built <date>)` for support cases — but only on `stderr`-equivalent of stdout, never recorded into any artifact.

### 8.3 Shell completion

`qlnes --install-completion <shell>` uses Typer's built-in mechanism (FR30). Supported shells: bash, zsh, fish, PowerShell. Behaviour:

- Prints the shell snippet to `stdout` if not running inside a writable shell init.
- Otherwise installs to the canonical per-shell location and prints the path on `stderr`.
- Exit `0` on success; `73` on permission failure with hint pointing at the manual install path.

Completion completes:

- Top-level commands.
- Per-command flags (Typer auto-generated).
- Enum values for `--format` and `--color`.
- File paths (default Typer behaviour).
- (Post-MVP) Mapper numbers from the live `bilan.json`. — out of MVP scope.

### 8.4 The coverage matrix as discovery surface

`qlnes coverage` is intentionally a **dual-use** UX feature: pipelines parse the JSON, and humans use the table to **discover what works**. A new user typing `qlnes coverage` after install learns immediately:

- which mappers are covered;
- which audio engines are recognized;
- where the gaps are.

This is the closest the product gets to onboarding. The table doubles as marketing — committing `bilan.json` to the repo means the GitHub README can render the matrix as a "what works today" badge.

The matrix is therefore **part of the UX**, not a debug artifact. Its layout is locked under the same semver discipline as command names.

---

## 9. Accessibility

### 9.1 Color independence

- **Color is never the sole conveyor of meaning.** Every status carries a symbol (`✓`, `⚠`, `✗`, `…`, `·`) and a word (`pass`, `partial`, `fail`, `unverified`, `missing`). A user with monochrome terminal, color-blindness, or `NO_COLOR=1` set sees the same information.
- **Symbol set is colorblind-safe.** Green/red have shape disambiguation (✓ vs ✗); yellow `⚠` differs from green `✓` by glyph, not just hue.
- **`--color {auto,always,never}` and `NO_COLOR`** environment variable both honored. `auto` = on-iff-`stderr.isatty()` and `TERM` is not `dumb`.

### 9.2 Locale & encoding

- **Default locale.** Match `$LANG`. Fallback to `C.UTF-8`. Output is always UTF-8.
- **ASCII fallback.** When the terminal cannot encode Unicode (e.g. `LANG=C`), substitute ASCII glyphs (`[OK]`, `[WARN]`, `[FAIL]`, `[??]`, `[--]`) for the symbol set.
- **No locale-aware number formatting** in any output. Integer thousands have no separator; floats use `.` (PRD NFR-REL-2 — determinism). Locale-aware printing creates non-deterministic hashes.
- **Date format.** ISO 8601 UTC (`2026-05-03T14:30:00Z`) only. No `May 3, 2026`.

### 9.3 Screen-reader friendliness

CLIs are accessible by default for screen readers (text-mode). The two practices to follow:

- **Don't lead lines with decoration alone.** `✓ STACK.md écrit : <path>` reads better than `✓ <path>` because the screen reader announces "checkmark, STACK.md written" — context first.
- **Avoid box-drawing characters in default mode.** The coverage table uses padded columns, not `│ │ ─` borders. Borders sound noisy through TTS. (`--format json` is the screen-reader-power-user's preferred mode; tables exist for sighted users.)

### 9.4 Keyboard / non-keyboard

CLI = keyboard. No accommodations needed beyond standard `readline`/Typer behaviour. Ctrl-C cancels (§7.3); piping works (P5); composability is implicit.

---

## 10. Pipeline & Scripting UX

### 10.1 The contract Lin actually uses

A pipeline integrator's mental model of `qlnes`:

```python
result = subprocess.run(
    ["qlnes", "audio", str(rom_path), "--format", "wav",
     "--output", str(out_dir), "--strict", "--no-progress", "--no-hints"],
    capture_output=True, text=True,
)

if result.returncode == 0:
    # Files in out_dir, named deterministically.
    # No stdout content to parse.
    pass
elif result.returncode == 100:
    # Unsupported mapper. Last stderr line is JSON.
    err = json.loads(result.stderr.splitlines()[-1])
    # err == {"code": 100, "class": "unsupported_mapper", "mapper": 5, ...}
elif result.returncode == 130:
    # User cancelled — caller probably propagates.
    raise KeyboardInterrupt
else:
    # Generic failure. JSON still parseable; payload class identifies kind.
    raise QlnesError.from_stderr(result.stderr)
```

This shape is the locked contract. Every flag and exit code in the table above is in service of this pattern.

**The recommended pipeline-mode flags:**

```
--strict            # warnings → errors
--no-progress       # silent in non-TTY anyway, but explicit defends against future changes
--no-hints          # easier line-based parsing
--color never       # belt-and-braces; --no-color also fine via NO_COLOR=1
--quiet             # only if you don't want the success ✓ line on stderr
```

Combined as `QLNES_STRICT=1 QLNES_PROGRESS=0 QLNES_HINTS=0 QLNES_COLOR=never qlnes …` in CI environments.

### 10.2 Atomic writes & idempotency

- Atomic writes (FR35) — every output goes through `<path>.tmp` + `rename`. A killed `qlnes` never leaves a half-file.
- Idempotency — a second invocation with the same flags produces the same output bytes (P2). It will refuse to overwrite by default (FR37) unless `--force`.
- Pre-flight (FR36) — fail early. Pipelines see the error before any output appears; restart cost is ~zero.

### 10.3 Deterministic filenames

For multi-output commands (`audio --output tracks/`), filenames are derived from:

```
<rom-stem>.<song-index-2-digit>.<engine>.<format>
```

Example: `metalstorm.04.famitracker.wav`. Index is the song-table position (zero-padded so lexicographic = numeric). Engine is the recognized engine name or `unknown`. Format is the extension. Lin's pipeline can predict every output filename from the input ROM path and song count.

> **Why `<rom-stem>` not `<sha256>`?** The user-supplied filename is friendlier in human contexts. Pipelines that need hash-stable names pass `--rename-by-hash` (Growth flag) to override. Both forms are deterministic.

### 10.4 The `bilan.json` schema is the API

For pipelines that consume `qlnes coverage --format json`, the schema is locked and versioned via the `qlnes_version` field at the top of `bilan.json`. A pipeline that breaks because `bilan.json` schema changed counts as a CLI-contract break (P4) and bumps qlnes major version.

---

## 11. Sample Sessions

### 11.1 Marco — happy path (PRD Journey 1)

```
$ python -m qlnes audio metalstorm.nes --format wav --output tracks/
→ lecture de metalstorm.nes
→ ROM : mapper=4  PRG=8 bank(s)
→ détection moteur audio… famitracker
→ rendu audio (23 / 23 pistes)…  [██████████████████] 100% ETA 0s
✓ 23 WAV écrits dans tracks/  (sha256 lockstep avec FCEUX)
$ ls tracks/
metalstorm.00.famitracker.wav  metalstorm.04.famitracker.wav  metalstorm.08.famitracker.wav  …
metalstorm.01.famitracker.wav  metalstorm.05.famitracker.wav  metalstorm.09.famitracker.wav  …
…
$ qlnes verify --audio metalstorm.nes
→ rendu audio (référence FCEUX)…
→ comparaison PCM…
✓ ok: audio identique (23/23 pistes, 178412800 échantillons)
$ echo $?
0
```

### 11.2 Sara — content creator (PRD Journey 2)

```
$ python -m qlnes nsf castlequest.nes --output ost.nsf --title "Castle Quest OST"
→ lecture de castlequest.nes
→ ROM : mapper=66  PRG=2 bank(s)
→ song-pointer table: 17 entrées (3 non-référencées)
✓ NSF écrit : ost.nsf  (load=$8000, init=$8000, play=$80F2)
$ python -m qlnes audio castlequest.nes --format wav --output tracks/
→ lecture de castlequest.nes
→ rendu audio (17 / 17 pistes, dont 3 non-référencées)…  [██████████████████] 100%
✓ 17 WAV écrits dans tracks/
$ ls tracks/
castlequest.00.famitracker.wav  …  castlequest.14.famitracker.wav
castlequest.15.famitracker.wav  ← non-référencée
castlequest.16.famitracker.wav  ← non-référencée
$ # Sara loads ost.nsf in NSFPlay; plays 17 tracks including the 2 demos.
```

### 11.3 Lin — pipeline integrator (PRD Journey 3)

```python
# audio_stage.py — Lin's pipeline
import json, subprocess, sys

result = subprocess.run(
    ["qlnes", "audio", "rom.nes", "--format", "wav",
     "--output", "tracks/",
     "--strict", "--no-progress", "--no-hints", "--color", "never"],
    capture_output=True, text=True,
)

if result.returncode == 0:
    # tracks/ contains the WAVs. Pipeline picks them up by glob.
    return list(Path("tracks/").glob("rom.*.wav"))

# Parse the trailing JSON line
err_line = result.stderr.strip().splitlines()[-1]
err = json.loads(err_line)
if err["class"] == "unsupported_mapper":
    sys.exit(f"audio stage skipped: mapper {err['mapper']} not yet supported "
             f"({err['track_url']})")
raise RuntimeError(f"qlnes failed: {err}")
```

In production this exits 0 most of the time. When mapper 5 lands, Lin logs and continues; her parent pipeline does the rest of the work without a crash.

### 11.4 Marco — unsupported mapper (PRD Journey 4)

```
$ python -m qlnes audio mmc5game.nes --format wav --output tracks/
→ lecture de mmc5game.nes
→ ROM : mapper=5  PRG=16 bank(s)
qlnes: error: mapper 5 (MMC5) audio extraction is not yet covered.
hint: Run `qlnes coverage` to see what's supported. Static analysis still works.
{"code":100,"class":"unsupported_mapper","mapper":5,"artifact":"audio","rom_sha256":"3f2a…","track_url":"https://github.com/jojo8356/qlnes#mapper-coverage","qlnes_version":"0.5.0"}
$ echo $?
100
$ # Marco runs static analysis instead — still works:
$ python -m qlnes analyze mmc5game.nes --asm out.asm
→ lecture de mmc5game.nes
→ ROM : mapper=5  PRG=16 bank(s)
→ analyse statique (QL6502 + heuristiques)…
✓ STACK.md écrit : mmc5game.STACK.md
✓ ASM annoté écrit : out.asm.bank0.asm  (bank 0/15)
✓ ASM annoté écrit : out.asm.bank1.asm  (bank 1/15)
…
```

### 11.5 Coverage discovery

```
$ qlnes coverage
mapper  artifact  status      pass     total   engines
0       analyze   ✓ pass        15/15
0       nsf       ✓ pass        15/15            famitracker:15
0       audio     ✓ pass        15/15            famitracker:15
0       verify    ✓ pass        15/15
1       analyze   ✓ pass        12/12
1       audio     ⚠ partial      8/12            famitracker:8 unknown:0/4 (unverified)
1       nsf       ⚠ partial      8/12            famitracker:8 unknown:0/4 (unverified)
1       verify    ✓ pass        12/12
4       analyze   ✓ pass         3/3
4       audio       missing                       (mapper 4 audio not yet supported)
66      analyze   ✓ pass         8/8
66      audio     ✓ pass         8/8             famitracker:8

Generated: 2026-05-03T14:30:00Z (qlnes 0.5.0, fceux ref)
Bilan: ./bilan.json
$ qlnes coverage --format json | jq '.results."4".audio'
null
```

### 11.6 Stale bilan warning

```
$ qlnes coverage
qlnes: warning: bilan.json is stale (generated 2026-04-12, qlnes/audio.py modified 2026-05-02)
hint: Run `qlnes coverage --refresh` to re-audit.
{"class":"bilan_stale","generated_at":"2026-04-12T...","newest_source_mtime":"2026-05-02T...","qlnes_version":"0.5.0"}

mapper  artifact  status      pass     total   engines
…  (the table prints anyway; warning, not error)

$ qlnes coverage --refresh
→ audit corpus (50 / 50 ROMs)…  [██████████████████] 100% ETA 0s
✓ bilan.json mis à jour
mapper  artifact  status      pass     total   engines
…
```

### 11.7 Strict mode — warning becomes error

```
$ qlnes coverage --strict
qlnes: error: bilan.json is stale (generated 2026-04-12, qlnes/audio.py modified 2026-05-02)
hint: Run `qlnes coverage --refresh` to re-audit.
{"code":70,"class":"bilan_stale","generated_at":"2026-04-12T...","qlnes_version":"0.5.0"}
$ echo $?
70
```

### 11.8 Refuse-to-overwrite

```
$ qlnes audio rom.nes --format wav --output tracks/
✓ 23 WAV écrits dans tracks/
$ qlnes audio rom.nes --format wav --output tracks/
qlnes: error: cannot write tracks/rom.00.famitracker.wav: file exists (use --force to overwrite)
hint: Add --force, or pick a different --output path.
{"code":73,"class":"cant_create","path":"tracks/rom.00.famitracker.wav","cause":"exists","qlnes_version":"0.5.0"}
$ echo $?
73
$ qlnes audio rom.nes --format wav --output tracks/ --force
✓ 23 WAV écrits dans tracks/  (overwrite)
```

### 11.9 Pre-flight failure (mp3 without LAME)

```
$ qlnes audio rom.nes --format mp3 --output tracks/
qlnes: error: MP3 encoder not found (LAME required)
hint: Run scripts/install_audio_deps.sh, or pass --format wav.
{"code":70,"class":"internal_error","detail":"missing_dependency","dep":"lame","qlnes_version":"0.5.0"}
$ echo $?
70
```

(Exit 70 because the user's invocation was valid — the failure is an environment issue. Some teams will argue 64; the locked decision is 70 because the user didn't pass a bad flag, the host is missing an expected dep.)

### 11.10 Cancellation mid-audit

```
$ qlnes audit
→ audit corpus (12 / 50 ROMs)…  [████░░░░░░░░░░░░░░] 24% ETA 22m
^C
qlnes: error: interrupted
{"code":130,"class":"interrupted","completed":12,"total":50,"qlnes_version":"0.5.0"}
$ echo $?
130
$ ls -la bilan.json    # not modified — atomic write was never finalized
-rw-r--r-- 1 johan johan 4233 May  2 14:12 bilan.json
```

---

## 12. Locked decisions (UX surface)

The following decisions are locked for the music-MVP and may only change with a major version bump:

| # | Decision | Rationale |
|---|---|---|
| L1 | Two output streams strictly: `stdout`=data, `stderr`=info+errors | P5; pipeline composability |
| L2 | Three-line error shape (`error:` line, optional `hint:` line, JSON line) | P6; one-grep machine parsing |
| L3 | Twelve-class error taxonomy (§6.2) | Bounded; covers every documented exit code |
| L4 | Coverage table is part of the contract | §8.4; doubles as discovery |
| L5 | French informational + English error keywords | Match user, match grep idiom |
| L6 | `--color {auto,always,never}` + `NO_COLOR` honored | Conventional; accessible |
| L7 | Symbols always paired with words | §9.1; color-independent |
| L8 | UTF-8 with ASCII fallback gated by locale | §9.2 |
| L9 | Refuse-to-overwrite default; `--force` to override | FR37 |
| L10 | Atomic writes; SIGINT leaves no half-file | FR35, §7.3 |
| L11 | Deterministic filenames `<rom>.<idx>.<engine>.<fmt>` | §10.3 |
| L12 | Six positive booleans + three negative (`--no-…`) only | §3.2 |
| L13 | One artifact per invocation; compose via shell | P1 |
| L14 | `audit` writes; `coverage` reads; `bilan.json` is the boundary | §3.4 |
| L15 | TTY detection drives feedback mode; no `--script` flag | P5, §7.1 |

## 13. Open questions (deferred to post-MVP)

These are intentionally not locked — the MVP ships without them, and the answers will come from real usage:

1. **Localization scope.** Should `qlnes` ship full French + English message catalogs, or stick to French-info / English-errors? Decision deferred to v0.7.
2. **Coverage matrix in CI artifacts.** Should `bilan.json` be auto-rendered to a Markdown badge for the GitHub README? Probably yes; deferred to Growth.
3. **`--explain-config` flag.** Useful for "why is the bilan path wrong in CI" debugging. Deferred to Growth (§4.2).
4. **`--rename-by-hash` flag.** Useful for content-addressable pipeline storage. Deferred to Growth (§10.3).
5. **Mapper-aware completion.** `qlnes coverage --mapper <TAB>` autocompletes from `bilan.json`. Deferred (§8.3).
6. **Interactive REPL** (`qlnes shell <rom>`). Vision-tier, FR32. Out of scope.
7. **`--profile` for ad-hoc named flag bundles** (e.g. `--profile ci` ≈ `--strict --no-progress --no-hints --color never`). Tempting; deferred until usage shows the bundles repeat in real CI configs.

## 14. Sign-off & next step

This document satisfies the BMad UX-design phase for a CLI/pipeline product. It locks every UX surface needed by `bmad-create-epics-and-stories` to slice the music-MVP into stories with concrete user-visible acceptance criteria.

**Acceptance criteria the next BMad step (`CE`) will use against this document:**

- Every MVP FR has a corresponding UX section it can cite.
- Every error class has an exit code, a hint, and a JSON shape (for AC test cases).
- Every command has a sample session in §11 (for AC examples).
- Every locked decision in §12 is testable via a sample command + expected output.

**Recommended next step.** Run `bmad-create-epics-and-stories` (CE). The 28 MVP FRs split naturally along the section boundaries above:

- Epic A — *Audio rendering & format selection* (FR5–FR11): UX §3.1, §5.2, §11.1–11.2.
- Epic B — *Audit & coverage matrix* (FR19–FR25): UX §5.3, §10.4, §11.5–11.6.
- Epic C — *Configuration & invocation surface* (FR27–FR30): UX §4.2–4.4, §8.
- Epic D — *Scripting contract* (FR33–FR40): UX §6, §7, §10, §11.3–11.4, §11.7–11.10.
- Epic E — *Pre-flight, atomicity, and refuse-to-overwrite* (FR35–FR37): UX §6, §11.8–11.10.

The architecture document (currently in progress at `step-03-starter`) needs to resolve its 6 open questions before `CE` can confidently bind stories to implementation modules. **In parallel**, the `architect` can pick up §11 sample sessions as integration-test fixtures.

---

*End of UX Design Document — qlnes (v1, 2026-05-03)*
