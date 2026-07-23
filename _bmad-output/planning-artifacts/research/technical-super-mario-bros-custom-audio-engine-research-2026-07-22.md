---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - _bmad-output/audio-validation/super-mario-bros-audio-engine-note-2026-07-22.md
  - out/smb/smb.asm
  - _bmad-output/planning-artifacts/research/technical-audio-nes-vers-mp3-et-extraction-des-musiques-de-roms-research-2026-07-22.md
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Super Mario Bros custom NES audio engine'
research_goals: 'Comprendre le moteur audio custom de Super Mario Bros dans l ASM local, definir son modele de queues, headers, donnees musicales et les preconditions pour extraire/rendre toutes les musiques via qlnes.'
user_name: 'Johan'
date: '2026-07-22'
web_research_enabled: true
source_verification: true
---

# Super Mario Bros. custom audio engine: recherche technique complete

## 1. Conclusion courte

Oui, Super Mario Bros. possede un moteur audio custom. Ce n'est pas un moteur generique type FamiTone2/FamiTracker, mais un driver integre au jeu, appele une fois par frame depuis le flux NMI/frame. Il gere:

- musiques d'aire via `AreaMusicQueue`;
- musiques d'evenement via `EventMusicQueue`;
- effets square 1, square 2 et noise via queues separees;
- pause sound;
- tables de headers musicaux compactes;
- streaming de donnees par offsets par canal;
- enveloppes, longueurs, frequences, routage APU pulse/pulse/triangle/noise;
- modulation du DAC raw `$4011`, sans preuve d'un vrai playback DMC sample `$4010-$4013` dans cette passe.

Pour `qlnes`, SMB doit etre traite comme un engine dedie `smb_custom`. Le chemin simple "strip PRG + prepend NSF header" ne suffit pas pour une ROM commerciale comme SMB, sauf si on fabrique un stub `INIT/PLAY` qui initialise correctement RAM/queues et appelle le driver dans le meme etat que le jeu.

## 2. Sources

Sources locales:

- ROM locale: `roms/Super Mario Bros. (World).nes`
- ASM local inspecte: `out/smb/smb.asm`
- Note initiale: `_bmad-output/audio-validation/super-mario-bros-audio-engine-note-2026-07-22.md`
- Tests locaux qlnes:
  - `smb-bilan.json`: engine `unknown`, tier 2, `unverified`
  - `smb-10s-bilan.json`: engine `unknown`, tier 2, `unverified`

Sources externes:

- Disassembly SMB annotee SourceGen/6502disassembly, elle-meme derivee de la disassembly doppelganger: https://6502disassembly.com/nes-smb/SuperMarioBros.html
- Page projet de cette disassembly, qui decrit le layout iNES: 16-byte header, 32 KiB PRG, 8 KiB CHR: https://6502disassembly.com/nes-smb/
- NSF spec NESdev: https://www.nesdev.org/wiki/NSF
- NSF2 spec NESdev: https://www.nesdev.org/wiki/NSF2
- APU registers NESdev: https://www.nesdev.org/wiki/APU_registers
- VGMPF SMB page, utile seulement comme contexte soundtrack/composer, pas comme spec engine: https://www.vgmpf.com/Wiki/index.php?title=Super_Mario_Bros._%28NES%29

## 3. Carte d'adresses audio

Les adresses CPU principales alignees entre ASM local et disassembly annotee:

| CPU | ASM local | Nom annote | Role |
|---|---|---|---|
| `$F2D0` | `L_F2D0` | `SoundEngine` | Dispatcher audio frame |
| `$F381` | `play_pulse` | `Dump_Squ1_Regs` | Ecriture regs pulse 1 |
| `$F38B` | `play_pulse_3` | `SetFreq_Squ1` | Frequence pulse 1 via tables |
| `$F39F` | `play_pulse_4` | `Dump_Squ2_Regs` | Ecriture regs pulse 2 |
| `$F3A9` | `play_pulse_6` | `SetFreq_Squ2` | Frequence pulse 2 |
| `$F3AD` | `play_pulse_7` | `SetFreq_Tri` | Frequence triangle |
| `$F41B` | `L_F41B` | `Square1SfxHandler` | Effets square 1 |
| `$F57C` | `L_F57C` | `Square2SfxHandler` | Effets square 2 |
| `$F667` | `L_F667` | `NoiseSfxHandler` | Effets noise |
| `$F694` | `L_F694` | `MusicHandler` | Musique principale |
| `$F90D` | `L_F90D` | `MusicHeaderData` | Offsets + headers musique |
| `$FF00-$FF65` | `L_FF00/L_FF01` | frequency data | Table periodes notes |
| `$FF66+` | `L_FF66` | `MusicLengthLookupTbl` | Table longueurs notes |
| `$FF96+` | `L_FF96/L_FF9A/L_FFA2` | envelope data | Enveloppes volume |

Preuve locale:

- `out/smb/smb.asm:82`: `JSR L_F2D0` appelle le moteur audio depuis la routine frame/NMI.
- `out/smb/smb.asm:3961`: entree `L_F2D0`.
- `out/smb/smb.asm:4014-4017`: appels aux handlers `L_F41B`, `L_F57C`, `L_F667`, `L_F694`.
- `out/smb/smb.asm:4420-4433`: chargement de `L_F90C/Y` vers pointeur donnees et offsets.
- `out/smb/smb.asm:4882+`: tables de frequences et longueurs.

Preuve externe:

- La disassembly annotee nomme `$F2D0` `SoundEngine`, et montre qu'elle active les canaux avec `SND_CHN` apres avoir configure `JOY2`/frame counter.
- Elle nomme `$F694` `MusicHandler`, avec lecture de `EventMusicQueue` puis `AreaMusicQueue`.
- Elle documente `MusicHeaderData` et donne son format: 1 byte offset table longueur, 2 bytes adresse donnees, 1 byte offset triangle, 1 byte offset square 1, 1 byte offset noise.

## 4. Queues et buffers

Le moteur utilise des queues zero-page comme interface entre gameplay et audio:

| Adresse | Nom annote | Role |
|---|---|---|
| `$FA` | `PauseSoundQueue` | queue pause |
| `$FB` | `AreaMusicQueue` | queue musique d'aire |
| `$FC` | `EventMusicQueue` | queue musique evenement |
| `$FD` | `NoiseSoundQueue` | queue sfx noise |
| `$FE` | `Square2SoundQueue` | queue sfx square 2 |
| `$FF` | `Square1SoundQueue` | queue sfx square 1 |

Buffers et etat principal:

| Adresse | Nom annote | Role |
|---|---|---|
| `$F1` | `Square1SoundBuffer` | sfx actif square 1 |
| `$F2` | `Square2SoundBuffer` | sfx actif square 2 |
| `$F3` | `NoiseSoundBuffer` | sfx actif noise |
| `$F4` | `AreaMusicBuffer` | musique d'aire active |
| `$F5-$F6` | `MusicData` | pointeur base donnees musique |
| `$F7` | `MusicOffset_Square2` | offset stream square 2 |
| `$F8` | `MusicOffset_Square1` | offset stream square 1 |
| `$F9` | `MusicOffset_Triangle` | offset stream triangle |
| `$07B0` | `MusicOffset_Noise` | offset stream noise |
| `$07B1` | `EventMusicBuffer` | musique evenement active |
| `$07B4` | `Squ2_NoteLenCounter` | compteur longueur square 2 |
| `$07B6` | `Squ1_NoteLenCounter` | compteur longueur square 1 |
| `$07B9` | `Tri_NoteLenCounter` | compteur longueur triangle |
| `$07BA` | `Noise_BeatLenCounter` | compteur beat noise |
| `$07C4` | `NoteLengthTblAdder` | offset additionnel pour time-running-out |
| `$07C7` | `GroundMusicHeaderOfs` | position dans la sequence ground music |
| `$07CA` | `AltRegContentFlag` | variation de registre square 1 |

Constantes musique importantes:

| Bit | Area music | Event music |
|---|---|---|
| `$01` | GroundMusic | DeathMusic |
| `$02` | WaterMusic | GameOverMusic |
| `$04` | UndergroundMusic | VictoryMusic |
| `$08` | CastleMusic | EndOfCastleMusic |
| `$10` | CloudMusic | non applicable ici |
| `$20` | PipeIntroMusic / EndOfLevelMusic selon contexte | EndOfLevelMusic |
| `$40` | StarPowerMusic | TimeRunningOutMusic |
| `$80` | non applicable ici | Silence |

Interpretation: l'interface d'un handler `smb_custom` ne doit pas appeler directement chaque "song" comme un NSF abstrait. Elle doit probablement simuler l'ecriture de ces queues, puis laisser `MusicHandler` charger les bons headers et buffers.

## 5. Scheduler frame et pause

`SoundEngine` fait d'abord trois choses:

1. Si `OperMode` indique le title screen mode, il coupe `SND_CHN` puis retourne.
2. Sinon, il ecrit `$FF` dans `$4017` (`JOY2` dans la disassembly annotee) et `$0F` dans `$4015` pour activer pulse 1, pulse 2, triangle, noise.
3. Il verifie `PauseModeFlag` et `PauseSoundQueue`; en mode pause il coupe/reinitialise des buffers sfx, joue des tons courts sur square 1, puis reprend.

Ensuite, quand pas en pause, il appelle:

- `Square1SfxHandler`;
- `Square2SfxHandler`;
- `NoiseSfxHandler`;
- `MusicHandler`.

En fin de frame, il remet a zero les queues `$FF/$FE/$FD/$FA` et ecrit un compteur vers `$4011` (`APU_DMC_RAW`). C'est important: un ripper doit ecrire les queues avant l'appel frame, pas apres.

## 6. Gestion des musiques

`MusicHandler` suit cette priorite:

1. `EventMusicQueue` non nulle: charger l'evenement dans `EventMusicBuffer`.
2. Sinon `AreaMusicQueue` non nulle: charger l'aire dans `AreaMusicBuffer`.
3. Sinon si `EventMusicBuffer OR AreaMusicBuffer` est non nul: continuer la musique courante.
4. Sinon: `RTS`.

Pour une musique d'aire, `AreaMusicQueue` est un bitfield; le code decale A jusqu'au bit actif pour trouver un offset dans `MusicHeaderData`. Pour ground music, il utilise `GroundMusicHeaderOfs` et une sequence de headers pour enchaîner les parties du theme principal.

Cas special `TimeRunningOutMusic`: le moteur sauvegarde l'ancienne area music dans `AreaMusicBuffer_Alt`, applique `NoteLengthTblAdder = $08`, puis peut relancer la musique precedente apres l'evenement. Ce comportement doit etre preserve si on veut reproduire les versions "hurry up".

## 7. Format des headers et streams

La disassembly annotee documente le header musique:

```text
byte 0: offset dans la table de longueurs
byte 1-2: adresse CPU des donnees musique
byte 3: offset triangle dans le bloc
byte 4: offset square 1 dans le bloc
byte 5: offset noise dans le bloc, absent/non utilise pour certaines musiques secondaires
```

Le stream square 2 commence a offset 0 dans `MusicData`; square 1, triangle et noise utilisent leurs offsets respectifs.

Regles decode observees:

- `0x00`: fin de donnees ou silence selon canal/contexte.
- byte positif (`<0x80`): note ou code rythmique.
- byte negatif (`>=0x80`): donnees de longueur, traitees via `ProcessLengthData`.
- les notes sont transformees par masques (`AND #$3E`) puis indexent les tables de frequence.
- les longueurs passent par `MusicLengthLookupTbl` avec `NoteLenLookupTblOfs` et `NoteLengthTblAdder`.
- les enveloppes passent par `LoadControlRegs` et `LoadEnvelopeData`.

## 8. Canaux APU

Pulse 1 et pulse 2:

- Les effets ont priorite via `Square1SoundBuffer` et `Square2SoundBuffer`.
- La musique square 2 est traitee en premier (`HandleSquare2Music`).
- Les helpers partagent une table de periode: low byte a `$FF01,Y`, high byte a `$FF00,Y`, puis ecriture vers `$4002/$4003`, `$4006/$4007` selon X.
- Les registres volume/sweep sont recalcules par contexte: water, win castle, death music, events.

Triangle:

- Le stream triangle utilise `MusicOffset_Triangle` et `Tri_NoteLenCounter`.
- Il ecrit le timer via le meme helper de frequence, avec X pointe sur les registres triangle.
- Il module `$4008` entre `$1F`, `$0F`, `$FF` selon note et contexte.

Noise:

- SFX noise: brick shatter et Bowser flame sont geres par `NoiseSfxHandler`.
- Music noise: `MusicOffset_Noise` et `Noise_BeatLenCounter` lisent des codes qui deviennent des triplets `$400C/$400E/$400F`.
- Le moteur utilise au moins trois profils de noise music: `$1C/$03/$18`, `$1C/$0C/$18`, `$1C/$03/$58`, et un fallback `$10`.

DMC / DAC raw:

- Le boot ecrit `$4011`.
- `SoundEngine` ecrit `$4011` en fin de frame depuis `DAC_Counter`.
- Aucun usage confirme de `$4010-$4013` comme sample DMC complet dans les lignes inspectees.

## 9. Pourquoi le fallback qlnes reste silencieux

Le fallback actuel de `qlnes audio` boote la ROM et laisse tourner sans script gameplay ni queue. Or SMB ne demarre pas une musique juste en appelant le CPU: la musique depend de l'etat de jeu (`OperMode`, queues, buffers, entree area/event). Sans initialiser une queue comme `AreaMusicQueue = GroundMusic` et l'etat RAM minimal attendu, le moteur peut rester muet.

Ce resultat n'est donc pas un echec audio APU; c'est une preuve que SMB a besoin d'un handler d'initialisation.

## 10. Strategie `smb_custom` pour qlnes

Detection:

- mapper 0 / NROM;
- PRG 32 KiB;
- presence du call `JSR $F2D0` depuis la routine frame;
- presence de `SoundEngine` qui ecrit `$4017`, `$4015`, puis appelle les quatre handlers;
- presence de `MusicHeaderData` a `$F90D` et table frequence a `$FF00`;
- SHA connu en manifest prive pour les tests commerciaux locaux, sans committer la ROM.

Enumeration:

- enumerer les bits `AreaMusicQueue`: ground, water, underground, castle, cloud, pipe intro, star power;
- enumerer les bits `EventMusicQueue`: death, game over, victory, end castle, end level, time running out, silence;
- pour ground music, enumerer soit le theme compose comme une playlist de headers, soit chaque header partiel avec metadata `segment`;
- separer musiques et sfx: square/noise sfx ne doivent pas etre classes comme tracks music par defaut, mais peuvent devenir `psfx` NSFe plus tard.

Render:

1. Boot minimal ou reset RAM NSF-like.
2. Forcer `OperMode` dans un mode non-title.
3. Ecrire la queue voulue (`$FB` ou `$FC`) avant le premier appel `SoundEngine`.
4. Appeler `$F2D0` une fois par frame.
5. Capturer les ecritures APU et rendre PCM.
6. Stopper au zero/end marker, boucle detectee par retour header, ou duree configuree.

NSF:

- Option 1: NSF wrapper qui embarque PRG et fournit `INIT(song)` pour mapper song index -> queue, puis `PLAY()` -> `JSR $F2D0; RTS`.
- Option 2: rendu direct qlnes sans produire NSF, plus simple pour valider.
- Le wrapper doit initialiser toutes les RAM utilisees par le moteur audio, en particulier queues/buffers/counters.
- Les players NSF classiques n'appellent pas NMI; `PLAY` doit retourner.

Verification:

- reference FCEUX locale sur ROM utilisateur;
- comparer au moins: ground, underground, water, castle, death/game over, time running out;
- mesurer non-silence, duree > 1 s, dominante attendue sur une fenetre controlee seulement comme smoke test; la preuve tier-1 reste PCM/reference.

## 11. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Mauvais init RAM | silence ou mauvais morceau | cribler les writes RAM du jeu avant queue musicale |
| Confusion area vs event | piste interrompue ou priorite fausse | modeler deux namespaces de tracks |
| Ground music segmente | extraction en morceaux au lieu du theme complet | playlist de headers avec detection de loop |
| Time-running-out | tempo/longueur faux | implementer `NoteLengthTblAdder` et restauration area |
| SFX vs musique | trop de tracks parasites | `music` par defaut, `sfx` optionnel |
| Copyright ROM/audio | risque legal | hashes/notes seulement, references locales non committees |

## 12. Reponse a la question "avaient-ils un moteur SMB?"

Oui. Le moteur SMB existe clairement: `SoundEngine` a `$F2D0`, avec queues, buffers, handlers sfx et music handler. Ce qui n'existait pas est un protocole standardise d'extraction NSF directement separable du jeu. Le moteur a ete ecrit pour SMB et son etat gameplay; il faut donc soit un wrapper qui recrée cet etat, soit un renderer direct qui ecrit les queues et appelle `$F2D0` frame par frame.

## 13. Sources a citer dans les epics/stories

- SourceGen SMB disassembly: https://6502disassembly.com/nes-smb/SuperMarioBros.html
- NSF spec: https://www.nesdev.org/wiki/NSF
- NSF2 spec: https://www.nesdev.org/wiki/NSF2
- APU registers: https://www.nesdev.org/wiki/APU_registers

**Technical Confidence Level:** High pour la structure du moteur, les queues, les handlers et le format de header; medium pour la liste exacte de tracks finales tant qu'un prototype n'a pas valide les transitions ground/time-running-out contre FCEUX.
