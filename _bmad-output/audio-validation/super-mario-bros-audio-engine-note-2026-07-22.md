# Super Mario Bros. Audio Engine Note - 2026-07-22

> Update: cette note etait la premiere passe ASM. La recherche complete BMAD
> dediee au moteur SMB custom est maintenant dans
> `_bmad-output/planning-artifacts/research/technical-super-mario-bros-custom-audio-engine-research-2026-07-22.md`.

## Source

- ROM locale: `roms/Super Mario Bros. (World).nes`
- SHA-256: `0b3d9e1f01ed1668205bab34d6c82b0e281456e137352e4f36a9b2cfa3b66dea`
- ASM inspecte: `out/smb/smb.asm`
- Rendu qlnes teste:
  - `_bmad-output/audio-validation/smb-tracks/Super Mario Bros. (World).00.unknown.wav`
  - `_bmad-output/audio-validation/smb-tracks-10s/Super Mario Bros. (World).00.unknown.wav`

## Finding

Super Mario Bros. n'utilise pas FamiTracker/FamiTone2. L'ASM montre un moteur
audio custom, situe principalement entre `L_F2D0` et `L_F8C4`, appele depuis la
routine frame/NMI a `L_80E4`.

Le moteur est donc reconnaissable par structure, mais pas encore supporte comme
engine tier-1 dans qlnes. Le test CLI actuel tombe correctement sur le fallback
`unknown`, tier 2, `unverified`.

## Entry Point and Scheduler

- `out/smb/smb.asm:82`: `JSR L_F2D0` appelle le moteur audio une fois par frame
  depuis la boucle NMI/frame.
- `out/smb/smb.asm:3961`: `L_F2D0` est le dispatcher audio principal.
- `out/smb/smb.asm:3967-3968`: le moteur active les canaux APU avec
  `LDA #0x0F ; STA APU_STATUS`.
- `out/smb/smb.asm:4014-4017`: le dispatcher appelle quatre sous-systemes:
  `L_F41B`, `L_F57C`, `L_F667`, `L_F694`.

Interpretation:

- `L_F41B` pilote surtout pulse 1 / effets courts.
- `L_F57C` pilote surtout pulse 2 / effets ou second voice.
- `L_F667` pilote noise / bruitages.
- `L_F694` lance et entretient la musique principale multi-canaux.

## APU Channels

### Pulse 1 and Pulse 2

- `out/smb/smb.asm:4038-4049`: helpers generiques:
  - `play_pulse` ecrit `APU_PULSE1_SWEEP` et `APU_PULSE1_CTRL`.
  - `play_pulse_3` lit les tables de periode `L_FF00/L_FF01` et ecrit
    `APU_PULSE1_TIMER_LO,X` puis `APU_PULSE1_TIMER_HI,X`.
- `out/smb/smb.asm:4051-4056`: equivalent pulse 2:
  - `play_pulse_4` ecrit `APU_PULSE2_CTRL` et `APU_PULSE2_SWEEP`.
  - `play_pulse_6` utilise `X = #0x04`, donc le meme chemin de timer cible
    les registres pulse 2.

Conclusion:

- Le moteur utilise une table de periodes 16-bit a `L_FF00/L_FF01`.
- Les notes ne sont pas stockees comme MIDI/FamiTone2 direct; ce sont des codes
  internes transformes en index de table.

### Triangle

- `out/smb/smb.asm:4550-4556`: le moteur active le triangle avec
  `LDA #0x1F ; STA APU_TRI_CTRL`, puis decode une note et appelle
  `play_pulse_7`.
- `out/smb/smb.asm:4057-4058`: `play_pulse_7` positionne `X = #0x08`, ce qui
  cible les registres triangle via le helper commun de timer.
- `out/smb/smb.asm:4568-4576`: le volume/linear control triangle est ajuste
  entre `#0x0F`, `#0x1F` et `#0xFF` selon le contexte musical.

Conclusion:

- Le triangle partage le chemin de table de periodes avec les pulses.
- Le canal basse de la musique SMB passe donc par ce scheduler, pas par un
  format FamiTone2.

### Noise

- `out/smb/smb.asm:4334-4352`: routine d'effet noise courte:
  - compteur `ram_07BF`
  - table de periodes `L_F62B`
  - enveloppes/volumes depuis `L_FFEA`
  - ecrit `APU_NOISE_CTRL`, `APU_NOISE_PERIOD`, `APU_NOISE_LEN`.
- `out/smb/smb.asm:4577-4616`: branche noise de la musique principale:
  - lit les donnees via `(ptr4_lo),Y`
  - mappe certains codes vers des profils `#0x1C/#0x03/#0x18`,
    `#0x1C/#0x0C/#0x18`, `#0x1C/#0x03/#0x58`, sinon `#0x10`
  - ecrit les trois registres noise.

Conclusion:

- Le moteur couvre bien le noise, avec au moins deux usages: bruitages courts
  et piste rhythmique/noise liee au morceau.

### DMC / Raw DAC

- `out/smb/smb.asm:23`: au boot, le code ecrit dans `APU_DMC_RAW`.
- `out/smb/smb.asm:4036`: chaque frame, le moteur ecrit `STY APU_DMC_RAW`.

Conclusion:

- SMB n'utilise pas ici un playback DMC sample complet visible via
  `$4010-$4013`; il module surtout le registre raw DAC `$4011`.
- Dans qlnes, le DMC reste un stub, donc ce signal raw doit rester `unverified`
  tant que le moteur SMB n'est pas implemente avec reference.

## Music Data Shape

- `out/smb/smb.asm:4420-4433`: `L_F90C` sert de table de selection de morceau:
  le moteur charge une longueur, un pointeur de donnees (`ptr4_lo/ptr4_hi`) et
  des offsets de canaux (`zp_F9`, `zp_F8`, `arg_pre_jsr_07B0`).
- `out/smb/smb.asm:4451-4488`: lecture de la voix pulse 2.
- `out/smb/smb.asm:4501-4539`: lecture de la voix pulse 1.
- `out/smb/smb.asm:4540-4576`: lecture de la voix triangle.
- `out/smb/smb.asm:4577-4616`: lecture noise.
- `out/smb/smb.asm:4665+`: grosses tables de donnees musicales.
- `out/smb/smb.asm:4882+`: table de periodes autour de `L_FF00/L_FF65`.

Interpretation:

- Chaque morceau pointe vers un bloc compact custom.
- Les voix ont des offsets separes dans le meme bloc, pas cinq pointeurs
  FamiTone2 independants.
- Les bytes `0x80+` semblent porter des controles de duree/octave/enveloppe;
  les bytes bas representent des notes ou silences selon le canal.

## qlnes Test Result

Commande 90 frames:

```bash
.venv/bin/python -m qlnes audio "roms/Super Mario Bros. (World).nes" -o _bmad-output/audio-validation/smb-tracks --format wav --frames 90 --engine-mode auto --force --bilan _bmad-output/audio-validation/smb-bilan.json --color never
```

Resultat:

- Exit: `0`
- Engine: `unknown`
- Tier: `2`
- Status: `unverified`
- WAV: `_bmad-output/audio-validation/smb-tracks-10s/Super Mario Bros. (World).00.unknown.wav`
- Duration: `9.983537 s`
- Peak-to-peak amplitude: `0`
- Sample range: `-16384..-16384`
- WAV: `_bmad-output/audio-validation/smb-tracks/Super Mario Bros. (World).00.unknown.wav`
- Duration: `1.497528 s`
- Peak-to-peak amplitude: `0`
- Dominant frequency: `0.000 Hz`

Commande 600 frames:

```bash
.venv/bin/python -m qlnes audio "roms/Super Mario Bros. (World).nes" -o _bmad-output/audio-validation/smb-tracks-10s --format wav --frames 600 --engine-mode auto --force --bilan _bmad-output/audio-validation/smb-10s-bilan.json --color never
```

Resultat:

- Exit: `0`
- Engine: `unknown`
- Tier: `2`
- Status: `unverified`

Interpretation:

- Le fallback generique boote la ROM sans script d'input ni selection de song.
- Sur SMB, ce chemin ne declenche pas encore une musique audible dans la fenetre
  testee. Ce n'est pas une preuve que le moteur SMB ne marche pas; c'est une
  preuve que qlnes n'a pas encore de handler SMB capable d'appeler le moteur
  avec les bons flags/song ids.

## Implementation Notes for a SMB Handler

Pour supporter SMB proprement, il faut un engine dedie, par exemple
`smb_custom`, avec:

1. Detection:
   - mapper 0
   - presence du call `JSR L_F2D0` depuis la routine frame
   - presence des tables `L_F90C` et `L_FF00/L_FF01`
   - ecritures APU groupees `APU_PULSE1/2`, `APU_TRI`, `APU_NOISE`,
     `APU_DMC_RAW`

2. Song enumeration:
   - parser `L_F90C` comme table de selection
   - extraire pour chaque entree: longueur/timing, pointeur donnees, offsets
     pulse1/pulse2/triangle/noise
   - ignorer les sentinelles avec evidence en bilan

3. Render path:
   - initialiser les RAM flags equivalentes a un song id
   - appeler `L_F2D0` une fois par frame, ou appeler la routine NMI qui appelle
     `L_F2D0`
   - capturer les ecritures APU produites et rendre via l'APU qlnes

4. Verification:
   - fixture SMB legalement non redistribue dans le repo; utiliser seulement
     une ROM locale utilisateur ou un hash connu dans un manifest prive
   - comparer contre FCEUX pour quelques songs connues
   - garder `unverified` jusqu'a ce qu'une reference FCEUX confirme les
     frequences/PCM

## Conclusion

SMB est un bon candidat Epic 2/Epic 6 pour elargir qlnes au-dela de
FamiTracker/FamiTone2. L'ASM contient assez d'informations pour demarrer un
handler custom: entrypoint `L_F2D0`, scheduler frame, tables de songs, table de
periodes, et routage pulse/pulse/triangle/noise. Le test actuel avec `qlnes
audio` reste correctement marque `unknown/unverified` et produit du silence
sans input/song initialization specifique.
