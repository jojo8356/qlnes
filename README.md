# qlnes

Pipeline complet d'analyse, d'annotation, de modding et de vérification
round-trip de ROM NES en Python.

À partir d'un fichier `.nes`, qlnes produit :

- un **`STACK.md`** synthétique (mapper, vecteurs CPU, registres hardware
  utilisés, sous-routines nommées, profil détecté, éditeur probable, …)
- un **désassemblage 6502 annoté** : `JSR ppu_load` au lieu de `JSR L_C0ED`,
  `STA PPUCTRL` au lieu de `STA L_2000`, `INC frame_counter` au lieu de
  `INC 0xD2`, et les chaînes ASCII directement converties en `.byte "..."`
- un dossier **`assets/`** : CHR-ROM en `.chr` binaire + `.asm` réassemblable
  + `.png` (background + sprites séparés)
- une **vérification round-trip** : la ROM peut être recompilée
  byte-pour-byte identique à l'originale (sha256 vérifié)

## Démo en 1 commande

```bash
$ python -m qlnes analyze tests/fixtures/nestest.nes --asm out.asm --assets auto

→ lecture de tests/fixtures/nestest.nes
→ ROM : mapper=0  PRG=1 bank(s)
→ analyse statique (QL6502 + heuristiques)…
→ discovery dynamique (cynes)…
→ extraction des assets dans tests/fixtures/assets/nestest…
  - CHR brute : `chr_rom.chr` (binaire 8KB / banque)
  - CHR en ASM (réassemblable) : `chr_rom.asm`
  - Aperçu image complète : `chr_tiles.png` (512 tiles)
  - Pattern table BG : `pattern_table_bg.png`
  - Pattern table sprites : `pattern_table_spr.png`
✓ STACK.md écrit : tests/fixtures/STACK.md
✓ ASM annoté écrit : out.asm

$ python -m qlnes verify tests/fixtures/nestest.nes
✓ identique (24592 octets, sha256 f67d55fd6b3c…)
```

## Installation

Le projet a deux composantes : un binaire C (`QL6502`) compilé localement, et
un package Python.

```bash
# Compiler QL6502 (vendor/QL6502-src/, MIT, forthchina)
mkdir -p bin && gcc -O2 -o bin/ql6502 vendor/QL6502-src/*.c

# Créer le venv et installer les deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Vérifier
.venv/bin/python -m unittest discover -s tests
```

Dépendances Python : `typer`, `py65`, `cynes` (émulateur NES headless pour la
discovery dynamique), `Pillow` (export PNG des tiles).

## Sous-commandes CLI

```bash
# Analyse complète : STACK.md + ASM annoté + assets
python -m qlnes analyze ROM.nes --asm out.asm --assets auto

# Recompiler la ROM depuis l'ASM annoté (round-trip)
python -m qlnes recompile ROM.nes -o /tmp/rec.nes

# Comparer deux ROMs (ou round-trip auto si seule l'originale est donnée)
python -m qlnes verify ROM.nes
python -m qlnes verify ORIG.nes RECOMPILED.nes
```

## API Python

```python
from qlnes import RomProfile, Rom

rom = Rom.from_file("game.nes")
profile = RomProfile.from_rom(rom).analyze_static()

# Tout est dans le rapport
print(profile.static_report.hardware)     # {0x2000: "PPUCTRL", ...}
print(profile.static_report.dataflow)     # {0xD2: "frame_counter", ...}
print(profile.static_report.subroutines)  # {0xC0ED: "ppu_load", ...}
print(profile.engine_hints)               # [Konami, ...]
print(profile.language_hypotheses)        # [ASM hand-written, ...]

# Sortie markdown + ASM annoté + assets
profile.write_markdown("STACK.md")
profile.extract_assets("assets/game/")

# Round-trip
diff = profile.verify_round_trip()
print(diff.summary())  # "identique (32784 octets, sha256 abc...)"
```

## Pipeline de détection

| Couche | Détecte | Source |
|---|---|---|
| iNES header | mapper, mirroring, battery, PRG/CHR sizes | qlnes/ines.py |
| Hardware lookup | PPUCTRL, JOY1, APU registers… | qlnes/nes_hw.py |
| OAM convention | sprite_N_y/tile/attr/x à $0200-$02FF | qlnes/annotate.py |
| Dataflow heuristiques | frame_counter, controllers, pointer pairs, OAM index, OAMDMA, PPU shadows, loop counters, JSR args | qlnes/dataflow.py |
| Subroutine kinds | read_controllers, oam_dma_transfer, ppu_load, play_pulse, … | qlnes/dataflow.py |
| Cross-ref dynamique → statique | dynamic name → routines qui y écrivent | qlnes/cross_ref.py |
| Détection éditeur | mapper hints + scan ASCII (KONAMI, CAPCOM, SUNSOFT…) | qlnes/engines.py |
| Détection toolchain | cc65 vs ASM hand-written vs homebrew | qlnes/lang_detect.py |
| Discovery dynamique | runs cynes + diff comportemental, multi-duration, composed, transitions | qlnes/emu/discover.py |
| Recompilation + verify | py65 backend + sha256 fast-path | qlnes/recompile.py |

## Architecture

```
qlnes/
├── annotate.py     pipeline annotation principale
├── asm_text.py     conversion DB → .byte "string"
├── assets.py       extraction CHR (.chr/.asm/.png)
├── cli.py          Typer subcommands (analyze/recompile/verify)
├── cross_ref.py    propage noms dynamiques aux routines
├── dataflow.py     5+ détecteurs statiques + classifier subroutines
├── engines.py      30+ mapper publishers + scan strings
├── ines.py         parse iNES + mappers 0/1/2/3
├── lang_detect.py  classifier toolchain
├── nes_hw.py       table NES hardware registers
├── parser.py       Disasm + Line typés
├── profile.py      RomProfile (orchestre tout) + write_markdown
├── ql6502.py       wrapper subprocess QL6502
├── recompile.py    py65 + RomDiff + sha256
├── rom.py          Rom + Bank
└── emu/
    ├── runner.py   wrapper cynes (Runner, Scenario, Snapshot)
    └── discover.py classify_durations, InteractionResult, Transition
```

## Tests

215 tests, ~12s sur un laptop. Couvre :

- chaque détecteur statique isolé
- mappers 0/1/2/3 avec ROMs synthétiques
- discovery dynamique sur un ROM jouable (synth réactif aux boutons)
- round-trip byte-pour-byte sur **nestest.nes** (test ROM publique)

```bash
.venv/bin/python -m unittest discover -s tests
```

## Limites connues

- **Mappers supportés** : 0 (NROM), 1 (MMC1 mode 3), 2 (UxROM), 3 (CNROM)
- **Discovery dynamique** : nécessite `cynes`, supporté seulement pour mapper 0 (limitation runner actuelle)
- **Détection éditeur** : pas de signature pour les moteurs sonores propriétaires sans string identifiable
- **PPU stub** : pas implémenté nous-mêmes, on délègue à cynes (qui fait le full-NES)

## Crédits

Ce projet est librement réutilisable sous MIT. Composants tiers :

| Composant | Auteur | License | Rôle |
|---|---|---|---|
| QL6502 (vendored) | forthchina | MIT | Désassembleur statique 6502 (analyse code/data) |
| py65 | Mike Naberezny | BSD-3 | Réassembleur 6502 |
| cynes | Youlixx | MIT | Émulateur NES headless |
| typer | Sebastián Ramírez | MIT | CLI |
| Pillow | Alex Clark + contributors | HPND | PNG des tiles |
| nestest.nes | Kevin Horton | public domain | Test ROM |

## Sources et inspirations

- [NESdev wiki](https://www.nesdev.org/wiki/Nesdev_Wiki) — référence absolue pour tout le hardware NES
- [GenNm (NDSS 2025)](https://arxiv.org/abs/2306.02546) — recovery de noms de variables sur binaires strippés (x86, mais idée transposée pour 6502)
- [christopherpow/nes-test-roms](https://github.com/christopherpow/nes-test-roms) — corpus de test ROMs
- [retroenv/retrodisasm](https://github.com/retroenv/retrodisasm) — tracing disassembler 6502
