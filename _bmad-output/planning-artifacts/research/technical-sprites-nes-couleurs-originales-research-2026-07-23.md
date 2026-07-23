---
stepsCompleted: [1]
inputDocuments:
  - README.md
  - qlnes/assets.py
  - qlnes/ines.py
  - _bmad-output/planning-artifacts/prd.md
workflowType: 'research'
lastStep: 1
research_type: 'technical'
research_topic: 'sprites NES en couleurs originales depuis les ROMs'
research_goals: 'Comprendre comment extraire les sprites NES avec leurs couleurs originales, identifier les limites de la CHR brute, et definir une approche implementable dans qlnes.'
user_name: 'Johan'
date: '2026-07-23'
web_research_enabled: true
source_verification: true
---

# Research Report: sprites NES en couleurs originales depuis les ROMs

**Date:** 2026-07-23  
**Author:** Johan  
**Research Type:** technical

---

## Research Overview

Cette note repond a une question precise : comment passer de `CHR-ROM -> PNG
gris/indices` a `sprites NES avec les couleurs originales du jeu`.

Conclusion courte : les couleurs originales ne sont pas dans les tiles CHR
seules. Une tile NES stocke uniquement des indices 2bpp `0..3`. Pour obtenir
les vraies couleurs d'un sprite, il faut connaitre au meme instant :

- la tile CHR visible par le PPU ;
- l'entree OAM du sprite : position, tile index, attributs, flip, palette ;
- la palette RAM sprite `$3F10-$3F1F` ;
- les bits PPUCTRL/PPUMASK : taille sprite, pattern table, emphasis/greyscale ;
- le mapper/CHR bank courant si le jeu bankswitche la CHR ;
- pour une sortie RGB, le profil palette/emulateur choisi.

Donc il existe trois niveaux d'extraction :

1. **CHR brute** : ce que qlnes fait deja dans `qlnes/assets.py`.
2. **Sprites colores par snapshot PPU/OAM** : cible correcte pour qlnes.
3. **Rendu final frame-perfect** : necessite un PPU complet ou un oracle
   emulateur, utile pour les jeux a raster effects, bankswitch mid-frame, ou
   palettes changees pendant l'image.

## Sources verifiees

Sources principales :

- NESdev, PPU memory map : https://www.nesdev.org/wiki/PPU_memory_map
- NESdev, PPU pattern tables : https://www.nesdev.org/wiki/PPU_pattern_tables
- NESdev, PPU palettes : https://www.nesdev.org/wiki/PPU_palettes
- NESdev, PPU OAM : https://www.nesdev.org/wiki/PPU_OAM
- NESdev, List of mappers : https://www.nesdev.org/wiki/List_of_mappers
- NESdev, MMC5 : https://www.nesdev.org/wiki/MMC5
- NESdev, INES Mapper 016 : https://www.nesdev.org/wiki/INES_Mapper_016
- NESdev, INES Mapper 018 : https://www.nesdev.org/wiki/INES_Mapper_018
- NESdev, INES Mapper 019 : https://www.nesdev.org/wiki/INES_Mapper_019
- NESdev, INES Mapper 032 : https://www.nesdev.org/wiki/INES_Mapper_032
- NESdev, INES Mapper 033 : https://www.nesdev.org/wiki/INES_Mapper_033
- NESdev, INES Mapper 042 : https://www.nesdev.org/wiki/INES_Mapper_042
- NESdev, MMC4 / mapper 010 : https://www.nesdev.org/wiki/MMC4
- NESdev, INES Mapper 070 : https://www.nesdev.org/wiki/INES_Mapper_070
- NESdev, INES Mapper 072 : https://www.nesdev.org/wiki/INES_Mapper_072
- NESdev, INES Mapper 079 / NINA-003-006 : https://www.nesdev.org/wiki/INES_Mapper_079
- NESdev, PPU programmer reference : https://www.nesdev.org/wiki/PPU_programmer_reference
- NESdev, PPU rendering : https://www.nesdev.org/wiki/PPU_rendering
- NESdev, CHR-ROM vs CHR-RAM : https://www.nesdev.org/wiki/CHR-ROM_vs_CHR-RAM
- NESdev, PPU attribute tables : https://www.nesdev.org/wiki/PPU_attribute_tables
- NESdev, MMC3 : https://www.nesdev.org/wiki/MMC3
- NESdev, Programming MMC3 : https://www.nesdev.org/wiki/Programming_MMC3
- FCEUX, PPU Viewer : https://fceux.com/web/help/PPUViewer.html
- FCEUX, Name Table Viewer : https://fceux.com/web/help/NameTableViewer.html
- FCEUX, Palette config : https://fceux.com/web/help/Palette.html

Verification web faite le 2026-07-23. Les points importants confirmes :

- les tiles/pattern tables sont du 2bpp et produisent seulement des indices
  `0..3`, pas des couleurs finales ;
- les sprites sont decrits par 64 entrees OAM de 4 octets ;
- la palette RAM PPU `$3F00-$3F1F` stocke des valeurs couleur 6 bits ;
- pour les sprites, l'index graphique `0` est transparent ;
- FCEUX PPU Viewer affiche l'etat PPU courant et permet d'inspecter les
  pattern tables avec les palettes runtime, mais les jeux qui changent CHR ou
  palette mid-frame demandent un choix de scanline ou un rendu PPU plus fin ;
- le Code/Data Logger de FCEUX ne peut masquer les tiles utilisees que pour
  CHR-ROM, car il observe les acces CHR-ROM, pas les copies dynamiques CHR-RAM.

## Chemin exact "ROM NES -> PNG sprites couleurs"

Le chemin fiable n'est pas un convertisseur direct de fichier `.nes` vers
`sprites.png`. C'est un pipeline d'observation :

1. Parser l'en-tete iNES pour connaitre PRG, CHR et mapper.
2. Booter la ROM ou charger un snapshot externe pour obtenir l'etat PPU/OAM.
3. Reconstituer la pattern table visible `$0000-$1FFF` :
   - CHR-ROM fixe : lire la banque CHR du fichier ;
   - CHR-ROM bankswitchee : appliquer les registres mapper captures ;
   - CHR-RAM : utiliser les bytes ecrits a runtime par `PPUDATA`.
4. Lire OAM pour savoir quels sprites sont visibles, leur tile, palette,
   position, priorite et flips.
5. Lire palette RAM `$3F10-$3F1F` pour les quatre sous-palettes sprite.
6. Decoder chaque tile 2bpp : index `0` transparent, index `1..3` opaques.
7. Convertir les valeurs palette PPU 6 bits en RGBA avec un profil declare.
8. Ecrire PNG + JSON de provenance.

La transparence ne vient donc pas d'un canal alpha stocke dans la ROM. Elle
vient de la convention PPU : pour les sprites, le pixel CHR d'index `0` ne
dessine rien. qlnes mappe cet index vers alpha `0` dans les PNG.

## Ce que qlnes fait aujourd'hui

`qlnes/assets.py` extrait :

- `chr_rom.chr` : bytes CHR bruts ;
- `chr_rom.asm` : representation reassemblable ;
- `chr_tiles.png` : grille complete des tiles ;
- `pattern_table_bg.png` : pattern table 0 ;
- `pattern_table_spr.png` : pattern table 1.

Ce rendu utilise une palette par defaut de 4 niveaux. C'est utile pour voir les
formes, mais ce n'est pas une extraction des couleurs originales. La raison est
structurelle : la CHR n'a pas les couleurs finales.

## Modele hardware minimal

### Pattern tables / CHR

Le PPU adresse `$0000-$1FFF` pour les pattern tables. Ces 8 KiB sont fournis
par la cartouche : CHR-ROM, CHR-RAM, ou banks CHR via mapper.

Une tile fait 16 octets :

- octets `0..7` : bitplane bas ;
- octets `8..15` : bitplane haut ;
- chaque pixel devient `color_index = bit0 | (bit1 << 1)`.

Le resultat est un index `0..3`, pas une couleur RGB.

### OAM sprite

La NES a 256 octets d'OAM primaire : 64 sprites, 4 octets par sprite.

| Octet | Champ | Impact couleur/sprite |
|---:|---|---|
| 0 | Y | position verticale, avec decalage hardware d'une scanline |
| 1 | tile index | tile a dessiner |
| 2 | attributes | palette, priorite, flip horizontal, flip vertical |
| 3 | X | position horizontale |

Attribut sprite, octet 2 :

```text
76543210
||||||++- palette sprite 0..3, exposee comme palettes 4..7 cote PPU
|||+++--- bits non implementes
||+------ priorite: 0 devant background, 1 derriere background
|+------- flip horizontal
+-------- flip vertical
```

Les deux bits de palette ne donnent pas une couleur. Ils choisissent l'une des
quatre sous-palettes sprite dans `$3F10-$3F1F`.

### Palette RAM

Le PPU a 32 octets de palette RAM indexes a `$3F00-$3F1F` :

- `$3F00-$3F0F` : palettes background ;
- `$3F10-$3F1F` : palettes sprite.

Les sprites utilisent quatre palettes de trois couleurs visibles. Leur index
pixel `0` est transparent. Les index `1..3` se resolvent dans :

```text
palette_base = $3F10 + sprite_palette_index * 4
pixel 0 -> transparent
pixel 1 -> PPU palette RAM[palette_base + 1]
pixel 2 -> PPU palette RAM[palette_base + 2]
pixel 3 -> PPU palette RAM[palette_base + 3]
```

Important : les entrees universelles/mirroirs comme `$3F10`, `$3F14`,
`$3F18`, `$3F1C` ne doivent pas etre traitees comme des couleurs opaques de
sprite. Pour un sprite, l'index CHR `0` signifie transparent.

### PPUCTRL

Deux bits sont critiques :

- bit 3 : pattern table des sprites 8x8 (`$0000` ou `$1000`) ;
- bit 5 : taille sprite (`0 = 8x8`, `1 = 8x16`).

En mode 8x16, le bit 0 du tile index choisit la pattern table, et le reste du
numero choisit la paire de tiles. On ne peut donc pas prendre simplement
`sprite_pattern_table_base + tile_index * 16` dans ce mode.

### PPUMASK

PPUMASK influence la sortie couleur :

- bit 0 : greyscale ;
- bits 5, 6, 7 : color emphasis/tint.

Pour une extraction "indices originaux", on peut stocker les valeurs palette
PPU brutes et ignorer le RGB. Pour une extraction "PNG comme l'utilisateur le
voit", il faut appliquer greyscale/emphasis avec un profil palette compatible.

## Pourquoi "couleur originale" est ambigu sur NES

La NES ne stocke pas des couleurs RGB fixes. Les valeurs palette sont des codes
6 bits qui deviennent un signal video analogique. Deux emulateurs peuvent
afficher des RGB legerement differents selon leur palette, leur simulation NTSC,
PAL/Dendy, ou leur profil TV.

Recommandation qlnes :

- conserver les **indices PPU bruts** comme verite technique ;
- produire un PNG avec un profil explicite, par exemple `nesdev-default`,
  `fceux-default`, `nestopia-rgb`, ou `ntsc-emulated` ;
- ecrire un sidecar JSON qui contient les valeurs PPU, les attributs OAM, le
  mapper, la frame, et le profil de conversion RGB.

Un fichier PNG seul n'est pas une preuve complete de couleur originale. Le JSON
doit etre la source de verite.

## Algorithme correct pour extraire les sprites colores

### Entrees necessaires

Pour une frame donnee :

- `ppu_chr[0x0000:0x2000]` : pattern tables visibles a cette frame ;
- `oam[256]` : OAM primaire ;
- `palette_ram[32]` : palette RAM `$3F00-$3F1F` ;
- `ppuctrl` : sprite size + pattern table ;
- `ppumask` : greyscale/emphasis ;
- `mapper_state` : bank CHR courant ;
- `frame_number` ou evenement de capture.

### Pipeline sprite

Pour chaque sprite `i` de `0..63` :

1. Lire `y, tile, attr, x = oam[i*4:i*4+4]`.
2. Ignorer les sprites masques hors ecran si `y >= $EF`, mais garder l'entree
   dans le JSON pour audit.
3. Calculer le mode :
   - 8x8 : base = `$1000` si `PPUCTRL bit 3 = 1`, sinon `$0000`.
   - 8x16 : base = `$1000` si `tile & 1`, sinon `$0000`; tile paire =
     `tile & $FE`.
4. Decoder les tile(s) 2bpp en indices `0..3`.
5. Appliquer flip H/V avant ou pendant la composition.
6. Pour chaque pixel :
   - si index `0`, pixel transparent ;
   - sinon palette = `attr & 0x03`;
   - valeur PPU = `palette_ram[0x10 + palette*4 + index] & 0x3F`;
   - RGB = lookup `ppu_value` dans le profil palette choisi, puis appliquer
     greyscale/emphasis si le mode de sortie le demande.
7. Sortir :
   - une image par sprite ;
   - une spritesheet packee ;
   - un JSON de provenance.

### Pseudo-code

```python
def sprite_palette_value(palette_ram, attr, color_index):
    if color_index == 0:
        return None  # transparent
    palette_id = attr & 0x03
    return palette_ram[0x10 + palette_id * 4 + color_index] & 0x3F


def sprite_tile_addr(ppuctrl, tile_index, row, sprite_height):
    if sprite_height == 8:
        base = 0x1000 if (ppuctrl & 0x08) else 0x0000
        return base + tile_index * 16 + row

    base = 0x1000 if (tile_index & 0x01) else 0x0000
    top_tile = tile_index & 0xFE
    tile_row = row // 8
    fine_y = row % 8
    return base + (top_tile + tile_row) * 16 + fine_y
```

## Backgrounds colores : meme probleme, autre source d'attributs

Pour les backgrounds, il ne faut pas utiliser OAM. Il faut :

- nametable `$2000-$2FFF` : tile index par cellule 8x8 ;
- attribute table `$23C0/$27C0/$2BC0/$2FC0` : choix de sous-palette par zone
  16x16 ;
- palette RAM `$3F00-$3F0F` ;
- PPUCTRL bit 4 : pattern table background ;
- scroll et mirroring pour savoir quelle nametable est visible.

Chaque byte d'attribute table couvre 32x32 pixels, divise en quatre zones
16x16. Les deux bits de quadrant choisissent une des quatre palettes background.

## CHR-ROM, CHR-RAM et mappers

### CHR-ROM simple

Pour NROM et autres cas simples sans bankswitch CHR pendant la frame, la CHR
dans le fichier `.nes` suffit pour les formes. Il faut quand meme capturer
OAM/palette RAM a runtime pour les couleurs.

### CHR-RAM

Si `chr_banks == 0`, la ROM ne contient pas directement la pattern table. Le
jeu copie ou genere des tiles dans la VRAM PPU pendant l'init/vblank. Dans ce
cas, une extraction statique depuis le fichier `.nes` ne peut pas reconstruire
les sprites. Il faut executer le jeu jusqu'a une frame et dumper la VRAM PPU.

### CHR bankswitching

Sur MMC1/MMC3/CNROM/GxROM et autres mappers, la CHR visible depend de registres
mapper. Une spritesheet statique par ROM peut etre incomplete. qlnes doit soit :

- dumper la CHR active par frame ;
- explorer plusieurs etats de jeu ;
- utiliser un logger d'acces CHR pour lister les tiles reellement dessinees.

FCEUX documente que son PPU Viewer affiche l'etat courant de la memoire PPU, et
que le masquage des graphics utilises via Code/Data Logger ne marche que pour
CHR-ROM parce que le logger observe les acces CHR-ROM. C'est un bon modele pour
qlnes : l'etat runtime est la source correcte.

## Strategie d'implementation pour qlnes

### Niveau 1 : enrichir l'existant statique

Objectif : ne pas promettre "couleurs originales" quand on n'a que la CHR.

Actions :

- Renommer/clarifier la sortie actuelle comme `pattern_table_indices.png` ou
  garder `chr_tiles.png` avec un manifeste explicite `color_source=synthetic`.
- Ajouter un JSON :

```json
{
  "kind": "chr_static",
  "chr_source": "chr_rom",
  "color_source": "synthetic_palette",
  "palette_profile": "qlnes-index-preview",
  "warning": "CHR tiles contain color indices only, not original palettes."
}
```

### Niveau 2 : capture runtime PPU/OAM

Nouvelle commande possible :

```bash
python -m qlnes sprites ROM.nes \
  --frame 600 \
  --out assets/sprites \
  --palette-profile fceux-default \
  --include-json
```

Sorties :

```text
assets/sprites/
├── frame-000600/
│   ├── spritesheet.png
│   ├── spritesheet.json
│   ├── sprite-00.png
│   ├── sprite-01.png
│   └── ppu-state.json
└── manifest.json
```

`ppu-state.json` doit contenir :

- frame ;
- mapper ;
- `ppuctrl`, `ppumask` ;
- `palette_ram` en valeurs hex PPU ;
- OAM brut ;
- CHR bank hash ;
- region NTSC/PAL ;
- palette RGB profile.

### Niveau 3 : rendu frame-perfect/oracle

Pour les cas durs :

- palettes changees mid-frame ;
- CHR bankswitch mid-frame ;
- sprite 0 hit/raster effects ;
- status bar avec pattern table differente ;
- jeux qui modifient scroll/palette pendant le rendu.

Dans ces cas, un simple snapshot debut-frame ou vblank n'est pas suffisant.
Il faut un PPU cycle/scanline aware ou un oracle externe :

- Mesen/FCEUX screenshot + PPU memory dump si scriptable ;
- futur PPU qlnes plus complet ;
- comparaison image contre capture oracle.

## Donnees a stocker pour que le PNG reste auditable

Ne pas stocker seulement `spritesheet.png`. Ajouter un sidecar :

```json
{
  "frame": 600,
  "region": "ntsc",
  "palette_profile": "fceux-default",
  "ppuctrl": "0x18",
  "ppumask": "0x1e",
  "sprite_height": 8,
  "sprite_pattern_table": "0x1000",
  "palette_ram": [
    "0x0f", "0x30", "0x21", "0x11",
    "0x0f", "0x16", "0x27", "0x18"
  ],
  "sprites": [
    {
      "index": 0,
      "x": 120,
      "y_raw": 95,
      "y_screen": 96,
      "tile": "0x24",
      "attr": "0x01",
      "palette_id": 1,
      "priority": "front",
      "flip_h": false,
      "flip_v": false,
      "tile_addrs": ["0x1240"],
      "transparent_index": 0
    }
  ]
}
```

## Tests recommandes

### Tests unitaires

- `decode_tile` conserve les indices `0..3`.
- `sprite_palette_value` retourne `None` pour index `0`.
- OAM attr bits `0..1` selectionnent bien `$3F11-$3F13`,
  `$3F15-$3F17`, `$3F19-$3F1B`, `$3F1D-$3F1F`.
- 8x8 : PPUCTRL bit 3 choisit `$0000` ou `$1000`.
- 8x16 : tile LSB choisit la pattern table et `tile & $FE` choisit la paire.
- flip H/V ne change pas la bounding box.

### Tests integration

- ROM synthetique CHR-ROM avec une tile connue, OAM fixe et palette RAM fixe :
  le PNG attendu contient exactement les RGB du profil choisi.
- ROM CHR-RAM : verifier que l'extracteur statique refuse ou marque
  `requires_runtime_ppu_dump`.
- Mapper CNROM/GxROM : capturer deux etats CHR differents et verifier que le
  hash CHR change dans le manifeste.

### Tests oracle

- Comparer la spritesheet composee avec une capture FCEUX/Mesen sur une ROM
  synthetique sans effets mid-frame.
- Pour les jeux commerciaux, ne versionner que les hashes et les manifests,
  pas les ROMs ni les PNG derives si copyright sensible.

## Recommandation produit

Pour qlnes, la bonne promesse utilisateur est :

> "Extraire les sprites avec les palettes runtime observees a une frame donnee."

Pas :

> "Extraire toutes les couleurs originales depuis la ROM seule."

La deuxieme phrase est fausse pour CHR-RAM, bankswitching, palettes runtime et
effets mid-frame.

## Plan d'implementation propose

1. **Documenter l'existant** : `assets.py` produit CHR/index preview, pas
   sprites colores.
2. **Ajouter un modele PPU snapshot** :
   - `PpuSnapshot(chr, oam, palette_ram, ppuctrl, ppumask, mapper_state, frame)`.
3. **Ajouter decode/composition sprite** :
   - `decode_sprite(snapshot, oam_index, palette_profile) -> SpriteImage`.
4. **Ajouter CLI** :
   - `qlnes sprites ROM.nes --frame N --out DIR`.
5. **Brancher un oracle au debut** :
   - si `cynes` ne donne pas encore OAM/palette/VRAM, utiliser FCEUX/Mesen ou
     un runner debug comme source de snapshot.
6. **Etendre ensuite le runner qlnes** :
   - PPU VRAM/palette/OAM minimal ;
   - mapper CHR visible ;
   - exports deterministes.

## Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Palette RGB non canonique | PNG different selon emulateur | sidecar JSON + profil explicite |
| CHR-RAM invisible statiquement | sprites manquants | capture runtime obligatoire |
| Bankswitch CHR | tiles fausses | stocker mapper_state + CHR snapshot |
| Effets mid-frame | couleurs/tiles fausses | mode oracle/frame-perfect |
| Jeux commerciaux | redistribution interdite | ignorer PNG/ROM derives, versionner notes/tests synthetiques |

## Decision technique

La voie correcte pour qlnes est de garder `CHR -> PNG` comme extraction
statique rapide, puis d'ajouter une deuxieme commande runtime pour les sprites
couleurs. Les "couleurs originales" doivent etre definies comme :

- valeurs palette PPU originales observees ;
- plus un profil RGB explicite pour rendre un PNG inspectable.

Cela preserve la rigueur technique et evite de confondre les indices CHR, les
palettes runtime et l'apparence RGB d'un emulateur donne.

## Methode complete pour obtenir les sprites NES en couleurs originales

Cette section est le protocole recommande pour le projet.

### 1. Identifier le type de donnees graphiques

Lire d'abord le header iNES :

- `CHR size > 0` : le fichier contient de la CHR-ROM. Les formes de tiles sont
  disponibles dans la ROM, mais les couleurs restent runtime.
- `CHR size == 0` : le jeu utilise CHR-RAM. Les tiles visibles sont chargees ou
  generees par le CPU via le PPU. Sans execution du jeu, il manque les formes
  elles-memes.
- `mapper` : determine si la CHR visible est fixe, bank-switched en 8 KiB,
  4 KiB, 2 KiB ou 1 KiB, et si l'extraction statique est representative.

Decision :

- pour une preview rapide : `qlnes sprites ROM.nes --palette ...`;
- pour les couleurs originales : capture runtime obligatoire ;
- pour CHR-RAM : capture runtime obligatoire meme pour les formes.

### 2. Capturer un etat PPU/OAM coherent

Pour une frame ou un checkpoint donne, capturer ensemble :

- OAM primaire 256 octets ;
- palette RAM 32 octets ;
- PPUCTRL et PPUMASK ;
- pattern table PPU visible `$0000-$1FFF`, ou au minimum le CHR bank courant si
  le mapper expose une banque 8 KiB simple ;
- mapper state si le jeu bankswitche PRG/CHR ;
- frame/scanline de capture.

La capture doit etre coherente temporellement. Melanger OAM d'une frame avec la
palette d'une autre frame peut produire des couleurs plausibles mais fausses.

### 3. Decoder les sprites, pas seulement les tiles

Chaque sprite vient d'une entree OAM :

```text
byte 0 = Y brut, affiche a Y+1
byte 1 = tile index
byte 2 = attributes
byte 3 = X
```

Les bits attributs importants :

```text
attr & 0x03 : sous-palette sprite 0..3
attr & 0x20 : priorite derriere background
attr & 0x40 : flip horizontal
attr & 0x80 : flip vertical
```

Regles critiques :

- le pixel CHR `0` devient toujours transparent pour un sprite ;
- les pixels CHR `1..3` se resolvent dans `$3F10 + palette_id*4 + index` ;
- en sprite 8x8, PPUCTRL bit 3 choisit pattern table `$0000` ou `$1000` ;
- en sprite 8x16, PPUCTRL bit 3 est ignore pour les sprites : le bit 0 du tile
  index choisit la pattern table, et `tile & 0xFE` choisit la paire de tiles ;
- le flip vertical 8x16 inverse aussi l'ordre des deux sous-tiles.

### 4. Exporter en PNG transparent et JSON auditable

Le PNG doit etre vu comme un rendu pratique. La preuve technique est le JSON.

Pour chaque sprite, stocker au minimum :

- ROM source et hash si disponible ;
- frame/scanline ;
- OAM index ;
- X, Y brut, Y ecran ;
- tile index, attr, palette_id, priority, flip_h, flip_v ;
- `palette_ppu` : les 4 valeurs PPU de la sous-palette ;
- `palette_rgba` : les RGBA utilises par qlnes pour ce PNG ;
- `transparent_index: 0` ;
- CHR source : `rom-bank`, `runtime-snapshot`, `chr-ram`, etc. ;
- bbox alpha si le sprite est recadre ;
- SHA-256 du PNG brut et du PNG recadre si deduplication.

Sans ces champs, on ne peut pas prouver que le PNG correspond aux couleurs
observees dans la ROM a ce moment.

### 5. Recuperer "tous" les sprites d'une ROM

Il n'existe pas de bouton universel "extraire tous les sprites" depuis une ROM
NES commerciale, car beaucoup de sprites n'existent que dans certains etats du
jeu : title screen, niveau, boss, cutscene, animation, mort, power-up, menu,
etc.

La meilleure strategie pragmatique pour qlnes :

1. faire une extraction statique CHR pour inventaire de formes ;
2. faire des captures runtime samplees : frames `1,30,60,...` ;
3. dedupliquer les PNG RGBA exacts ;
4. produire aussi des PNG recadres transparents ;
5. enregistrer un atlas global avec provenance ROM/frame/OAM/palette ;
6. permettre plus tard des scenarios input : attendre titre, Start, avancer,
   sauter, entrer dans un niveau, etc. ;
7. brancher un oracle externe Mesen/FCEUX pour les jeux a effets PPU complexes.

Commande qlnes actuelle recommandee pour une collection locale :

```bash
python -m qlnes sprites-batch roms/ \
  -o out/sprites-batch \
  --recursive \
  --runtime-sample-range 1:300:30 \
  --allow-failures
```

Resultat attendu :

- un dossier par ROM ;
- des sous-dossiers `frame-XXXXXX/` ;
- `unique/` et `unique-trimmed/` par ROM ;
- `all-unique-trimmed/` et `all-unique-trimmed-spritesheet.png` globalement ;
- `all-unique-trimmed-atlas.json` pour retrouver source, frame, palette et
  coordonnees atlas.

### 6. Quand utiliser un snapshot externe

Utiliser un snapshot externe si :

- le mapper n'est pas supporte par le runner qlnes ;
- la ROM depend d'IRQ, raster effects, mid-frame CHR/palette switch ;
- la ROM utilise un PPU timing exact ;
- l'objectif est une verification visuelle frame-perfect ;
- un emulateur comme FCEUX/Mesen sait deja afficher exactement l'etat voulu.

Format minimal supporte par qlnes :

```json
{
  "frame": 123,
  "chr_bank": 0,
  "ppuctrl": "0x08",
  "ppumask": "0x1E",
  "palette_ram": ["32 valeurs 0x00..0x3F"],
  "oam": ["256 valeurs 0x00..0xFF"]
}
```

Pour CHR-RAM, ou pour un mapper avec fenetres CHR partielles, ajouter :

```json
{
  "chr_data": ["8192 valeurs 0x00..0xFF pour PPU $0000-$1FFF"]
}
```

Puis :

```bash
python -m qlnes sprites ROM.nes \
  -o out/oam-sprites \
  --snapshot snapshot-ppu-oam.json
```

### 7. Definition retenue de "couleurs originales"

Pour qlnes, "couleur originale" doit signifier :

- les valeurs palette PPU originales observees dans `$3F10-$3F1F` au moment de
  capture ;
- les attributs OAM originaux qui choisissent la sous-palette ;
- le pattern table/CHR mapping original au moment de capture ;
- un profil RGB declare pour convertir ces valeurs PPU en PNG.

Ce n'est pas :

- les couleurs dans la CHR, car la CHR ne contient pas de couleurs ;
- une palette universelle unique NES, car le signal video NES est analogique et
  les emulateurs peuvent choisir des palettes RGB differentes ;
- une garantie de tous les sprites d'un jeu sans explorer ses etats runtime.

## Addendum implementation qlnes 2026-07-23

La premiere implementation qlnes suit cette decision :

- `python -m qlnes sprites ROM.nes -o out/sprites --palette 0F,30,16,27`
  exporte une preview statique CHR en PNG RGBA, avec l'index couleur `0`
  transparent.
- `python -m qlnes sprites ROM.nes -o out/oam --snapshot snapshot.json`
  exporte les sprites OAM avec palette RAM runtime, flips, taille 8x8/8x16 et
  canvas `oam-screen.png`.
- `python -m qlnes sprites ROM.nes -o out/oam --runtime-frames 120` boote les
  ROMs simples NROM, MMC1/SxROM, UxROM, CNROM, MMC3, MMC5, AxROM, MMC2/PxROM,
  MMC4/FxROM, Color Dreams, Bandai FCG, Jaleco SS88006, Namco 129/163,
  Irem G-101, Taito TC0190,
  BNROM/NINA, Mapper 42, GxROM/GNROM, Sunsoft FME-7/5B, Bandai, Camerica,
  JF-17 et NINA-03/06 avec l'observateur in-process et capture automatiquement
  PPUCTRL, PPUMASK, palette RAM, OAM/OAMDMA, pattern table CHR-RAM simple,
  CHR bank CNROM actif, fenêtres CHR MMC1 8 KiB/split 4 KiB, fenêtres CHR MMC3
  1 KiB/2 KiB, fenêtres CHR MMC5 sprite, fenêtres CHR MMC2/MMC4 4 KiB latchées, fenêtres CHR NINA 4 KiB, PRG banks AxROM, PRG-CHR banks Color
  Dreams et PRG-CHR banks GxROM, ainsi que les fenêtres PRG 8 KiB et CHR 1 KiB
  FME-7, les fenêtres CHR 1 KiB Bandai FCG/Jaleco SS88006/Namco 129-163/Irem G-101 et 2 KiB/1 KiB Taito TC0190, le registre `PPPP CCCC` Bandai, les bits de commande PRG/CHR JF-17 et
  le registre expansion NINA-03/06.
- `--runtime-input start@1:30,a+right@120:240` pilote la manette 1 pendant la
  capture runtime. Cela permet d'atteindre plus d'etats de jeu que le boot
  naturel seul : ecran titre, debut de niveau, saut, attaque, marche, etc. Le
  manifeste conserve `runtime_input` et `controller1_nonzero_frames`.
- Les ROMs CHR-RAM simples n'ont pas de données graphiques CHR statiques dans
  le fichier `.nes`. L'export runtime capture donc les writes `PPUDATA` vers
  `$0000-$1FFF` et marque le manifeste avec `chr_ram: true`, `chr_source:
  snapshot` et une note `CHR-RAM runtime export`.
- Le bus runtime fournit une PRG-RAM `$6000-$7FFF` zero-init pour les cas où la
  ROM prépare les buffers OAM/palette dans la RAM cartouche avant un `OAMDMA`
  `$4014`. Cela augmente la couverture sans changer le format PNG final.
- Pour mapper 87/J87, NESdev documente un PRG fixe 32 KiB et une fenêtre
  CHR-ROM 8 KiB sélectionnée par writes `$6000-$7FFF`. Le registre expose deux
  bits `LH` où bit 0 = bit CHR haut et bit 1 = bit CHR bas ; qlnes applique ce
  bit-order inversé avant de choisir la CHR bank runtime. Source :
  https://www.nesdev.org/wiki/INES_Mapper_087
- Pour mapper 9/MMC2, NESdev liste PxROM/MMC2 dans la table iNES et le modèle
  MMC4 documente le même principe de fenêtres CHR-ROM 4 KiB sélectionnées par
  latches PPU `$0FD8/$0FE8` et `$1FD8/$1FE8`. qlnes compose donc deux fenêtres
  CHR 4 KiB dans le snapshot runtime depuis les registres `$B000-$E000`, et
  modèle la fenêtre PRG 8 KiB switchable à `$8000-$9FFF`. Sources :
  https://www.nesdev.org/wiki/List_of_mappers et https://www.nesdev.org/wiki/MMC4
- Pour mapper 10/MMC4, NESdev documente une PRG bank 16 KiB switchable à
  `$8000-$BFFF`, la dernière PRG bank fixe à `$C000-$FFFF`, et deux fenêtres
  CHR-ROM 4 KiB sélectionnées par les mêmes latches que MMC2. qlnes exporte
  donc les sprites depuis la pattern table CHR mappée dans le snapshot. Source :
  https://www.nesdev.org/wiki/MMC4
- Pour mapper 16/Bandai FCG, NESdev documente des registres pouvant apparaître
  en `$6000-$600D` ou `$8000-$800D`, avec huit registres CHR-ROM 1 KiB et une
  PRG bank 16 KiB switchable. qlnes observe les deux plages, compose les huit
  fenêtres CHR 1 KiB dans le snapshot runtime et ignore IRQ/EEPROM pour ce
  chemin d'export sprites. Source : https://www.nesdev.org/wiki/INES_Mapper_016
- Pour mapper 18/Jaleco SS88006, NESdev documente trois fenêtres PRG-ROM 8 KiB
  switchables, une dernière fenêtre PRG fixe, et huit fenêtres CHR-ROM 1 KiB.
  Les banks PRG/CHR sont écrites par paires de nibbles ; qlnes recombine ces
  paires pour composer la pattern table visible dans le snapshot runtime.
  IRQ, mirroring et ADPCM sont hors du chemin export sprites. Source :
  https://www.nesdev.org/wiki/INES_Mapper_018
- Pour mapper 19/Namco 129-163, NESdev documente trois fenêtres PRG-ROM 8 KiB
  switchables, une dernière fenêtre PRG fixe, et huit fenêtres CHR-ROM 1 KiB
  pour les pattern tables. qlnes compose ces huit fenêtres dans le snapshot
  runtime ; IRQ, expansion audio et banking nametable spécial restent hors du
  chemin export sprites. Source : https://www.nesdev.org/wiki/INES_Mapper_019
- Pour mapper 5/MMC5, NESdev documente quatre modes PRG, quatre modes CHR, les
  registres PRG `$5114-$5117`, les registres CHR `$5120-$512B` et les bits hauts
  `$5130`. qlnes observe ces registres pour reconstruire les fenêtres CHR sprite
  visibles dans le snapshot runtime ; IRQ, audio MMC5, ExRAM, split screen et
  attributs étendus restent hors du chemin export sprites. Source :
  https://www.nesdev.org/wiki/MMC5
- Pour mapper 32/Irem G-101, NESdev documente deux fenêtres PRG-ROM 8 KiB
  switchables, deux fenêtres PRG fixes avec mode d'échange `$8000/$C000`, et
  huit fenêtres CHR-ROM 1 KiB. qlnes observe les registres PRG/CHR nécessaires
  et compose la pattern table CHR 1 KiB visible dans le snapshot runtime.
  Source : https://www.nesdev.org/wiki/INES_Mapper_032
- Pour mapper 33/Taito TC0190, NESdev documente deux fenêtres PRG-ROM 8 KiB
  switchables, les deux dernières fenêtres PRG fixes, deux fenêtres CHR-ROM
  2 KiB et quatre fenêtres CHR-ROM 1 KiB. qlnes compose cette pattern table
  mixte dans le snapshot runtime pour les PNG OAM couleur. Source :
  https://www.nesdev.org/wiki/INES_Mapper_033
- Pour mapper 101/JF-10, NESdev documente la même famille de board mais avec le
  bit-order CHR normal `HL` à `$6000-$7FFF`, plus une extension oversize mieux
  définie. qlnes sélectionne donc directement la valeur écrite comme CHR bank
  8 KiB runtime. Source : https://www.nesdev.org/wiki/INES_Mapper_101
- Pour mapper 13/CPROM, NESdev documente une PRG-ROM fixe 32 KiB et une
  CHR-RAM totale 16 KiB où PPU `$0000-$0FFF` est fixe et `$1000-$1FFF` expose
  une page CHR-RAM 4 KiB sélectionnée par `$8000-$FFFF`. qlnes capture donc les
  writes CHR-RAM runtime par page et compose la pattern table visible dans le
  snapshot. Source : https://www.nesdev.org/wiki/CPROM
- Pour mapper 78/Holy Diver, NESdev documente une PRG bank 16 KiB switchable à
  `$8000-$BFFF`, la dernière PRG bank fixe à `$C000-$FFFF`, et une CHR-ROM 8 KiB
  switchable via le même registre `CCCC MPPP` à `$8000-$FFFF`. qlnes utilise
  bits `0-2` pour PRG et bits `4-7` pour la CHR bank runtime. Source :
  https://www.nesdev.org/wiki/INES_Mapper_078
- Pour mapper 206/Namco 108, NESdev documente une variante MMC3-like sans IRQ
  ni bits de mode PRG/CHR : les deux dernières PRG banks 8 KiB sont fixes, et
  la CHR est composée de deux fenêtres 2 KiB à gauche plus quatre fenêtres 1
  KiB à droite. qlnes ignore donc les bits hauts de `$8000` et exporte les
  sprites depuis la pattern table CHR mappée dans le snapshot. Source :
  https://www.nesdev.org/wiki/INES_Mapper_206
- Pour mapper 42, NESdev documente les conversions FDS en cartouche : CPU
  `$8000-$FFFF` est fixe sur les derniers 32 KiB de PRG-ROM, CPU
  `$6000-$7FFF` expose une fenêtre PRG-ROM 8 KiB switchable par `$E000`, et PPU
  `$0000-$1FFF` expose une fenêtre CHR-ROM 8 KiB switchable par `$8000`.
  qlnes capture donc les writes `$8000` pour choisir la CHR bank runtime qui
  colore les sprites exportes, et modele `$E000` pour que le boot puisse lire
  du code ou des donnees dans la fenêtre `$6000`. Source :
  https://www.nesdev.org/wiki/INES_Mapper_042
- Pour mapper 72/JF-17, NESdev documente une PRG bank 16 KiB switchable à
  `$8000-$BFFF`, la dernière PRG bank fixe à `$C000-$FFFF`, et une CHR-ROM
  8 KiB switchable. qlnes observe les writes `$8000-$FFFF` : un bit `7`
  montant sélectionne la PRG bank depuis bits `0-3`, et un bit `6` montant
  sélectionne la CHR bank depuis bits `0-3`. Source :
  https://www.nesdev.org/wiki/INES_Mapper_072
- Pour mapper 70/Bandai, NESdev documente une PRG bank 16 KiB switchable à
  `$8000-$BFFF`, la dernière PRG bank fixe à `$C000-$FFFF`, et une CHR-ROM
  8 KiB switchable. qlnes lit le registre `$8000-$FFFF` au format
  `PPPP CCCC` : bits `4-7` pour PRG, bits `0-3` pour CHR. Source :
  https://www.nesdev.org/wiki/INES_Mapper_070
- Pour mapper 79/NINA-03-06, NESdev documente une PRG bank 32 KiB switchable
  à `$8000-$FFFF` et une CHR-ROM 8 KiB switchable à `$0000-$1FFF`. qlnes
  observe le registre expansion `$4100-$5FFF` decode sur les pages impaires :
  bit `3` sélectionne la PRG bank et bits `0-2` sélectionnent la CHR bank.
  Source : https://www.nesdev.org/wiki/INES_Mapper_079
- Pour mapper 11/Color Dreams, NESdev documente une fenêtre CPU 32 KiB
  switchable à `$8000-$FFFF`, une fenêtre PPU CHR 8 KiB à `$0000-$1FFF`, et
  un registre `CCCC LLPP` : bits `0-1` pour le PRG bank 32 KiB, bits `4-7`
  pour le CHR bank 8 KiB, bits `2-3` réservés au contournement lockout.
  Source : https://www.nesdev.org/wiki/INES_Mapper_011

Sorties principales :

- `tiles/*.png` ou `oam/sprite-*.png` : PNG transparents individuels ;
- `spritesheet-*.png` ou `oam-spritesheet.png` : spritesheet transparente ;
- `oam-screen.png` : composition sprite-only 256x240 avec fond transparent ;
- `sprites-manifest.json` : provenance, palette RAM, profil RGB, frame,
  mapper/CHR state et attributs OAM.

Limites conservees volontairement :

- les variantes mapper complexes et IRQ/raster effects ne sont pas encore
  captures automatiquement ;
- les changements mid-frame palette/CHR restent hors scope sans oracle PPU
  complet ;
- le PNG est un rendu inspectable, mais les valeurs palette PPU du manifeste
  restent la verite technique.
