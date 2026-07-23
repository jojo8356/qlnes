---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - _bmad-output/project-context.md
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Conversion automatique ROM NES vers port natif Linux / executable PC universel'
research_goals: 'Comprendre comment creer une grosse feature qlnes qui transforme une ROM NES en executable Linux natif, sans dependance utilisateur, et evaluer la faisabilite d une approche automatique et universelle.'
user_name: 'Johan'
date: '2026-07-23'
web_research_enabled: true
source_verification: true
---

# Conversion ROM NES vers Port Natif Linux: Recherche Technique Complete

**Date:** 2026-07-23  
**Auteur:** Johan / qlnes  
**Type:** Recherche technique BMAD  

## Executive Summary

Transformer une ROM NES en executable Linux "normal" est possible, mais pas sous la forme naive "ROM -> binaire x86_64 pur". Une ROM NES contient du code 6502 et des donnees qui supposent l'existence d'une machine NES complete: CPU 6502 modifie, PPU, APU, OAM DMA, controleurs, RAM/VRAM, timing NMI/IRQ et mapper cartouche. Sans reproduire ces composants, le code traduit ne peut pas tourner correctement.

La voie technique viable pour qlnes est donc une **static recompilation hybride**: traduire le PRG 6502 en C/Rust/LLVM natif, puis le lier a un **runtime NES specialise** qui implemente PPU/APU/mappers/entrees. Ce n'est pas un emulateur generaliste expose a l'utilisateur, mais c'est encore une simulation du hardware NES. Pour une ROM arbitraire, une partie hardware reste inevitable. Pour un jeu connu comme SMB, on peut aller plus loin vers un vrai port moteur natif en remplacant progressivement des routines ASM par des equivalents SDL/Rust/C.

**Conclusion principale:**  
- **Universel automatique:** faisable uniquement avec recompilation CPU + runtime hardware NES specialise.
- **Vrai port natif sans simulation hardware:** faisable seulement par moteur/jeu, avec reverse engineering avance.
- **MVP qlnes realiste:** generer un projet Linux natif qui compile le code 6502 en C, embarque assets extraits, lie un runtime SDL2 minimal, supporte d'abord NROM/mapper 0, puis etend les mappers.

## Table des Matieres

1. Position technique et vocabulaire
2. Recherche web et sources verifiees
3. Architecture NES a reproduire
4. Modeles possibles de conversion
5. Architecture cible pour qlnes
6. Pipeline de recompilation statique
7. Runtime natif Linux
8. Universalite, limites et detection moteur
9. Packaging executable Linux/AppImage
10. Roadmap epics/stories
11. Risques techniques et juridiques
12. Recommandation finale

## 1. Position Technique et Vocabulaire

### Ce que "natif" peut vouloir dire

Il faut distinguer trois niveaux:

1. **Wrapper executable**  
   Une app Linux embarque une ROM et un emulateur. C'est simple, robuste, universel, mais ce n'est pas ce que tu demandes.

2. **Recompilation statique hybride**  
   Le code 6502 de la ROM est traduit en C/Rust/LLVM puis compile en x86_64/ARM64 natif. Le binaire contient un runtime qui simule PPU/APU/mappers. Le gameplay CPU tourne comme code natif, mais le hardware NES reste reproduit. C'est le meilleur compromis "automatique et universel".

3. **Port natif moteur**  
   On remplace les systemes NES par des systemes PC: renderer SDL/OpenGL, audio mixer PC, logique jeu reconstruite. C'est vraiment natif, mais non universel: il faut reconnaitre le moteur du jeu ou reconstruire le jeu.

### Decision de vocabulaire pour qlnes

Je recommande de nommer la feature:

**`recomp` / `native-port`**

Et de documenter deux modes:

- `--mode=recomp`: recompilation 6502 + runtime NES specialise.
- `--mode=port`: port moteur natif, seulement pour moteurs supportes comme SMB.

## 2. Recherche Web et Sources Verifiees

### Sources clefs

- NESdev, PPU memory map: la PPU utilise CHR-ROM/CHR-RAM, nametables, attribute tables, palette RAM et OAM; les sprites sont 64 entrees OAM de 4 octets.  
  Source: https://www.nesdev.org/wiki/PPU_memory_map

- NESdev, PPU programmer reference: OAMDMA `$4014` copie 256 octets et suspend le CPU; la PPU fetch les nametables/attributes/patterns par scanline.  
  Source: https://www.nesdev.org/wiki/PPU_programmer_reference

- NESdev, Catch-up: CPU, PPU, APU et mapper tournent en parallele; les emulateurs doivent synchroniser finement les composants, sinon les raster effects et IRQ sont faux.  
  Source: https://www.nesdev.org/wiki/Catch-up

- Andrew Kelley / Jamulator: preuve historique que des ROMs NES peuvent etre recompiles statiquement via LLVM/Go vers executables natifs, avec runtime SDL/OpenGL.  
  Source: https://andrewkelley.me/post/jamulator.html

- N64Recomp: architecture moderne de recompilation statique: input binaire + symboles/metadonnees -> C -> compilation native + runtime.  
  Source: https://github.com/N64Recomp/N64Recomp

- Zelda64Recomp: exemple produit moderne: le binaire ne contient pas les assets commerciaux, demande une ROM utilisateur, et n'est pas un emulateur arbitraire.  
  Source: https://github.com/Zelda64Recomp/Zelda64Recomp

- NESdev, Releasing on modern platforms: les sorties modernes de jeux NES utilisent souvent un middleware emulateur verrouille; attention aux licences, surtout GPL.  
  Source: https://www.nesdev.org/wiki/Releasing_on_modern_platforms

- LLVM LangRef: LLVM IR est une representation SSA typée servant de cible d'optimisation et de compilation.  
  Source: https://www.llvm.org/docs/LangRef.html

- SDL: bibliotheque cross-platform donnant acces audio, clavier, manette, graphique; licence zlib permissive.  
  Source: https://www.libsdl.org/

- PyInstaller: produit un executable/folder self-contained a partir d'un script Python et de ses dependances.  
  Source: https://pyinstaller.org/en/stable/usage.html

- AppImage docs: un AppImage est un fichier executable contenant une app et ses dependances dans une image SquashFS avec runtime ELF et `AppRun`.  
  Sources: https://docs.appimage.org/packaging-guide/manual.html et https://appimage.github.io/appimagetool/

### Niveau de confiance

**Confiance haute** sur l'impossibilite d'un binaire Linux pur sans runtime hardware: les sources NESdev documentent que les jeux NES dependent directement de composants materiels et de timings paralleles.

**Confiance haute** sur la faisabilite d'une recompilation statique hybride: Jamulator et N64Recomp prouvent le pattern.

**Confiance moyenne** sur l'universalite NES complete: techniquement possible en couvrant tous les mappers/timings, mais le cout devient proche d'un emulateur cycle-accurate + recompiler.

## 3. Architecture NES a Reproduire

### CPU 6502

La ROM contient du code 6502 qui manipule:

- registres A/X/Y/SP/P/PC;
- flags carry/zero/interrupt/decimal/break/overflow/negative;
- pile `$0100-$01FF`;
- RAM interne `$0000-$07FF` miroir;
- vecteurs NMI/RESET/IRQ a la fin du PRG.

Pour recompiler, qlnes doit construire un CFG depuis:

- RESET vector;
- NMI vector;
- IRQ/BRK vector;
- tables de jump indirect;
- JSR/JMP/branches;
- traces dynamiques optionnelles pour separer code/donnees.

### PPU

La PPU n'est pas un detail graphique. Les jeux ecrivent dans ses registres pour controler:

- CHR-ROM/CHR-RAM `$0000-$1FFF`;
- nametables `$2000-$2FFF`;
- palette `$3F00-$3F1F`;
- OAM sprites 64 x 4 octets;
- scrolling via `$2005/$2006`;
- NMI via `$2000`;
- DMA OAM via `$4014`.

Une conversion native universelle doit reproduire ces effets, sinon les niveaux, sprites, scrolls, palettes et split screens cassent.

### APU

L'audio depend de registres `$4000-$4017`:

- pulse 1/2;
- triangle;
- noise;
- DMC;
- frame counter;
- longueur/envelope/sweep.

qlnes a deja un APU in-process pour WAV/MP3. Ce code peut devenir le noyau audio du runtime natif.

### Mappers

Les mappers changent le mapping PRG/CHR, les mirroring nametable, parfois les IRQ. Un binaire universel doit inclure un runtime mapper:

- NROM pour MVP;
- MMC1/MMC3 ensuite;
- CNROM/UxROM/AxROM faciles;
- VRC/Namco/Sunsoft plus complexes;
- IRQ scanline indispensables pour certains jeux.

## 4. Modeles Possibles de Conversion

### Mode A: Wrapper avec emulateur embarque

**Principe:** executable Linux lance un core NES interne avec la ROM.

**Avantages:**
- universel;
- rapide a livrer;
- compatibilite haute;
- packaging simple.

**Inconvenient:**
- ne satisfait pas "sans emulateur".

**Usage qlnes:** garder comme `bundle-rom`, mais ne pas le vendre comme port natif.

### Mode B: Static recompilation CPU + runtime NES

**Principe:** chaque instruction 6502 est traduite en C/Rust/LLVM. Les acces memoire deviennent des appels runtime:

```c
ctx->a = mem_read(ctx, addr);
mem_write(ctx, 0x2000, ctx->a);
branch_if_zero(ctx, target);
```

Puis:

```bash
clang generated_prg.c runtime/*.c -lSDL3 -o GameNative
```

**Avantages:**
- le code jeu devient natif;
- executable Linux normal;
- possible automatiquement;
- compatible avec qlnes actuel;
- facilite debug/profiling/instrumentation.

**Inconvenients:**
- le runtime reste une simulation NES;
- la precision timing est difficile;
- code/data separation non triviale;
- mappers et self-modifying tricks demandent fallback.

**C'est le MVP recommande.**

### Mode C: Dynamic recompilation

**Principe:** traduire les blocs 6502 au runtime.

**Avantages:**
- gere mieux code dynamique et indirect jumps;
- plus universel.

**Inconvenients:**
- complexite runtime elevee;
- moins "port natif" produit;
- ressemble fortement a un emulateur JIT.

**Usage qlnes:** pas en MVP. Peut servir de fallback pour blocs inconnus.

### Mode D: Port moteur natif

**Principe:** reconnaitre le moteur du jeu, extraire assets/maps/sounds, remplacer le moteur NES par un moteur PC.

Pour SMB:

- niveaux depuis tables SMB;
- metatiles et palettes deja extraits par qlnes;
- audio SMB NSF/SFX deja partiellement compris;
- personnages/blocs/logo deja exportes;
- logique moteur a reconstruire.

**Avantages:**
- vrai port natif;
- rendu moderne;
- pas de simulation PPU/APU necessaire a terme.

**Inconvenients:**
- non universel;
- demande un plugin par moteur/jeu;
- risque legal plus sensible si assets inclus.

## 5. Architecture Cible pour qlnes

### Vue d'ensemble

```text
ROM .nes
  |
  v
Header iNES + mapper profile
  |
  +--> PRG disasm + CFG + code/data classifier
  |
  +--> CHR/palettes/nametables/assets extraction
  |
  +--> Engine recognizer optionnel (SMB/FamiTone/etc.)
  |
  v
Recompiler backend
  |
  +--> C/Rust/LLVM generated code
  +--> runtime manifest
  +--> symbol map / debug report
  |
  v
Native runtime Linux
  |
  +--> CPU context
  +--> memory bus + mapper
  +--> PPU renderer SDL
  +--> APU audio SDL
  +--> input
  |
  v
Executable ELF / AppImage
```

### Commandes proposees

```bash
python -m qlnes recomp ROM.nes -o out/native --target linux-x86_64
python -m qlnes recomp ROM.nes -o out/native --backend c --mapper nrom
python -m qlnes native-port ROM.nes -o out/smb-native --engine smb
python -m qlnes native-build out/native --appimage
```

### Artefacts generes

```text
out/native/
  qlnes-recomp.toml
  src/
    main.c
    prg_generated.c
    prg_generated.h
    runtime_bus.c
    runtime_ppu.c
    runtime_apu.c
    mapper_nrom.c
  assets/
    chr.bin
    palettes.bin
  debug/
    cfg.dot
    symbols.json
    code-data-map.json
    unsupported-sites.md
  build.sh
  build-appimage.sh
```

## 6. Pipeline de Recompilation Statique

### Phase 1: Analyse ROM

qlnes sait deja lire iNES, mappers, PRG/CHR et produire ASM. Pour la recompilation, il faut ajouter:

- validation mapper supporte;
- extraction PRG banks;
- calcul des plages CPU visibles;
- table de vectors;
- scan des JSR/JMP/branches;
- detection des jump tables;
- detection code vs data.

### Phase 2: CFG et code/data

Le probleme dur est de savoir ce qui est instruction et ce qui est data. Strategie:

1. tracing statique depuis RESET/NMI/IRQ;
2. heuristiques pour jump tables;
3. references dynamiques optionnelles via runner;
4. annotations ASM existantes qlnes;
5. fallback interpreter pour adresses non classees.

### Phase 3: Translation 6502

Deux backends realistes:

#### Backend C

Plus simple pour MVP:

```c
void fn_8000(Cpu *cpu, Bus *bus) {
  cpu->p |= FLAG_I;              // SEI
  cpu->p &= ~FLAG_D;             // CLD
  cpu->a = 0x10;                 // LDA #$10
  bus_write(bus, 0x2000, cpu->a);// STA PPUCTRL
}
```

Avantages:
- facile a debug;
- clang/gcc universels;
- pas de dependance LLVM Python;
- compatible AppImage.

#### Backend LLVM IR

Plus puissant ensuite:

- SSA;
- optimisations;
- object files directs;
- potentiel JIT/fallback.

Inconvenient: complexite et compatibilite LLVM.

### Phase 4: Acces memoire

Ne jamais compiler les reads/writes comme acces tableau brut sans controle, parce que `$2000`, `$4014`, `$8000` ne sont pas de simples RAM.

Pattern:

```c
uint8_t bus_read(Bus *bus, uint16_t addr);
void bus_write(Bus *bus, uint16_t addr, uint8_t value);
```

Optimisation possible:

- RAM zero-page direct;
- RAM stack direct;
- PRG-ROM direct;
- registres hardware via switch;
- mappers via hooks.

### Phase 5: Timing

Chaque instruction 6502 a un cout cycle. Le runtime doit accumuler:

```c
cpu->cycles += cycles_for_instruction;
runtime_catchup(runtime, cpu->cycles);
```

`runtime_catchup` avance:

- PPU jusqu'au cycle cible;
- APU jusqu'au cycle cible;
- mapper IRQ;
- NMI quand vblank arrive.

La source NESdev "Catch-up" confirme que CPU/PPU/APU/mapper doivent etre synchronises finement pour eviter les erreurs de raster/IRQ.

## 7. Runtime Natif Linux

### Backend graphique

SDL est le choix naturel:

- Linux/Windows/macOS;
- input clavier/manette;
- audio;
- fenetre;
- licence zlib permissive.

Pour Linux MVP:

- SDL3 ou SDL2;
- framebuffer 256x240 en texture;
- scaling integer;
- vsync optionnel;
- input mapping NES.

### PPU runtime

Deux niveaux:

1. **Frame renderer simple**  
   Suffisant pour NROM/SMB si pas de raster tricks avances.

2. **Cycle/scanline renderer**  
   Necessaire pour MMC3 IRQ, split scroll, sprite 0 hit strict.

MVP:

- background nametable;
- attributes;
- sprites 8x8/8x16;
- palette;
- mirroring horizontal/vertical;
- OAMDMA.

### APU runtime

Reutiliser `qlnes/apu` comme reference comportementale, puis porter en C/Rust:

- pulse/triangle/noise/DMC;
- mixer;
- resampler;
- SDL audio callback.

MVP possible sans audio parfait:

- d'abord silence ou APU minimal;
- ensuite pulse/triangle/noise;
- DMC plus tard.

### Input

Mapper:

- clavier -> bits NES A/B/Select/Start/Up/Down/Left/Right;
- gamepad SDL -> memes bits;
- registre `$4016` strobe/shift deja modele dans qlnes.

## 8. Universalite, Limites et Detection Moteur

### Pourquoi "universel sans runtime" est impossible

Une ROM NES n'appelle pas une API abstraite "draw_sprite". Elle ecrit directement dans des registres hardware. Exemple:

- `$2000`: PPUCTRL;
- `$2005`: scroll;
- `$2006/$2007`: VRAM address/data;
- `$4014`: DMA OAM;
- `$8000+`: mapper bank switching selon cartouche.

Un executable Linux n'a pas ces registres. Il faut donc soit:

- les simuler;
- soit comprendre semantiquement chaque routine et la remplacer.

La premiere option est universelle; la seconde est native mais par moteur.

### Strategie qlnes hybride

Classer les ROMs:

| Classe | Exemple | Strategie |
|---|---|---|
| NROM simple | SMB, petits jeux mapper 0 | recompilation + runtime PPU/APU simple |
| Mapper simple | CNROM/UxROM/AxROM | recompilation + runtime mapper |
| Mapper IRQ | MMC3, VRC | runtime scanline/cycle plus strict |
| Moteur reconnu | SMB | port moteur optionnel |
| Code dynamique opaque | jump indirect massif | fallback interpreter/JIT |

### Role de l'ASM

qlnes doit enrichir le desassemblage:

- labels fonctions;
- constantes hardware;
- variables RAM;
- tables de donnees;
- jump tables;
- call graph;
- bank ownership;
- NMI/IRQ handlers;
- PPU/APU/mappers writes.

C'est exactement dans la continuite des features deja ajoutees: notation const/var, graphics-calls, SMB graphics/audio notes.

## 9. Packaging Executable Linux/AppImage

### Executable ELF direct

Build minimal:

```bash
cc -O2 src/*.c -lSDL3 -lm -o MyGame
```

Ou Rust:

```bash
cargo build --release
```

### AppImage

AppImage demande un AppDir:

```text
AppDir/
  AppRun
  mygame.desktop
  mygame.svg
  usr/bin/mygame
  usr/lib/*.so
```

Puis `appimagetool AppDir MyGame.AppImage`.

La documentation AppImage confirme que l'AppImage est un fichier executable contenant l'application et ses dependances raisonnablement non garanties sur le systeme cible.

### Important pour qlnes

Pour une vraie feature `native-port`, ne pas utiliser PyInstaller. PyInstaller est utile pour wrapper Python, mais la cible "native" doit produire:

- C/Rust compile;
- ELF direct;
- AppImage depuis ELF;
- pas de Python au runtime.

`uv` reste utile comme bootstrap d'outils de generation, mais pas dans l'app finale.

## 10. Roadmap Epics / Stories

### Epic 1: Recompilation 6502 minimale NROM

**Goal:** prendre une ROM NROM et generer du C compilable.

Stories:

- R1. Parser PRG banks et vectors RESET/NMI/IRQ.
- R2. Construire CFG statique depuis vectors.
- R3. Identifier code vs data avec rapport d'incertitude.
- R4. Emettre C pour instructions 6502 officielles.
- R5. Ajouter CPU context et flags exacts.
- R6. Compiler en ELF Linux via `cc`.
- R7. Ajouter tests golden sur ROMs synthetiques.

Acceptance:

- une ROM synthetique "hello PPU" compile et tourne;
- hash de RAM final identique au runner qlnes pour scenario court.

### Epic 2: Runtime bus + PPU minimal

Stories:

- P1. Implementer bus CPU `$0000-$FFFF`.
- P2. Implementer RAM miroir.
- P3. Implementer PPU registers `$2000-$2007`.
- P4. Implementer OAMDMA `$4014`.
- P5. Renderer SDL framebuffer 256x240.
- P6. Mirroring horizontal/vertical.
- P7. Tests visuels sur nametable/palette/sprites.

Acceptance:

- SMB title screen affiche un rendu coherent;
- sprites OAM visibles avec palettes correctes.

### Epic 3: Runtime APU

Stories:

- A1. Porter pulse channels.
- A2. Porter triangle.
- A3. Porter noise.
- A4. Porter DMC minimal.
- A5. Mixer/resampler SDL.
- A6. Comparer PCM avec qlnes Python APU.

Acceptance:

- 10 secondes audio synthetic ROM ont RMS/frequence attendue;
- SMB theme joue sans crash.

### Epic 4: Timing NMI/IRQ

Stories:

- T1. Cycle accounting par instruction.
- T2. `runtime_catchup`.
- T3. NMI vblank.
- T4. Sprite 0 hit minimal.
- T5. Mapper IRQ interface.
- T6. Tests contre traces in-process qlnes.

Acceptance:

- NMI appele au bon rythme;
- jeux NROM dependent du vblank sans divergence majeure.

### Epic 5: Mappers

Stories:

- M1. NROM.
- M2. CNROM.
- M3. UxROM.
- M4. AxROM.
- M5. MMC1.
- M6. MMC3 + IRQ scanline.
- M7. Manifest mapper capabilities.

Acceptance:

- chaque mapper a ROM synthetic et tests bank switching.

### Epic 6: SMB Native Port Mode

Stories:

- S1. Reutiliser extraction niveaux/metatiles existante.
- S2. Renderer SDL direct des niveaux SMB.
- S3. Input et scrolling SMB.
- S4. Physique Mario minimale.
- S5. Collisions blocs/sol/tuyaux.
- S6. Ennemis Goomba/Koopa MVP.
- S7. Audio SMB via NSF/SFX ou runtime APU.

Acceptance:

- 1-1 jouable de bout en bout en port moteur.

### Epic 7: Packaging Linux

Stories:

- B1. Generer `build.sh`.
- B2. Generer `AppDir`.
- B3. Telecharger/appeler `appimagetool`.
- B4. Inclure SDL/libs.
- B5. Generer desktop/icon.
- B6. Verifier execution AppImage.

Acceptance:

- `python -m qlnes recomp ROM.nes -o out/game && out/game/build-appimage.sh` produit un `.AppImage`.

## 11. Risques Techniques et Juridiques

### Risques techniques

- Code/data separation impossible a 100% statiquement.
- Jump indirect et self-modifying patterns.
- Timing PPU/mapper insuffisant.
- DMC et APU edge cases.
- Mappers nombreux.
- Tests visuels difficiles a automatiser.
- Performance du C genere si tout passe par `bus_read/write`.

Mitigation:

- fallback interpreter pour blocs inconnus;
- traces dynamiques;
- commencer NROM;
- comparer contre qlnes runner;
- screenshot diff;
- corpus homebrew legal.

### Risques juridiques

- Ne pas committer ROMs commerciales.
- Ne pas distribuer assets extraits.
- Suivre le modele Zelda64Recomp: binaire sans assets, ROM fournie par l'utilisateur.
- Pour homebrew/open ROMs, autoriser bundle complet si licence compatible.
- Licences runtime: privilegier zlib/MIT/BSD; attention GPL si distribution commerciale.

## 12. Recommandation Finale

### Ce qu'il faut construire

Construire **`qlnes recomp`**, pas essayer de "convertir sans runtime".

Definition produit:

> qlnes recomp traduit le code 6502 d'une ROM NES en code natif C/Rust, genere un runtime Linux specialise pour reproduire le hardware NES necessaire, puis compile un executable ELF/AppImage. Pour les moteurs reconnus, qlnes peut remplacer progressivement le runtime hardware par un port moteur natif.

### MVP concret

1. Backend C 6502 pour ROMs synthetiques NROM.
2. Runtime bus + RAM + PPU minimal.
3. SDL framebuffer.
4. NMI/vblank.
5. SMB title screen.
6. SMB 1-1 bootable.
7. AppImage.

### Definition de succes MVP

```bash
python -m qlnes recomp "roms/Super Mario Bros. (World).nes" -o out/smb-recomp --target linux
cd out/smb-recomp
./build.sh
./Super-Mario-Bros-NES
```

Le binaire produit:

- est un ELF Linux;
- ne depend pas de Python;
- ne lance pas un emulateur externe;
- execute du code 6502 traduit;
- contient un runtime NES specialise;
- peut etre emballe en AppImage.

### Ce qui ne doit pas etre promis

- Compatibilite universelle NES en V1.
- Absence totale de simulation hardware.
- Conversion parfaite de tous les jeux sans annotations.
- Distribution de ROMs commerciales.

### Meilleure phrase produit

**"Recompile NES ROMs into native Linux executables using generated 6502 code plus a ROM-specialized NES hardware runtime."**

En francais:

**"Recompiler des ROMs NES en executables Linux natifs via code 6502 genere et runtime hardware NES specialise par ROM."**

## Annexes: Sources

- NESdev PPU memory map: https://www.nesdev.org/wiki/PPU_memory_map
- NESdev PPU programmer reference: https://www.nesdev.org/wiki/PPU_programmer_reference
- NESdev Catch-up: https://www.nesdev.org/wiki/Catch-up
- NESdev Releasing on modern platforms: https://www.nesdev.org/wiki/Releasing_on_modern_platforms
- Jamulator article: https://andrewkelley.me/post/jamulator.html
- N64Recomp: https://github.com/N64Recomp/N64Recomp
- Zelda64Recomp: https://github.com/Zelda64Recomp/Zelda64Recomp
- Retrodisasm: https://github.com/retroenv/nesgodisasm
- LLVM LangRef: https://www.llvm.org/docs/LangRef.html
- llvmlite docs: https://llvmlite.readthedocs.io/en/stable/user-guide/binding/
- SDL homepage: https://www.libsdl.org/
- PyInstaller usage: https://pyinstaller.org/en/stable/usage.html
- AppImage manual packaging: https://docs.appimage.org/packaging-guide/manual.html
- appimagetool overview: https://appimage.github.io/appimagetool/
