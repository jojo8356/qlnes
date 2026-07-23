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

`oam-screen.png` est un canvas transparent 256x240 avec les sprites replacés à
leurs coordonnées écran. Les sprites de plus petit index OAM sont composés
devant ceux de plus grand index, comme sur la NES. La priorité devant/derrière
le background est conservée dans le manifeste, mais le PNG reste volontairement
sprite-only avec fond transparent.

Les sprites masques hors ecran (`Y >= 0xEF`) sont ignores par defaut. Ajouter
`--include-hidden` pour les exporter aussi.

## Mode runtime automatique NROM/MMC1/UxROM/CNROM/MMC3/GxROM

Pour les ROMs mapper 0/NROM, mapper 1/MMC1 simple, mapper 2/UxROM, mapper
3/CNROM, mapper 4/MMC3 simple et mapper 66/GxROM qui initialisent les palettes
et OAM par les writes PPU classiques, qlnes peut faire le snapshot
automatiquement :

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
- les writes serie mapper 1/MMC1 vers `$8000-$FFFF` pour choisir les PRG banks
  et composer les fenêtres CHR 8 KiB ou split 4 KiB visibles dans les cas
  simples ;
- les writes mapper 2/UxROM vers `$8000-$FFFF` pour choisir la PRG bank basse ;
- les writes mapper 3/CNROM vers `$8000-$FFFF` pour choisir le CHR bank actif ;
- les writes mapper 4/MMC3 vers `$8000/$8001` pour choisir les PRG banks et
  composer les fenêtres CHR 1 KiB/2 KiB visibles dans le snapshot ;
- les writes mapper 66/GxROM vers `$8000-$FFFF` pour choisir la PRG bank 32 KiB
  et le CHR bank actif.

Ensuite il exporte les sprites OAM comme le mode `--snapshot`, avec
`palette_source: runtime-snapshot` et `snapshot: in-process` dans le manifeste.

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
NROM/MMC1/UxROM/CNROM/MMC3/GxROM simples, y compris une partie des ROMs CHR-RAM
si les tiles sont ecrites via `PPUDATA` pendant la fenetre capturee. Elle ne
couvre pas encore tous les jeux NES :

- variantes mapper complexes : le snapshot doit contenir le CHR bank actif ou
  les pattern tables runtime.
- Effets mid-frame : les changements palette/CHR pendant le rendu demandent un
  oracle PPU plus precis.

Dans l'environnement local actuel, FCEUX Qt est installe mais crashe avant de
produire le dump PPU/OAM en mode offscreen. Le chemin `--snapshot` reste donc
le point d'integration pour un dump externe fiable FCEUX/Mesen.
