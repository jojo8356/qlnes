---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - _bmad-output/project-context.md
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design.md
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Audio NES vers MP3 et extraction des musiques de ROMs'
research_goals: 'Comprendre l audio de la NES, les formats et pipelines d extraction, puis definir comment convertir les musiques de ROMs NES en MP3 pour planifier les epics et stories du projet qlnes.'
user_name: 'Johan'
date: '2026-07-22'
web_research_enabled: true
source_verification: true
---

# Audio NES vers MP3: recherche technique complete pour l'extraction des musiques de ROMs

**Date:** 2026-07-22
**Author:** Johan
**Research Type:** technical

## Research Overview

Cette recherche couvre l'audio NES de bout en bout pour `qlnes`: fonctionnement APU, drivers musique dans les ROMs, formats NSF/NSF2/NSFe, rendu PCM/WAV, encodage MP3 et verification par oracle FCEUX. Elle s'appuie sur des sources techniques actuelles et verifiables: NESdev pour APU/NSF/NSFe/iNES, FamiStudio pour l'interface des engines modernes, FCEUX pour Lua/oracle, Python/lameenc/pytest/Typer pour la stack d'implementation.

La conclusion structurante est que les musiques NES ne se "convertissent" pas directement en MP3. Une ROM contient du code 6502, des donnees musique et parfois des extensions mapper; le bon pipeline est ROM -> detection engine/song table -> execution `init/play` ou trace -> evenements APU -> PCM canonique -> WAV/MP3/NSF. Le MP3 est une sortie lossy derivee; l'equivalence doit etre verifiee sur PCM.

## Executive Summary

L'audio NES est une execution, pas un fichier audio cache dans la ROM. Les jeux pilotent l'APU 2A03/2A07 via des registres memoire; les moteurs musique lisent des sequences/instruments propres a chaque jeu ou famille d'engine, puis ecrivent periodiquement vers les canaux pulse, triangle, noise, DMC et parfois vers des puces d'expansion. La conversion fiable vers MP3 passe donc par un artefact intermediaire canonique: le PCM.

Pour `qlnes`, la strategie robuste est un pipeline local, deterministe et testable: parser la ROM, detecter mapper/engine/expansion, enumerer les pistes, executer le moteur ou generer un NSF, capter les ecritures APU, rendre le PCM, puis produire WAV/MP3/NSF. L'equivalence doit etre mesuree contre FCEUX sur PCM, pas contre les bytes MP3.

**Key Technical Findings:**

- La NES expose cinq canaux APU internes; DMC et expansion audio compliquent rapidement l'equivalence. Source: https://www.nesdev.org/wiki/APU
- NSF est un format executable `INIT`/`PLAY`, pas un dump audio; NSF2/NSFe apportent metadata pistes et compatibilite moderne. Sources: https://www.nesdev.org/wiki/NSF et https://www.nesdev.org/wiki/NSFe
- Les moteurs musique NES ne partagent pas un bytecode universel; il faut des handlers par engine et une couverture explicite. Source: https://www.nesdev.org/wiki/Audio_drivers
- FCEUX Lua fournit un oracle pratique pour avancer frame par frame et inspecter l'etat audio. Source: https://fceux.com/web/help/LuaFunctionsList.html
- `lameenc` est adapte a la sortie MP3 Python, mais la verification doit rester PCM car MP3 est lossy et dependant de l'encodeur. Source: https://pypi.org/project/lameenc/

**Technical Recommendations:**

- Construire d'abord WAV/PCM tier-1 pour une ROM mapper 0 et un engine reconnu.
- Ajouter MP3 comme sink derive de PCM, avec pin stricte `lameenc`.
- Ajouter NSF2/NSFe ensuite pour la distribution chiptune et metadata.
- Publier la progression en matrice `(mapper, audio_engine, expansion_audio, artifact)`.
- Ne jamais promettre `pass` pour un engine inconnu; produire `unverified` si fallback trace.

## Table of Contents

1. Scope et methodologie
2. Paysage technique NES audio
3. Stack technique
4. Integration et formats
5. Architecture cible `qlnes`
6. Pipeline ROM vers MP3
7. Performance, scalabilite et determinisme
8. Securite, legal et compliance
9. Roadmap d'implementation
10. Risques et mitigations
11. Sources et verification

## 1. Scope et methodologie

**Research Topic:** Audio NES vers MP3 et extraction des musiques de ROMs

**Research Goals:** Comprendre l audio de la NES, les formats et pipelines d extraction, puis definir comment convertir les musiques de ROMs NES en MP3 pour planifier les epics et stories du projet qlnes.

**Technical Scope:**

- Architecture Analysis: APU, drivers, mappers, expansion audio, oracle.
- Implementation Approaches: ROM -> events -> PCM -> WAV/MP3/NSF.
- Technology Stack: Python 3.11+, Typer, pytest, FCEUX, `lameenc`, stdlib `wave`.
- Integration Patterns: CLI subprocess, fichiers deterministes, corpus hashes-only.
- Performance Considerations: chunks PCM, cache references, parallelisation par ROM/piste.

## 2. Paysage technique NES audio

La NES genere le son via l'APU integre au CPU: deux pulses, triangle, noise et DMC. Les registres `$4000-$4015` et `$4017` controlent timers, volumes, envelopes, length counters, sweep, DMC et frame counter. Source: https://www.nesdev.org/wiki/APU_registers

Le frame counter cadence envelopes, sweep et length units environ quatre fois par frame NTSC. La precision temporelle importe parce que les engines appellent souvent leur update une fois par frame, mais les effets audio et le mixage se resolvent en cycles et samples. Source: https://www.nesdev.org/wiki/APU

Le mixage n'est pas lineaire; NESdev documente des formules et lookup tables pour les groupes pulse et TND, avec filtres analogiques derriere. Pour `qlnes`, cela impose un renderer fixe et teste, idealement entier/table-driven. Source: https://www.nesdev.org/wiki/APU_Mixer

Les drivers musique NES mettent a jour l'audio souvent une fois par frame. FamiStudio montre une interface moderne typique: init, play song, update par frame depuis NMI. Source: https://famistudio.org/doc/soundengine/

## 3. Stack technique

### Programming Languages

- Python 3.11+ pour orchestration CLI, parsing, writers, tests et audit.
- 6502/2A03 comme code cible a executer, tracer ou reconstituer.
- Lua pour piloter FCEUX comme oracle.
- C uniquement pour le disassembleur vendore existant.

### Libraries and Tools

- `Typer`: CLI existante et tests via `CliRunner`. Source: https://typer.tiangolo.com/tutorial/testing/
- `pytest`: parametrisation des matrices `(rom, mapper, engine, format)`. Source: https://docs.pytest.org/en/stable/how-to/parametrize.html
- stdlib `wave`: ecriture WAV PCM non compresse. Source: https://docs.python.org/3/library/wave.html
- `lameenc`: encodage MP3 depuis PCM 16-bit interleaved, wheels Python modernes; version a pinner. Source: https://pypi.org/project/lameenc/
- FCEUX: oracle externe avec Lua `emu.frameadvance()` et `sound.get()`. Source: https://fceux.com/web/help/LuaFunctionsList.html

### Storage

Aucune base de donnees n'est necessaire. Les donnees persistantes doivent rester des fichiers deterministes et auditables:

- `corpus/manifest.toml` pour declarer ROMs par SHA-256, mapper, engine, region, durees attendues et hashes de reference.
- `bilan.json` comme etat machine genere de la couverture.
- `tracks/*.wav`, `tracks/*.mp3`, `ost.nsf` comme artefacts.
- `trace/*.tsv` ou JSONL pour les ecritures APU capturees.

## 4. Integration et formats

Les vrais contrats d'interoperabilite sont binaires et temporels:

- `.nes` iNES/NES 2.0: entree ROM; detection mapper, PRG/CHR, region, trainer, PRG-RAM.
- NSF/NSF2: sortie chiptune executable par players.
- NSFe chunks: metadata pistes (`tlbl`), durees (`time`), fade (`fade`), playlist (`plst`), auteurs (`auth`).
- WAV PCM: sortie canonique lossless et support d'equivalence.
- MP3: sortie lossy derivee de PCM, pratique pour usage final.
- TOML/JSON: configuration, manifest, bilan.
- TSV/JSONL: trace APU event stream.

NESdev decrit NSF comme un payload de code musique NES precede d'un header, puis un protocole `INIT`/`PLAY`. Si les bytes `$070-$077` sont non-zero, le bankswitch NSF utilise 8 banques de 4 KiB controlees via `$5FF8-$5FFF`; les appels `PLAY` suivent la periode declaree NTSC/PAL. Source: https://www.nesdev.org/wiki/NSF

NSFe ajoute des chunks metadata extensibles et a ete incorpore dans NSF2. Les chunks `tlbl`, `time`, `fade` et `plst` sont directement utiles pour produire des OST exploitables, avec titres, durees et boucles. Source: https://www.nesdev.org/wiki/NSFe

L'expansion audio force l'interoperabilite mapper+audio. FamiStudio liste des expansions VRC6, VRC7, FDS, MMC5, Sunsoft S5B, Namco 163 et indique qu'un export doit faire correspondre expansion active et donnees chargees. Pour `qlnes`, une mauvaise combinaison mapper/engine/expansion doit echouer avant ecriture. Source: https://famistudio.org/doc/expansion/

## 5. Architecture cible `qlnes`

Architecture recommandee:

```text
RomLoader -> RomProfile -> EngineRegistry -> SongPlan
SongPlan -> Runner -> ApuWriteEvent stream -> ApuEmulator -> PCM
PCM -> WavWriter
PCM -> Mp3Writer
SongPlan/PRG -> Nsf2NsfeWriter
FceuxOracle -> reference trace/PCM -> Audit -> bilan.json
```

Les modules doivent suivre une separation ports/adapters:

- coeur: ROM profile, engine match, song plan, events APU, PCM.
- adaptateurs: CLI Typer, FCEUX subprocess/Lua, `lameenc`, filesystem, NSF/WAV writers.

Le modele event sourcing est pertinent localement: les ecritures APU constituent un journal qui permet de reconstruire le PCM, comparer deux executions, isoler un drift et rejouer un bug. Fowler decrit l'event sourcing comme la capture de tous les changements d'etat en sequence d'evenements; Microsoft rappelle que ce pattern est couteux mais justifie quand auditabilite et reconstruction historique sont centrales. Ici, il faut l'appliquer seulement au flux APU, pas a toute l'application. Sources: https://www.martinfowler.com/eaaDev/EventSourcing.html et https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing

## 6. Pipeline ROM vers MP3

Pipeline concret:

1. Lire `.nes`, valider header, mapper, PRG/CHR, region.
2. Identifier expansion audio possible par mapper/submapper.
3. Detecter engine via signatures, tables, init/play candidates et evidence.
4. Enumerer toutes les pistes, y compris non referencees quand la table le permet.
5. Executer `init(song)` puis `play/update` pendant une duree connue ou jusqu'a boucle detectee.
6. Capturer `ApuWriteEvent(cpu_cycle, address, value)`.
7. Rendre PCM au sample rate fixe.
8. Ecrire WAV PCM lossless.
9. Encoder MP3 depuis PCM via `lameenc`.
10. Ecrire provenance et couverture.

Le MP3 ne doit pas etre compare byte-a-byte entre environnements sauf version encodeur verrouillee; le hash canonique est celui du PCM.

## 7. Performance, scalabilite et determinisme

Performance cible:

- rendu <= 2x temps reel sur corpus MVP.
- parallelisation par ROM et par piste, pas a l'interieur d'une piste tant que l'equivalence n'est pas stable.
- PCM streaming par chunks.
- tables APU precomputees.
- caches par SHA-256 et provenance.
- audit 50 ROMs sous 30 minutes selon PRD.

Determinisme:

- pas de wall-clock dans artefacts.
- ordre trie dans JSON.
- ecritures atomiques.
- sample rate fixe.
- version FCEUX/lameenc inscrite.
- PCM comme artefact de preuve, MP3 comme artefact derive.

## 8. Securite, legal et compliance

Le repo ne doit pas contenir de ROMs commerciales ni d'audio derive. Le corpus public doit stocker uniquement hashes, metadata et scripts. Les utilisateurs placent leurs ROMs localement; `qlnes audit` valide les hashes et genere references locales.

Les erreurs doivent etre loud and specific: unsupported mapper, unsupported expansion, engine unknown, encoder absent, FCEUX absent. Pas de sortie corrompue ou partielle.

## 9. Roadmap d'implementation

1. Types core et writers atomiques.
2. Preflight CLI et erreurs structurees.
3. FCEUX oracle minimal + Lua trace.
4. APU MVP pulse/triangle/noise, DMC stub.
5. Premier engine reconnu sur mapper 0.
6. WAV tier-1 avec equivalence PCM.
7. MP3 sink depuis PCM.
8. NSF2 header/payload.
9. NSFe chunks metadata.
10. `bilan.json` coverage.
11. Expansion engines/mappers par corpus.

## 10. Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Engine inconnu | piste manquante ou mauvaise | fallback trace `unverified`, coverage matrix explicite |
| APU Python diverge de FCEUX | invariant rate | tests par canal, trace diff, oracle versionne |
| MP3 non deterministe entre versions | faux negatif byte hash | PCM canonical; pin `lameenc`; MP3 hash informative |
| Expansion audio mal detectee | audio incomplet | preflight mapper/expansion; status unsupported |
| ROM copyright | risque legal | manifest hashes only; pas de ROM ni audio derive committe |
| Performance corpus | audit trop lent | xdist par ROM, cache references |

## 11. Sources et verification

Sources principales consultees:

- NESdev APU: https://www.nesdev.org/wiki/APU
- NESdev APU registers: https://www.nesdev.org/wiki/APU_registers
- NESdev APU mixer: https://www.nesdev.org/wiki/APU_Mixer
- NESdev NSF: https://www.nesdev.org/wiki/NSF
- NESdev NSF2: https://www.nesdev.org/wiki/NSF2
- NESdev NSFe: https://www.nesdev.org/wiki/NSFe
- NESdev Audio drivers: https://www.nesdev.org/wiki/Audio_drivers
- NESdev Expansion audio: https://www.nesdev.org/wiki/Category:Expansion_audio
- FamiStudio sound engine: https://famistudio.org/doc/soundengine/
- FamiStudio expansion audio: https://famistudio.org/doc/expansion/
- FCEUX Lua functions: https://fceux.com/web/help/LuaFunctionsList.html
- Python `wave`: https://docs.python.org/3/library/wave.html
- lameenc PyPI: https://pypi.org/project/lameenc/
- Typer testing: https://typer.tiangolo.com/tutorial/testing/
- pytest parametrization: https://docs.pytest.org/en/stable/how-to/parametrize.html

**Technical Confidence Level:** High pour APU/NSF/WAV/CLI/test strategy; medium pour equivalence exacte FCEUX tant que le projet n'a pas encore de fixtures corpus locales et de reference PCM generee.

## Technical Research Conclusion

La bonne definition produit de "get toutes les musics des ROMs" est: extraire toutes les pistes detectables pour les couples `(mapper, audio_engine, expansion_audio)` supportes, produire WAV/MP3/NSF, et publier clairement ce qui est `pass`, `unverified` ou `unsupported`. Le MVP doit commencer par une tranche etendue verticalement, pas par une promesse universelle.

**Next technical step:** utiliser ce document comme input pour les epics/stories: obtenir une premiere piste WAV verifiee, obtenir MP3, obtenir NSF/NSFe, auditer la couverture, puis elargir engines/mappers.

**Technical Research Completion Date:** 2026-07-22

## 12. Addendum 2026-07-22: extraction NSF via emulateurs, players et plugins

La remarque utilisateur ajoute une voie importante: `qlnes` ne doit pas seulement partir de `.nes`; il doit aussi accepter les `.nsf` ou `.nsfe` produits par des outils externes, puis automatiser leur ecoute/conversion avec des players specialises. C'est souvent plus robuste qu'un ripper ROM universel.

Constats verifies:

- Le format NSF est un conteneur executable: code/data musique + header `INIT`/`PLAY`, charge et joue par un player NSF ou un emulateur NES. Source: https://www.nesdev.org/wiki/NSF
- FCEUX sait ouvrir les formats `.nes`, `.fds`, `.unf`, `.unif`, `.nsf` et archives compressees qui les contiennent. Cela en fait un oracle/lecteur utile, mais pas une garantie de rip automatique depuis n'importe quelle ROM commerciale. Source: https://fceux.com/web/help/Gamefilecompatibility.html
- NSFPlay est open source, fournit un player NSF/NSFe Windows et le plugin Winamp NSFPlug; son repo contient aussi des utilitaires CLI contrib pour rendre en WAV ou manipuler les metadata. Source: https://bbbradsmith.github.io/nsfplay/ et https://github.com/bbbradsmith/nsfplay
- `game-music-emu` / `libgme` supporte NSF et NSFE et constitue une meilleure dependance de lecture/conversion cross-platform qu'un plugin Winamp pour le pipeline CLI. Source: https://github.com/libgme/game-music-emu
- `asanoic/nsf-ripper` est un petit wrapper C++ autour de `game-music-emu` qui lit un fichier `.nsf` et rend chaque piste en FLAC. Le README indique `NsfRipper [NSF file]`; le test local confirme qu'il ne dumpe pas une ROM `.nes`. Source: https://github.com/asanoic/nsf-ripper
- NSFe liste explicitement des players compatibles, dont Audio Overload, Game Emu Player pour foobar2000, VLC, NSFPlay, Mesen et NotSoFatso/Winamp. Source: https://www.nesdev.org/wiki/NSFe
- `NSF2WAV` existe historiquement dans l'ecosysteme NEZplug comme convertisseur NSF/KSS/HES/GBR/AY vers WAV, mais il depend de composants Windows/Winamp-era et doit etre traite comme adapter optionnel, pas comme backend principal. Source: https://nezplug.sourceforge.net/

Implication architecture:

1. Ajouter une entree `qlnes audio input.nsf` en plus de `qlnes audio input.nes`.
2. Pour `.nsf/.nsfe`, utiliser un backend player deterministe (`libgme` en premier, NSFPlay CLI/contrib en option) pour rendre PCM/WAV, puis MP3.
3. Pour `.nes`, garder la detection engine interne et les adapters externes comme voies opportunistes: NES2NSF/SlickNSF/FCEUX/Mesen peuvent fournir des indices ou artefacts, mais chaque sortie doit garder son statut de provenance.
4. Les plugins Winamp/players GUI servent a l'ecoute manuelle et a la validation utilisateur; ils ne doivent pas etre la dependance principale d'un batch CLI Linux.
5. Le bilan doit distinguer `source_rom_extracted`, `source_nsf_imported`, `source_emulator_dumped` et `source_manual_external` pour eviter de presenter un NSF externe comme une extraction prouvee par `qlnes`.
6. La methode "strip NES header" est seulement un raccourci de reverse-engineering pour certains cas simples: un vrai NSF exige un header `NESM`, le nombre de pistes, les adresses load/init/play, les timings NTSC/PAL, les flags expansion audio et parfois des banques. Pour Super Mario Bros., le moteur et les tables sont integres au jeu; il faut donc dumper/ripper avec evidence ASM ou debugger, pas renommer le fichier.

Decision recommandee:

- Court terme: supporter `.nsf/.nsfe` comme entree officielle et convertir toutes les pistes en WAV/MP3 via `libgme` ou NSFPlay.
- Moyen terme: ajouter des adapters pour rippers historiques quand disponibles localement (`NES2NSF`, `SlickNSF`, `NSF2WAV`/NEZplug, outils utilisateur comme `lando-nsf2wav` s'ils sont fournis), et des renderers `.nsf -> audio` comme `asanoic/nsf-ripper`, avec statut `unverified` tant qu'une comparaison PCM n'est pas passee.
- Long terme: implementer les handlers de moteurs ROM prioritaires (`FamiTone2`, SMB custom, moteurs connus par corpus) pour produire NSF/NSFe et PCM sans dependance GUI.

### Test local de `asanoic/nsf-ripper`

Commande et resultat:

- Clone: `git clone --recurse-submodules https://github.com/asanoic/nsf-ripper.git _bmad-output/external-tools/nsf-ripper`
- Probleme upstream: le submodule `https://github.com/asanoic/pull-flac.git` retourne `Repository not found`.
- Patch local applique au `CMakeLists.txt`: remplacer `add_subdirectory(flac)` par `pkg_check_modules(FLAC REQUIRED IMPORTED_TARGET flac)` et lier `PkgConfig::FLAC`.
- Build: `cmake -S ... -B ... -DCMAKE_BUILD_TYPE=Release`, puis `cmake --build ...` => succes.
- Commit teste: `6a82ad336f94fca86f1ac76c69d71581b542bb8c`.
- Binaire local: `_bmad-output/external-tools/nsf-ripper/build/NsfRipper`, SHA-256 `395ffaeb81ab96073991e18c8ae073ea93d14309bbb056cae28f9de9192ebb9d`.
- Test `.nes`: `NsfRipper "roms/Super Mario Bros. (World).nes"` => exit `139` / segfault. L'outil n'est donc pas un dumper ROM -> NSF.
- Test `.nsf`: `NsfRipper "_bmad-output/external-tools/nsf-ripper/Chip 'n Dale Rescue Rangers.nsf"` => exit `0`, 16 pistes FLAC produites; premiere piste mesuree a `180.000000` secondes. Les NSF exemples et FLAC de test ont ete supprimes ensuite pour ne pas conserver d'audio derive dans le projet.

Conclusion d'integration: `asanoic/nsf-ripper` peut inspirer ou servir d'adapter `.nsf -> .flac`, mais `qlnes` ferait mieux d'integrer directement `libgme` ou un backend equivalent pour produire PCM/WAV/MP3 avec controle de duree, metadata, erreurs et provenance. Il ne resout pas l'etape difficile Super Mario Bros. `.nes -> .nsf`.

### Addendum: cas NESASM/homebrew mapper 0

Une discussion NESdev fournie par l'utilisateur clarifie un cas plus simple que Super Mario Bros.: une ROM homebrew mapper 0, 16 KiB ou 32 KiB, ecrite en NESASM, dont l'auteur connait les adresses `INIT` et `PLAY`.

Points techniques a retenir:

- `NES2NSF` n'est pas un convertisseur magique ROM -> NSF; c'est plutot un outil de compilation/splitting avec configuration et heuristiques, et il est historiquement fragile.
- Pour NROM/mapper 0, si le programme est deja structure en driver audio, on peut prendre le PRG sans l'iNES header et lui prependre un header NSF valide.
- Le dump PRG depend de l'origine: code a `$8000` => dump `$8000-$FFFF` pour 32 KiB; code a `$C000` => dump `$C000-$FFFF` et load address NSF adaptee.
- Le `PLAY` NSF doit executer une frame de musique puis `RTS`. Un `JSR play` dans la NMI d'une ROM donne souvent le candidat `PLAY`.
- Le `INIT` NSF doit initialiser puis `RTS`; pour un programme mono-piste sans init, il peut pointer vers un `RTS` vide.
- Les players NSF classiques n'executent pas le programme comme une ROM complete avec PPU/NMI libre. Si la musique attend le VBlank, lit des registres PPU, ou boucle sans retourner, il faut refactorer vers le protocole `INIT`/`PLAY` ou utiliser une approche "iNES music file" / emulateur complet.

Implication pour `qlnes`: ajouter une voie `qlnes nsf --from-prg-plan` ou `qlnes nsf --homebrew-nrom` pour les ROMs simples ou les projets source controlables. Cette voie ne convient pas aux ROMs commerciales complexes comme Super Mario Bros. sans reverse-engineering du moteur et de ses tables. Pour SMB, il faut encore identifier le dispatcher, la table de songs, l'initialisation RAM et le point `PLAY` equivalent avant de construire un NSF.
