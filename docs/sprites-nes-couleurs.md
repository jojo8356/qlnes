# Sprites NES couleurs et transparence

`qlnes sprites` extrait les tiles d'une pattern table CHR en PNG RGBA. L'index
couleur NES `0` est exporte avec alpha `0`, donc transparent.

```bash
python -m qlnes sprites ROM.nes \
  -o out/sprites \
  --pattern-table 1 \
  --palette 0F,30,16,27
```

Sorties :

- `spritesheet-pt1-pal0.png` : spritesheet RGBA ;
- `tiles/*.png` : un PNG transparent par tile ;
- `sprites-manifest.json` : provenance, palette PPU, pattern table, CHR bank.

## Couleurs originales

Une tile CHR NES ne contient pas de RGB. Elle contient des indices `0..3`.
Pour avoir les couleurs originales strictes d'un jeu, il faut fournir une
palette RAM issue du runtime PPU du jeu au moment capture. Sans palette runtime,
`qlnes sprites` applique une palette de preview explicite et l'indique dans le
manifeste.

## Mode runtime snapshot

Pour exporter les sprites OAM avec les palettes originales capturees pendant le
jeu, utiliser `--snapshot` :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-sprites \
  --snapshot snapshot-ppu-oam.json
```

Format minimal du snapshot :

```json
{
  "frame": 123,
  "chr_bank": 0,
  "ppuctrl": "0x08",
  "ppumask": "0x1E",
  "palette_ram": [
    "0x0F", "0x30", "0x21", "0x11",
    "0x0F", "0x16", "0x27", "0x18",
    "0x0F", "0x09", "0x19", "0x29",
    "0x0F", "0x06", "0x17", "0x28",
    "0x0F", "0x30", "0x16", "0x27",
    "0x0F", "0x30", "0x12", "0x21",
    "0x0F", "0x30", "0x1A", "0x2A",
    "0x0F", "0x30", "0x10", "0x20"
  ],
  "oam": ["256 valeurs 0x00..0xFF"]
}
```

Dans ce mode, qlnes :

- lit les 64 entrees OAM ;
- applique la sous-palette sprite de chaque sprite (`attr & 0x03`) ;
- respecte le mode 8x8 ou 8x16 depuis `PPUCTRL` ;
- applique les flips horizontal/vertical OAM ;
- ecrit `oam-spritesheet.png`, `oam-screen.png` et `oam/sprite-XX-*.png`
  en RGBA transparent.

Le chemin snapshot/runtime est testé avec un sprite 8x16 en double flip
horizontal/vertical pour vérifier les pixels PNG individuels et leur placement
dans `oam-screen.png`.

`oam-screen.png` est un canvas transparent 256x240 avec les sprites replacés à
leurs coordonnées écran. Les sprites de plus petit index OAM sont composés
devant ceux de plus grand index, comme sur la NES. La priorité devant/derrière
le background est conservée dans le manifeste, mais le PNG reste volontairement
sprite-only avec fond transparent.

Les sprites masques hors ecran (`Y >= 0xEF`) sont ignores par defaut. Ajouter
`--include-hidden` pour les exporter aussi.

## Mode runtime automatique NROM/MMC1/UxROM/CNROM/MMC3/MMC5/AxROM/MMC2/MMC4/Color Dreams/CPROM/Bandai FCG/Jaleco SS88006/Namco 163/VRC2-VRC4/VRC6/Irem G-101/Taito TC0190/BNROM/Mapper 42/GxROM/FME-7/Bandai/Camerica/JF-17/Holy Diver/NINA-03-06/J87/JF-10/Namco 108

Pour les ROMs mapper 0/NROM, mapper 1/MMC1 simple, mapper 2/UxROM, mapper
3/CNROM, mapper 4/MMC3 simple, mapper 5/MMC5 simple, mapper 7/AxROM, mapper 9/MMC2, mapper
10/MMC4, mapper 11/Color Dreams, mapper 13/CPROM, mapper 16/Bandai FCG,
mapper 18/Jaleco SS88006, mapper 19/Namco 129-163, mapper 21/22/23/25/VRC2-VRC4, mapper 24-26/VRC6,
mapper 32/Irem G-101, mapper 33/Taito TC0190,
mapper 34/BNROM-NINA,
mapper 42/FDS conversions, mapper 66/GxROM,
mapper 69/Sunsoft FME-7/5B, mapper 70/Bandai, mapper 71/Camerica, mapper
72/JF-17, mapper 78/Holy Diver, mapper 79/NINA-03-06, mapper 87/J87, mapper
101/JF-10 et mapper 206/Namco 108 qui initialisent les palettes et OAM par les
writes PPU classiques, qlnes peut faire le snapshot automatiquement :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-sprites \
  --runtime-frames 120
```

Ce mode boote la ROM en-process avec `py65`, observe :

- `PPUCTRL` et `PPUMASK` ;
- les writes pattern table `$0000-$1FFF` utiles aux ROMs CHR-RAM simples ;
- `PPUADDR` + `PPUDATA` pour la palette RAM `$3F00-$3F1F` ;
- `OAMADDR` + `OAMDATA` ;
- `OAMDMA` `$4014` pour copier la page CPU vers OAM ;
- la PRG-RAM cartouche `$6000-$7FFF`, utile quand l'init prépare les buffers
  OAM ou palette hors RAM interne avant de déclencher `OAMDMA` ;
- les writes serie mapper 1/MMC1 vers `$8000-$FFFF` pour choisir les PRG banks
  et composer les fenêtres CHR 8 KiB ou split 4 KiB visibles dans les cas
  simples ;
- les writes mapper 2/UxROM vers `$8000-$FFFF` pour choisir la PRG bank basse ;
- les writes mapper 3/CNROM vers `$8000-$FFFF` pour choisir le CHR bank actif ;
- les writes mapper 4/MMC3 vers `$8000/$8001` pour choisir les PRG banks et
  composer les fenêtres CHR 1 KiB/2 KiB visibles dans le snapshot ;
- les writes mapper 5/MMC5 vers `$5100/$5101`, `$5114-$5117`,
  `$5120-$512B` et `$5130` pour choisir les modes PRG/CHR, les banques PRG et
  les fenêtres CHR sprite visibles dans le snapshot ;
- les writes mapper 7/AxROM vers `$8000-$FFFF` pour choisir la PRG bank 32 KiB ;
- les writes mapper 9/MMC2 vers `$A000-$EFFF` pour choisir la PRG bank 8 KiB
  basse et les deux fenêtres CHR-ROM 4 KiB latchées visibles dans le snapshot ;
- les writes mapper 10/MMC4 vers `$A000-$EFFF` pour choisir la PRG bank 16 KiB
  basse et les deux fenêtres CHR-ROM 4 KiB latchées visibles dans le snapshot ;
- les writes mapper 11/Color Dreams vers `$8000-$FFFF` pour choisir la PRG bank
  32 KiB via bits `0-1` et le CHR bank 8 KiB via bits `4-7` ;
- les writes mapper 13/CPROM vers `$8000-$FFFF` pour choisir la page CHR-RAM
  4 KiB visible en PPU `$1000-$1FFF` ;
- les writes mapper 16/Bandai FCG vers `$6000-$6008` ou `$8000-$8008` pour
  choisir les huit fenêtres CHR-ROM 1 KiB et la PRG bank 16 KiB basse ;
- les writes mapper 18/Jaleco SS88006 vers `$8000-$D003` pour choisir les
  fenêtres PRG 8 KiB et les huit fenêtres CHR-ROM 1 KiB par paires de nibbles ;
- les writes mapper 19/Namco 129-163 vers `$8000-$BFFF/$E000-$F000` pour
  choisir les fenêtres PRG 8 KiB et les huit fenêtres CHR-ROM 1 KiB ;
- les writes mapper 21/22/23/25/VRC2-VRC4 vers `$8000/$9002/$A000` et
  `$B000-$E003` pour choisir les fenêtres PRG 8 KiB et les huit fenêtres
  CHR-ROM 1 KiB par paires de nibbles ;
- les writes mapper 24/26/VRC6 vers `$8000/$B003/$C000/$D000-$D003/$E000-$E003`
  pour choisir les fenêtres PRG 16/8 KiB et les huit fenêtres CHR-ROM 1 KiB ;
- les writes mapper 32/Irem G-101 vers `$8000/$9000/$A000/$B000-$B007` pour
  choisir les fenêtres PRG 8 KiB et les huit fenêtres CHR-ROM 1 KiB ;
- les writes mapper 33/Taito TC0190 vers `$8000-$8003/$A000-$A003` pour
  choisir les fenêtres PRG 8 KiB et les fenêtres CHR-ROM 2 KiB/1 KiB ;
- les writes mapper 34/BNROM vers `$8000-$FFFF` pour choisir la PRG bank 32 KiB
  ou, en mode NINA, `$7FFD/$7FFE/$7FFF` pour choisir PRG 32 KiB et deux
  fenêtres CHR 4 KiB ;
- les writes mapper 42 vers `$8000` pour choisir la CHR-ROM 8 KiB active, et
  vers `$E000` pour choisir la PRG-ROM 8 KiB visible en CPU `$6000-$7FFF` ;
- les writes mapper 66/GxROM vers `$8000-$FFFF` pour choisir la PRG bank 32 KiB
  et le CHR bank actif ;
- les writes mapper 69/FME-7 vers `$8000-$9FFF` puis `$A000-$BFFF` pour choisir
  les fenêtres PRG 8 KiB `$8000/$A000/$C000` et les fenêtres CHR 1 KiB visibles
  dans le snapshot ;
- les writes mapper 70/Bandai vers `$8000-$FFFF` pour choisir la PRG bank 16
  KiB basse via bits `4-7` et la CHR-ROM 8 KiB active via bits `0-3` ;
- les writes mapper 71/Camerica vers `$C000-$FFFF` pour choisir la PRG bank 16
  KiB basse, avec la dernière bank fixe en haut.
- les writes mapper 72/JF-17 vers `$8000-$FFFF` : bit `7` montant choisit la
  PRG bank 16 KiB basse et bit `6` montant choisit la CHR-ROM 8 KiB active,
  avec le numero de bank dans les bits `0-3` ;
- les writes mapper 78/Holy Diver vers `$8000-$FFFF` pour choisir la PRG bank
  16 KiB basse via bits `0-2` et la CHR-ROM 8 KiB active via bits `4-7` ;
- les writes mapper 79/NINA-03-06 vers `$4100-$5FFF` pour choisir la PRG bank
  32 KiB via bit `3` et la CHR-ROM 8 KiB active via bits `0-2` ;
- les writes mapper 87/J87 vers `$6000-$7FFF` pour choisir la CHR-ROM 8 KiB
  active avec le bit-order `LH` documenté par NESdev.
- les writes mapper 101/JF-10 vers `$6000-$7FFF` pour choisir la CHR-ROM 8 KiB
  active avec le bit-order normal `HL`.
- les writes mapper 206/Namco 108 vers `$8000/$8001` pour choisir les PRG banks
  et les fenêtres CHR 1 KiB/2 KiB, sans les bits de mode MMC3.

Ensuite il exporte les sprites OAM comme le mode `--snapshot`, avec
`palette_source: runtime-snapshot` et `snapshot: in-process` dans le manifeste.
Chaque entrée `sprites[]` contient aussi `palette_ppu` et `palette_rgba`, pour
retracer les quatre couleurs NES utilisées par le PNG exporté.

Pour les ROMs CHR-RAM simples (`chr_banks = 0` dans l'en-tête iNES), il n'y a
pas de CHR-ROM statique à extraire. Le mode runtime capture donc les writes
`PPUDATA` vers `$0000-$1FFF` et exporte les sprites depuis cette pattern table
VRAM capturée. Le manifeste écrit alors `chr_ram: true`, `chr_source:
snapshot`, et conserve une note `CHR-RAM runtime export`. C'est le chemin à
utiliser pour obtenir les PNG RGBA transparents avec couleurs runtime sur les
jeux qui chargent leurs sprites au boot.

Pour capturer plusieurs moments runtime, utiliser `--runtime-sample-frames`.
qlnes reboote la ROM pour chaque checkpoint et écrit un sous-dossier par frame :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-samples \
  --runtime-sample-frames 1,30,60,120
```

La forme plage évite de lister les frames une par une :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-samples \
  --runtime-sample-range 1:300:30
```

Pour atteindre plus d'états de jeu, ajouter des inputs manette 1 pendant la
capture runtime :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-samples \
  --runtime-sample-range 1:600:30 \
  --runtime-input start@1:30,a+right@120:240
```

Syntaxe `--runtime-input` :

- les frames sont 1-based ;
- `button@frame` presse un bouton sur une frame ;
- `button@start:end` presse un bouton sur une plage inclusive ;
- plusieurs boutons se combinent avec `+` ;
- plusieurs entrées se séparent par virgule ou espace ;
- boutons acceptés : `a`, `b`, `select`, `start`, `up`, `down`, `left`,
  `right`.

Exemples :

- `start@1:30` : maintenir Start sur les 30 premières frames ;
- `a+right@120:240` : maintenir A et Droite sur les frames 120 à 240 ;
- `start@1:20,a@80,b@100:110` : séquence menu puis deux actions.

Chaque sous-dossier `frame-000120/` contient les mêmes PNG OAM transparents que
`--runtime-frames`. Le manifeste `runtime-sprite-samples-manifest.json` liste
toutes les frames capturées, leurs manifestes locaux, et un dossier `unique/`
qui déduplique les PNG RGBA finaux par hash SHA-256. Une spritesheet
`unique-spritesheet.png` regroupe aussi ces sprites uniques. Le dossier
`unique-trimmed/` et `unique-trimmed-spritesheet.png` fournissent les mêmes
sprites recadrés sur leur bbox alpha, en conservant la transparence. Les
entrées `unique_sprites[]` du manifeste incluent aussi les coordonnées d'atlas
`sheet` et `trimmed_sheet` pour lire directement les spritesheets. Ce mode ne
garantit pas tous les sprites d'un jeu complet, mais il couvre mieux les
animations et états de boot/titre qu'une seule capture finale.

## Mode batch multi-ROM

Pour traiter une collection locale, `sprites-batch` cherche les fichiers `.nes`
dans un dossier, crée un sous-dossier de sortie par ROM, et écrit un manifeste
global `sprites-batch-manifest.json` :

```bash
python -m qlnes sprites-batch roms/ \
  -o out/sprites-batch \
  --recursive \
  --runtime-sample-range 1:300:30
```

`--runtime-input` est aussi disponible en batch. Le même script d'input est
appliqué à chaque ROM :

```bash
python -m qlnes sprites-batch roms/ \
  -o out/sprites-batch \
  --recursive \
  --runtime-sample-range 1:600:30 \
  --runtime-input start@1:30,a+right@120:240
```

Le batch continue quand une ROM échoue, enregistre l'erreur dans le manifeste
global, puis retourne un code non-zero s'il y a au moins un échec. Ajouter
`--allow-failures` pour conserver un code retour `0` dans les pipelines qui
acceptent les ROMs non supportées.

En mode `--runtime-frames` ou `--runtime-sample-*`, le batch produit aussi
`all-unique-trimmed/` et `all-unique-trimmed-spritesheet.png` à la racine de
sortie. Le fichier
`all-unique-trimmed-atlas.json` fournit un atlas dédié avec la spritesheet, les
coordonnées `sheet`, la provenance ROM et les hashes. Ces fichiers dédupliquent
les sprites recadrés de toutes les ROMs traitées par `trimmed_sha256`.

La forme courte `--palette 0F,30,16,27` applique une sous-palette sprite de 4
valeurs PPU sur les quatre palettes sprite.

La forme complete accepte 32 valeurs PPU, correspondant a la palette RAM
`$3F00-$3F1F` :

```bash
python -m qlnes sprites ROM.nes \
  -o out/sprites-runtime \
  --palette "0F,30,21,11,0F,16,27,18,0F,09,19,29,0F,06,17,28,0F,30,16,27,0F,30,12,21,0F,30,1A,2A,0F,30,10,20"
```

## Options utiles

- `--pattern-table 0|1` : choisit `$0000` ou `$1000`.
- `--chr-bank N` : choisit la banque CHR-ROM 8 KiB.
- `--sprite-height 8|16` : decode en mode sprite 8x8 ou 8x16.
- `--palette-id 0..3` : choisit la sous-palette sprite.
- `--no-tiles` : ecrit seulement la spritesheet.

## Limite actuelle

La commande sait capturer automatiquement les cas
NROM/MMC1/UxROM/CNROM/MMC3/MMC5/AxROM/MMC2/MMC4/Color Dreams/CPROM/Bandai FCG/Jaleco SS88006/Namco 163/VRC2-VRC4/VRC6/Irem G-101/Taito TC0190/BNROM/Mapper 42/GxROM/FME-7/Bandai/Camerica/JF-17/Holy Diver/NINA-03-06/J87/JF-10/Namco 108
simples, y compris une partie des ROMs CHR-RAM si les tiles sont ecrites via
`PPUDATA` pendant la fenetre capturee.
Elle ne couvre pas encore tous les jeux NES :

- variantes mapper complexes : le snapshot doit contenir le CHR bank actif ou
  les pattern tables runtime.
- Effets mid-frame : les changements palette/CHR pendant le rendu demandent un
  oracle PPU plus precis.

Dans l'environnement local actuel, FCEUX Qt est installe mais crashe avant de
produire le dump PPU/OAM en mode offscreen. Le chemin `--snapshot` reste donc
le point d'integration pour un dump externe fiable FCEUX/Mesen.
