---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/research/technical-audio-nes-vers-mp3-et-extraction-des-musiques-de-roms-research-2026-07-22.md
---

# qlnes - Epic Breakdown

## Overview

Ce document fournit le breakdown complet des epics et stories pour la vague "get toutes les musics des ROMs" de `qlnes`, en decomposant le PRD, l'architecture, l'UX CLI et la recherche technique audio NES vers MP3.

## Requirements Inventory

### Functional Requirements

FR1: Charger un fichier iNES `.nes` et valider son header.
FR2: Produire `STACK.md`, resume technique humain d'une ROM inconnue.
FR3: Produire un disassemblage 6502 annote du PRG-ROM.
FR4: Executer la dynamic discovery via `cynes` quand disponible.
FR5: Extraire la soundtrack d'une ROM supportee en NSF via `qlnes nsf <rom>`.
FR6: Extraire la soundtrack en WAV par piste via `qlnes audio <rom> --format wav`, avec boucles preservees.
FR7: Extraire la soundtrack en MP3 par piste via `qlnes audio <rom> --format mp3`, encode depuis le meme PCM que WAV.
FR8: Choisir NSF, WAV ou MP3 via `--format`, un format par invocation.
FR9: Specifier un repertoire de sortie par piste via `--output <dir>` avec noms deterministes.
FR10: Parcourir exhaustivement la song-pointer table, y compris entrees non referencees.
FR11: Rendre WAV/MP3 par chemin direct ASM -> PCM, sample-identique a FCEUX pour engines reconnus; fallback frame-accurate `unverified` pour unknown; jamais de heuristique PCM comme primaire.
FR12: Etendre l'audio a tout mapper iNES couvert en Growth, un mapper a la fois.
FR13: Recompiler ASM annote en ROM byte-identique.
FR14: Extraire CHR-ROM en PNG sheets.
FR15: Round-trip PNG -> CHR byte-identique en Growth.
FR16: Extraire gameplay data tables en JSON/markdown en Vision.
FR17: Verifier un round-trip sur une ROM via `qlnes verify <rom>`.
FR18: Verifier l'equivalence audio d'une ROM via `qlnes verify --audio <rom>` contre FCEUX.
FR19: Auditer tout le corpus via `qlnes audit`, produire `bilan.json`.
FR20: `qlnes audit` sort `102` sans ecrire `bilan.json` si une reference FCEUX manque.
FR21: Lire la couverture via `qlnes coverage`, table ou JSON; axes mapper pour non-audio, `(mapper, audio engine)` pour audio.
FR22: `qlnes coverage` lance `audit` si `bilan.json` manque ou invalide.
FR23: `qlnes coverage` avertit si `bilan.json` est stale.
FR24: Forcer un re-audit via `qlnes coverage --refresh`.
FR25: `bilan.json` enregistre status, counts, failures et sous-map engines audio avec `unknown: unverified`.
FR26: Chaque release est gatee par 100% equivalence sur la portion corpus supportee.
FR27: Configurer via defaults, `qlnes.toml`, `QLNES_*`, flags CLI.
FR28: Toute valeur config/env est aussi exprimable par flag CLI.
FR29: `audio`, `verify`, `audit`, `coverage` honorent leurs sections config et `[default]`.
FR30: Installer shell completion bash/zsh/fish/PowerShell via Typer.
FR31: Installer via `pip install qlnes` en Growth.
FR32: Lancer un REPL `qlnes shell <rom>` en Vision.
FR33: Sortir avec exit codes documentes.
FR34: Prefixer toute erreur stderr par `qlnes: error:` puis JSON single-line.
FR35: Ecrire tout output atomiquement via `.tmp` + rename.
FR36: Executer preflight avant toute ecriture.
FR37: Refuser overwrite sans `--force`, exit `73`.
FR38: `--strict` rend les warnings fatals.
FR39: Non-TTY: pas de progress bars/prompts.
FR40: Stack traces masquees par defaut, visibles avec `--debug`.

### NonFunctional Requirements

NFR-PERF-1: `qlnes analyze <rom>` sur 32 KB termine en moins de 2 s.
NFR-PERF-2: `qlnes audio --format wav` rend chaque piste en <= 2x temps reel.
NFR-PERF-3: `qlnes audit` sur 50 ROMs termine en moins de 30 min localement.
NFR-PERF-4: `qlnes coverage` read-only sur `bilan.json` termine en moins de 100 ms.
NFR-PERF-5: RAM max par invocation sous 500 MB.
NFR-REL-1: memes inputs/versions/flags produisent outputs byte-identiques; PCM est hash canonique.
NFR-REL-2: aucun artefact ne contient wall-clock, hostname, username; exception documentee pour `bilan.json.generated_at`.
NFR-REL-3: parallelisme interne order-deterministic.
NFR-REL-4: ecritures atomiques.
NFR-REL-5: crash-free sur corpus supporte; erreurs internes code 70 + JSON.
NFR-PORT-1: Linux est plateforme canonique MVP.
NFR-PORT-2: macOS hors MVP, possible Growth.
NFR-PORT-3: Windows differe.
NFR-PORT-4: Python floor 3.11.
NFR-DEP-1: FCEUX est le seul hard external non-Python MVP.
NFR-DEP-2: Python deps floor-pinned; `lameenc` version-pin stricte pour equivalence MP3.
NFR-DEP-3: `cynes` optionnel et feature-gated.
NFR-DEP-4: nouveau hard external => update PRD.

### Additional Requirements

- Pas de starter greenfield; etendre le brownfield `python -m qlnes`.
- Ajouter modules `qlnes/io/atomic.py`, `qlnes/io/errors.py`, `qlnes/io/preflight.py`, `qlnes/det.py`, `qlnes/config/loader.py`.
- Ajouter `qlnes/audio/` avec APU emulator, engine plugins, renderer, trace model.
- Ajouter `qlnes/oracle/fceux.py` et `qlnes/audio_trace.lua`.
- Ajouter `qlnes/audit/bilan.py`, corpus manifest, reference generation.
- Implementer `SoundEngine` ABC avec detection, song enumeration, init/play addresses, loop boundaries.
- Utiliser NSF2 + NSFe chunks (`tlbl`, `time`, `fade`, `auth`, `plst`) pour metadata.
- Utiliser FCEUX comme oracle versionne, pas comme renderer produit.
- Corpus: hashes only, pas de ROMs ni references audio committees.
- Tests: pytest, matrices parametrisees, invariants PCM, determinisme, atomic kill, CLI subprocess.
- Maintenir la couverture audio par `(mapper, audio engine, expansion_audio)`.
- MP3 derive de PCM via `lameenc`; PCM reste l'artefact de preuve.

### UX Design Requirements

UX-DR1: Command tree MVP plat: `analyze`, `recompile`, `verify`, `audio`, `nsf`, `audit`, `coverage`.
UX-DR2: Une invocation = un artefact/formats; `--format {wav,mp3,nsf}` controle la sortie audio.
UX-DR3: ROM unique en positional; output toujours via `--output`.
UX-DR4: Flags GNU long-form, shorts limites a `-o`, `-q`, `-f`, `-h`.
UX-DR5: Non-TTY silencieux et scriptable; pas d'interactif.
UX-DR6: Erreurs trois lignes maximum: message humain, JSON structuré, hint optionnel.
UX-DR7: `--strict`, `--force`, `--quiet`, `--debug`, `--no-progress`, `--no-hints`, `--color` respectent les semantiques UX.
UX-DR8: Noms de pistes deterministes `<rom-stem>.<song-index-2-digit>.<engine>.<format>`.
UX-DR9: `coverage` affiche table lisible et JSON stable.
UX-DR10: Accessibilite CLI: ne pas dependre de la couleur, UTF-8, table lisible screen-reader.
UX-DR11: Refus overwrite explicite et actionable.
UX-DR12: Preflight MP3 sans LAME donne erreur claire et hint install.

### FR Coverage Map

FR1: Epic 5 - garde-fou ingestion ROM existante.
FR2: Epic 5 - garde-fou `STACK.md`.
FR3: Epic 5 - garde-fou disassemblage annote.
FR4: Epic 5 - garde-fou dynamic discovery.
FR5: Epic 3 - emission NSF.
FR6: Epic 1 - extraction WAV par piste.
FR7: Epic 1 - extraction MP3 depuis PCM.
FR8: Epic 1 et Epic 3 - choix format audio/NSF.
FR9: Epic 1 et Epic 4 - repertoire et noms deterministes.
FR10: Epic 1 - song-table exhaustive.
FR11: Epic 1 - ASM -> PCM direct, tier-1/fallback.
FR12: Epic 6 - extension mapper/engine post-MVP.
FR13: Epic 5 - garde-fou recompile.
FR14: Epic 5 - garde-fou assets PNG.
FR15: Epic 6 - Growth CHR round-trip.
FR16: Epic 6 - Vision gameplay data.
FR17: Epic 5 - garde-fou verify ROM.
FR18: Epic 2 - verify audio single ROM.
FR19: Epic 2 - audit corpus.
FR20: Epic 2 - missing reference exit 102.
FR21: Epic 2 - coverage table/JSON.
FR22: Epic 2 - coverage auto-audit.
FR23: Epic 2 - stale warning.
FR24: Epic 2 - refresh.
FR25: Epic 2 - schema `bilan.json`.
FR26: Epic 2 - release gate 100%.
FR27: Epic 4 - config layers.
FR28: Epic 4 - flag parity.
FR29: Epic 4 - command config sections.
FR30: Epic 4 - shell completion.
FR31: Epic 6 - pip install Growth.
FR32: Epic 6 - REPL Vision.
FR33: Epic 4 - exit codes.
FR34: Epic 4 - structured stderr.
FR35: Epic 4 - atomic writes.
FR36: Epic 4 et Epic 2 - preflight avant ecriture/audit.
FR37: Epic 4 - overwrite refusal.
FR38: Epic 4 - strict mode.
FR39: Epic 4 - non-TTY batch behavior.
FR40: Epic 4 - debug stack traces only.

## Epic List

### Epic 1: Extraire des pistes WAV/MP3 verifiees depuis une ROM
L'utilisateur peut lancer `qlnes audio <rom> --format wav|mp3 --output tracks/` sur un premier couple mapper/engine supporte et obtenir des pistes par fichier, deterministes, bouclees et rattachees a un PCM canonique verifiable.
**FRs covered:** FR6, FR7, FR8, FR9, FR10, FR11.

### Epic 2: Savoir ce qui est vraiment couvert
L'utilisateur peut verifier une ROM ou auditer un corpus, puis lire une matrice de couverture fiable qui distingue `pass`, `fail`, `unsupported` et `unverified` par mapper et engine audio.
**FRs covered:** FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26, FR36, FR38.

### Epic 3: Produire un NSF2/NSFe exploitable par les lecteurs chiptune
L'utilisateur peut lancer `qlnes nsf <rom> --output ost.nsf` et obtenir un NSF valide avec metadata pistes, compatible avec les lecteurs cibles et coherent avec la detection de songs.
**FRs covered:** FR5, FR8, FR10.

### Epic 4: Rendre la CLI robuste pour scripts et pipelines
L'utilisateur pipeline peut invoquer `qlnes` en subprocess avec exit codes stables, stderr JSON, preflight, atomic writes, config layers, flags batch et completions sans inspecter les modules Python internes.
**FRs covered:** FR9, FR27, FR28, FR29, FR30, FR33, FR34, FR35, FR36, FR37, FR38, FR39, FR40.

### Epic 5: Garder l'analyse, le round-trip et les assets existants verts
L'utilisateur conserve les capacites existantes `analyze`, `recompile`, `verify` et assets pendant l'arrivee du pipeline musique, avec regression tests et contrats CLI inchanges.
**FRs covered:** FR1, FR2, FR3, FR4, FR13, FR14, FR17.

### Epic 6: Etendre vers la couverture universelle post-MVP
L'utilisateur voit la couverture progresser vers plus de mappers, engines, CHR round-trip, packaging et exploration interactive sans casser le MVP.
**FRs covered:** FR12, FR15, FR16, FR31, FR32.

## Epic 1: Extraire des pistes WAV/MP3 verifiees depuis une ROM

L'utilisateur peut lancer `qlnes audio <rom> --format wav|mp3 --output tracks/` sur un premier couple mapper/engine supporte et obtenir des pistes par fichier, deterministes, bouclees et rattachees a un PCM canonique verifiable.

### Story 1.1: Premier WAV verifie depuis une ROM mapper 0

As a ROM hacker,
I want `qlnes audio <rom> --format wav --output tracks/` to render a supported mapper-0 soundtrack,
So that I can obtain a usable lossless track without manual audio capture.

**Acceptance Criteria:**

**Given** a valid mapper-0 ROM in the local audio corpus with a recognized engine fixture
**When** I run `python -m qlnes audio rom.nes --format wav --output tracks/`
**Then** `qlnes` writes one WAV file per detected song using deterministic filenames
**And** each WAV is generated from the direct ROM/engine -> APU events -> PCM path
**And** the command exits `0` without requiring FCEUX unless verification is requested
**And** pulse 1, pulse 2, triangle and noise channels are represented in the PCM renderer
**And** DMC usage is either absent in the fixture or explicitly reported as unsupported/unverified before pass status is claimed.

### Story 1.2: Exhaustive song table enumeration

As a soundtrack extractor,
I want `qlnes` to walk every entry in a recognized song table,
So that unused and composer-demo tracks are not missed.

**Acceptance Criteria:**

**Given** a recognized engine fixture with referenced and unreferenced song table entries
**When** I run `qlnes audio` on the ROM
**Then** every valid song table entry is planned as a track
**And** invalid/sentinel entries are skipped only with recorded evidence
**And** output filenames use zero-padded song-table indexes
**And** the generated provenance records engine id, mapper, song index and detection evidence.

### Story 1.3: Loop-aware WAV output

As a porter,
I want loop boundaries preserved in WAV output,
So that I can drop tracks into a modern game audio engine without manual editing.

**Acceptance Criteria:**

**Given** a recognized engine track with bytecode-level loop metadata
**When** the track is rendered as WAV
**Then** the WAV contains PCM audio and loop metadata using the project's selected WAV loop representation
**And** the loop start/end values are derived from engine semantics, not PCM autocorrelation
**And** a test verifies the loop points for at least one fixture track
**And** if loop detection is unavailable, the track is emitted with explicit `unverified` loop provenance, not silent guesses.

### Story 1.4: MP3 output from canonical PCM

As a content creator,
I want MP3 files generated from the same canonical PCM as WAV,
So that I can use compact audio files while preserving a trustworthy source.

**Acceptance Criteria:**

**Given** `lameenc` is installed at the supported pinned version
**When** I run `python -m qlnes audio rom.nes --format mp3 --output tracks/`
**Then** `qlnes` renders PCM through the same path as WAV and encodes MP3 from that PCM
**And** output filenames match the WAV naming convention with `.mp3`
**And** provenance records encoder name/version, bitrate, sample rate and PCM hash
**And** tests compare PCM hash as canonical and treat MP3 byte hash as version-bound.

### Story 1.5: Unknown engine fallback tagged unverified

As a user with an unsupported ROM,
I want `qlnes` to avoid false pass claims,
So that I know whether the extracted audio is verified or only best-effort.

**Acceptance Criteria:**

**Given** a valid ROM whose audio engine is not recognized
**When** I run `qlnes audio`
**Then** `qlnes` either produces frame-accurate fallback artifacts tagged `unverified` or fails preflight if fallback is unavailable
**And** `bilan.json` never records unknown-engine audio as `pass`
**And** stderr explains the unsupported engine condition with mapper and ROM SHA-256
**And** no corrupted or partially verified output is presented as tier-1.

## Epic 2: Savoir ce qui est vraiment couvert

L'utilisateur peut verifier une ROM ou auditer un corpus, puis lire une matrice de couverture fiable qui distingue `pass`, `fail`, `unsupported` et `unverified` par mapper et engine audio.

### Story 2.1: Verification audio d'une ROM contre FCEUX

As a developer validating fidelity,
I want `qlnes verify --audio <rom>` to compare qlnes PCM against FCEUX reference PCM,
So that I can prove a supported ROM is audio-equivalent.

**Acceptance Criteria:**

**Given** FCEUX is installed and a supported ROM has local reference generation available
**When** I run `python -m qlnes verify --audio rom.nes`
**Then** `qlnes` obtains or reads the FCEUX reference PCM
**And** compares it to qlnes PCM at the configured sample rate
**And** exits `0` only when the PCM streams match
**And** exits `101` with structured JSON when equivalence fails.

### Story 2.2: Corpus manifest and reference generation

As a maintainer,
I want a hash-only corpus manifest and reference generator,
So that tests can validate real ROM behavior without committing ROMs or audio derivatives.

**Acceptance Criteria:**

**Given** a `corpus/manifest.toml` entry containing ROM SHA-256, mapper, engine and expected reference metadata
**When** I run the reference generation script locally
**Then** references are produced only for ROM files present locally
**And** missing ROMs are reported without failing unrelated entries
**And** generated reference provenance includes FCEUX version and Lua script hash
**And** no ROM bytes or reference WAV/MP3 files are added to tracked output paths.

### Story 2.3: `qlnes audit` writes `bilan.json`

As a project owner,
I want `qlnes audit` to run invariants across the corpus,
So that release readiness is based on actual coverage evidence.

**Acceptance Criteria:**

**Given** corpus ROMs and references are available locally
**When** I run `python -m qlnes audit`
**Then** every applicable invariant is run for supported mapper/engine/artifact combinations
**And** `bilan.json` records status, ROM count, fail count and failing SHA-256s
**And** missing references cause exit `102` before writing a new `bilan.json`
**And** the write is atomic.

### Story 2.4: `qlnes coverage` table and JSON

As a user checking support,
I want `qlnes coverage` to show a clear support matrix,
So that I know whether a ROM class is supported before relying on extraction.

**Acceptance Criteria:**

**Given** a valid `bilan.json`
**When** I run `python -m qlnes coverage`
**Then** the default output is a human-readable table
**And** audio rows are grouped by mapper and engine
**And** `--format json` emits schema-stable JSON
**And** missing or invalid `bilan.json` triggers an audit according to FR22.

### Story 2.5: Stale coverage and refresh

As a CI user,
I want stale coverage to be detected and refreshable,
So that old `bilan.json` results do not mask regressions.

**Acceptance Criteria:**

**Given** `bilan.json.generated_at` predates files in `qlnes/`
**When** I run `qlnes coverage`
**Then** `qlnes` warns that coverage may be stale
**And** suggests `--refresh`
**And** `qlnes coverage --refresh` bypasses the cache and runs audit
**And** `--strict` turns the stale warning into a fatal error.

## Epic 3: Produire un NSF2/NSFe exploitable par les lecteurs chiptune

L'utilisateur peut lancer `qlnes nsf <rom> --output ost.nsf` et obtenir un NSF valide avec metadata pistes, compatible avec les lecteurs cibles et coherent avec la detection de songs.

### Story 3.1: NSF2 header et payload mapper 0

As a chiptune user,
I want `qlnes nsf <rom> --output ost.nsf` to emit a basic NSF2 file,
So that I can play a supported ROM soundtrack in NSF players.

**Acceptance Criteria:**

**Given** a supported mapper-0 ROM with recognized init/play addresses
**When** I run `python -m qlnes nsf rom.nes --output ost.nsf`
**Then** `ost.nsf` has a valid NSF2 header
**And** load/init/play addresses and song count match the detected engine plan
**And** bankswitch fields are valid for the payload
**And** at least one target NSF decoder/player can load the file in tests.

### Story 3.2: NSFe metadata chunks

As a content creator,
I want NSF tracks to include labels, durations, fade and playlist metadata,
So that players show an organized soundtrack instead of anonymous tracks.

**Acceptance Criteria:**

**Given** song labels or generated track names are available
**When** `qlnes nsf` emits NSF2/NSFe metadata
**Then** `tlbl`, `time`, `fade`, `auth` and `plst` chunks are encoded according to the selected spec
**And** missing metadata falls back to deterministic defaults
**And** tests validate chunk order, lengths and little-endian fields
**And** unknown optional metadata never prevents playback.

### Story 3.3: NSF output shares song enumeration with audio output

As a user,
I want NSF and WAV/MP3 extraction to include the same tracks,
So that one command does not silently miss songs found by another.

**Acceptance Criteria:**

**Given** a recognized ROM with N detected songs
**When** I run both `qlnes audio --format wav` and `qlnes nsf`
**Then** both commands use the same `SongPlan` source
**And** the NSF song count equals the audio track count
**And** unreferenced but valid song table entries appear in both outputs
**And** a regression test asserts consistency.

### Story 3.4: NSF unsupported mapper/expansion failure

As a user with a complex ROM,
I want `qlnes nsf` to fail clearly when mapper or expansion audio is not covered,
So that I do not receive a broken NSF.

**Acceptance Criteria:**

**Given** a ROM with unsupported mapper or expansion audio
**When** I run `qlnes nsf`
**Then** preflight exits before writing `ost.nsf`
**And** stderr includes `qlnes: error:` and JSON details
**And** the error code distinguishes unsupported mapper from malformed input
**And** `--force` does not bypass unsupported capability checks.

## Epic 4: Rendre la CLI robuste pour scripts et pipelines

L'utilisateur pipeline peut invoquer `qlnes` en subprocess avec exit codes stables, stderr JSON, preflight, atomic writes, config layers, flags batch et completions sans inspecter les modules Python internes.

### Story 4.1: Erreurs structurees et exit codes

As a pipeline integrator,
I want all failures to have stable exit codes and parseable stderr JSON,
So that automation can handle errors without scraping prose.

**Acceptance Criteria:**

**Given** any command encounters a usage, ROM, unsupported, IO, equivalence or internal error
**When** the command exits non-zero
**Then** stderr begins with `qlnes: error:`
**And** the next line is single-line JSON containing `code` and `class`
**And** exit code matches the documented table
**And** stack traces are hidden unless `--debug` is passed.

### Story 4.2: Atomic output and overwrite protection

As a user rerunning extraction,
I want outputs protected from partial writes and accidental overwrite,
So that failed runs do not corrupt previous artifacts.

**Acceptance Criteria:**

**Given** an output target already exists
**When** I run a writer command without `--force`
**Then** `qlnes` exits `73` before writing
**And** with `--force`, writes occur through sibling temp files and atomic rename
**And** a kill/crash test leaves either the previous complete output or no output
**And** no half-written target remains.

### Story 4.3: Layered configuration for audio commands

As a CI maintainer,
I want defaults from config, env and CLI flags to resolve predictably,
So that local and CI runs behave the same way.

**Acceptance Criteria:**

**Given** built-in defaults, `qlnes.toml`, `QLNES_*` env vars and CLI flags define the same option
**When** `qlnes audio`, `verify`, `audit` or `coverage` resolves config
**Then** precedence is defaults < TOML < env < CLI
**And** every TOML/env option has a corresponding CLI flag
**And** command-specific sections override `[default]` only for that command
**And** invalid config fails preflight with structured error.

### Story 4.4: Batch-mode flags and non-TTY behavior

As a script author,
I want explicit quiet, strict, progress, hints and color controls,
So that `qlnes` behaves predictably in logs and pipes.

**Acceptance Criteria:**

**Given** stdout or stderr is non-TTY
**When** I run a long command
**Then** no progress bars or prompts are emitted
**And** `--strict` makes warnings fatal
**And** `--no-hints` suppresses hint lines but not JSON
**And** `--color never` disables ANSI color
**And** `--quiet` suppresses informational output while preserving errors.

### Story 4.5: Shell completion and help contract

As a CLI user,
I want completion and help to reflect the MVP command surface,
So that I can discover flags without external docs.

**Acceptance Criteria:**

**Given** Typer completion is available
**When** I run `--install-completion` for bash, zsh, fish or PowerShell
**Then** completion installation follows Typer's mechanism
**And** help lists audio, nsf, audit and coverage flags with valid enum values
**And** noun command exceptions `audio` and `nsf` remain documented as backwards-compatible
**And** help text does not advertise Growth/Vision features as MVP.

## Epic 5: Garder l'analyse, le round-trip et les assets existants verts

L'utilisateur conserve les capacites existantes `analyze`, `recompile`, `verify` et assets pendant l'arrivee du pipeline musique, avec regression tests et contrats CLI inchanges.

### Story 5.1: Regression tests pour ingestion et analyse ROM

As an existing user,
I want `analyze` and ROM header validation to keep working,
So that music work does not break current analysis workflows.

**Acceptance Criteria:**

**Given** existing fixture ROMs
**When** the test suite runs
**Then** header validation, `STACK.md` generation and annotated ASM generation pass
**And** existing output structure remains compatible
**And** unsupported dynamic discovery still degrades clearly when `cynes` is absent.

### Story 5.2: Regression tests pour recompile et verify

As a ROM hacker,
I want byte-identical round-trip verification to remain green,
So that audio extraction does not weaken the original equivalence promise.

**Acceptance Criteria:**

**Given** existing round-trip fixtures
**When** I run `qlnes recompile` and `qlnes verify`
**Then** recompiled ROM bytes match the source
**And** failures use the new structured error contract
**And** tests cover both success and mismatch cases
**And** audio verification does not change the default non-audio verify behavior.

### Story 5.3: Regression tests pour assets PNG

As a user extracting sprites,
I want CHR-ROM PNG extraction to keep working,
So that the music MVP does not regress asset workflows.

**Acceptance Criteria:**

**Given** ROMs with CHR-ROM banks
**When** I run `qlnes analyze --assets`
**Then** PNG sheets are emitted as before
**And** outputs are protected by the same atomic/overwrite contract where applicable
**And** deterministic-output tests reject timestamps or host-specific metadata
**And** asset failures do not mask unrelated audio tests.

## Epic 6: Etendre vers la couverture universelle post-MVP

L'utilisateur voit la couverture progresser vers plus de mappers, engines, CHR round-trip, packaging et exploration interactive sans casser le MVP.

### Story 6.1: Ajouter un nouveau mapper/engine audio a la matrice

As a maintainer,
I want a repeatable contributor flow for adding one mapper/engine pair,
So that coverage can grow without redesigning the pipeline.

**Acceptance Criteria:**

**Given** a new legal local corpus ROM and engine research notes
**When** a contributor adds a handler and manifest entry
**Then** the new pair appears in `bilan.json`
**And** tier-1 requires PCM equivalence against FCEUX
**And** unsupported expansion audio remains explicit
**And** docs explain the required evidence.

### Story 6.2: CHR PNG round-trip growth story

As an asset modder,
I want PNG sheets to round-trip back to byte-identical CHR-ROM,
So that visual assets become as verifiable as code and audio.

**Acceptance Criteria:**

**Given** extracted PNG sheets from a CHR-ROM fixture
**When** I run the future PNG -> CHR round-trip command
**Then** produced CHR bytes match the original bank
**And** failures record source bank and pixel/tile mismatch evidence
**And** coverage records the asset invariant separately from audio.

### Story 6.3: Packaging growth story

As a new user,
I want to install `qlnes` with `pip install qlnes`,
So that I can invoke `qlnes <command>` without cloning the repo.

**Acceptance Criteria:**

**Given** packaging is promoted to Growth
**When** the package is built
**Then** console script `qlnes` invokes the same CLI as `python -m qlnes`
**And** package data includes Lua scripts and manifests but no ROM/audio bytes
**And** dependency pins preserve MVP behavior
**And** install docs state FCEUX requirements for verify/audit.

### Story 6.4: Interactive ROM shell vision story

As a researcher,
I want `qlnes shell <rom>` to inspect routines and audition tracks interactively,
So that exploratory reverse-engineering is faster than repeated CLI calls.

**Acceptance Criteria:**

**Given** the Vision shell is enabled
**When** I open a ROM
**Then** I can list detected routines, songs and coverage status
**And** audition commands reuse the same audio renderer and provenance model
**And** no shell-only behavior bypasses batch CLI invariants
**And** the feature remains out of MVP docs until explicitly promoted.

## Final Validation

- FR coverage: complete. FR1-FR40 are mapped to epics.
- UX-DR coverage: complete. UX-DR1-UX-DR12 are covered by Epic 1, Epic 2, Epic 3 and Epic 4 stories.
- Architecture alignment: complete. No greenfield starter is required; stories extend the brownfield CLI.
- Story count: 26 stories across 6 epics.
- Dependency flow: Epic 1 creates the first vertical audio value; Epic 2 and Epic 3 build on the audio planning/provenance seams; Epic 4 hardens the public CLI contract; Epic 5 protects existing value; Epic 6 is explicitly post-MVP.
- Forward dependency check: no story requires a later story in the same epic to be useful.
- File churn check: overlap on CLI/audio/audit modules is intentional and grouped by user-visible workflow, with Epic 4 reserved for public contract hardening.
