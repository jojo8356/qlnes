# STACK — nestest

_Généré automatiquement par **qlnes** le 2026-04-30 14:29._

## En-tête iNES

| Champ | Valeur |
|---|---|
| Magic | `NES\x1A` ✓ |
| Mapper | 0 (NROM) |
| PRG-ROM | 16 KB (1 bank) |
| CHR-ROM | 8 KB (1 bank) |
| Mirroring | horizontal |
| Battery (SRAM) | non |
| Trainer | non |

## Vecteurs CPU

| Vecteur | Adresse CPU | Offset PRG |
|---|---|---|
| NMI | `$C5AF` | `0x05BF` |
| RESET | `$C004` | `0x0014` |
| IRQ | `$C5F4` | `0x0604` |

## Désassemblage statique

- **4379** lignes assembleur
- **17** registres hardware identifiés
- **2** zones OAM
- **6** patterns dataflow détectés
- **41** labels de code internes
- **4** vars zero-page non classifiées
- **3** adresses non classifiées
- **2** JMP indirects (tables de pointeurs)

### Registres hardware utilisés

- `$2000` — **PPUCTRL**
- `$2001` — **PPUMASK**
- `$2002` — **PPUSTATUS**
- `$2005` — **PPUSCROLL**
- `$2006` — **PPUADDR**
- `$2007` — **PPUDATA**
- `$4000` — **APU_PULSE1_CTRL**
- `$4001` — **APU_PULSE1_SWEEP**
- `$4002` — **APU_PULSE1_TIMER_LO**
- `$4003` — **APU_PULSE1_TIMER_HI**
- `$4004` — **APU_PULSE2_CTRL**
- `$4005` — **APU_PULSE2_SWEEP**
- `$4006` — **APU_PULSE2_TIMER_LO**
- `$4007` — **APU_PULSE2_TIMER_HI**
- `$4015` — **APU_STATUS**
- `$4016` — **JOY1**
- `$4017` — **JOY2_FRAMECTR**

### Patterns dataflow détectés

- `$0000` → **arg_pre_jsr** — _STA $0000 juste avant JSR (probable argument)_
- `$00D0` → **ptr0_lo** — _utilisé en addressing indirect (zp),Y ou (zp,X)_
- `$00D1` → **ptr0_hi** — _high byte du pointeur $D0/$D1_
- `$00D2` → **frame_counter** — _INC unconditionnel près du NMI handler_
- `$00D7` → **arg_pre_jsr** — _STA $00D7 juste avant JSR (probable argument)_
- `$00D8` → **arg_pre_jsr** — _STA $00D8 juste avant JSR (probable argument)_

### Sous-routines nommées

| Adresse | Nom | Type | Pourquoi |
|---|---|---|---|
| `$C0ED` | **ppu_load** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C1A1` | **ppu_load_2** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C1ED` | **ppu_load_3** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C261` | **ppu_load_4** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C2A7` | **ppu_load_5** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C2ED` | **ppu_load_6** | `ppu_load` | PPUADDR setup + STA PPUDATA |
| `$C66F` | **play_pulse** | `play_pulse` | écrit registres pulse APU |
| `$C689` | **play_pulse_2** | `play_pulse` | écrit registres pulse APU |

### Sprites (OAM)

2 adresses dans la zone OAM ($0200-$02FF) référencées.

## Stack technique détectée

| Capacité | Présent | Indice |
|---|:---:|---|
| NMI activé (vblank) | ✅ | `STA PPUCTRL avec bit 7` |
| OAM DMA (sprites) | ❌ | `STA OAMDMA ($4014)` |
| Scrolling actif | ✅ | `STA PPUSCROLL ($2005)` |
| Écritures palette/nametable | ✅ | `STA PPUDATA ($2007)` |
| Contrôleur 1 lu | ✅ | `LDA JOY1 ($4016)` |
| Contrôleur 2 lu | ❌ | `LDA JOY2 ($4017)` |
| APU pulses | ✅ | `STA $4000-$4007` |
| APU triangle | ❌ | `STA $4008-$400B` |
| APU noise | ❌ | `STA $400C-$400F` |
| APU DMC (samples) | ❌ | `STA $4010-$4013` |

## Langage / toolchain probable

| Hypothèse | Confiance | Indices |
|---|---:|---|
| **ASM écrit à la main** | 0.70 | peu d'accès indexés ZP (0), pas de frame stack, 9 routines |

## Caractérisation

- jeu avec scrolling
- 2 JMP indirect détectés (tables de pointeurs)
- 36 variables réactives découvertes par discovery dynamique

## Discovery dynamique (cynes)

### Scénario `press_a`

| Adresse | Nom | Δ | Confiance | Raison |
|---|---|---:|---:|---|
| `0x00D4` | **press_a_flag** | 128 | 0.60 | saute brusquement (Δ=-128 en 10f) — sans doute un état booléen |
| `0x00D6` | **press_a_flag** | 128 | 0.60 | saute brusquement (Δ=-128 en 10f) — sans doute un état booléen |

### Scénario `press_b`

| Adresse | Nom | Δ | Confiance | Raison |
|---|---|---:|---:|---|
| `0x00D4` | **press_b_flag** | 64 | 0.60 | saute brusquement (Δ=64 en 10f) — sans doute un état booléen |
| `0x00D6` | **press_b_flag** | 64 | 0.60 | saute brusquement (Δ=64 en 10f) — sans doute un état booléen |

### Scénario `press_start`

| Adresse | Nom | Δ | Confiance | Raison |
|---|---|---:|---:|---|
| `0x0001` | **level** | 255 | 0.70 | changement borné (Δ=-1) — probablement un état/level |
| `0x0034` | **level** | 4 | 0.70 | changement borné (Δ=4) — probablement un état/level |
| `0x0081` | **level** | 2 | 0.70 | changement borné (Δ=2) — probablement un état/level |
| `0x0083` | **level** | 3 | 0.70 | changement borné (Δ=3) — probablement un état/level |
| `0x0084` | **level** | 3 | 0.70 | changement borné (Δ=3) — probablement un état/level |
| `0x008A` | **level** | 3 | 0.70 | changement borné (Δ=3) — probablement un état/level |
| `0x0097` | **level** | 255 | 0.70 | changement borné (Δ=-1) — probablement un état/level |
| `0x0098` | **level** | 255 | 0.70 | changement borné (Δ=-1) — probablement un état/level |
| `0x01FD` | **level** | 255 | 0.70 | changement borné (Δ=-1) — probablement un état/level |
| `0x0200` | **level** | 3 | 0.70 | changement borné (Δ=3) — probablement un état/level |

## Assets extraits

- Dossier : `tests/fixtures/assets/nestest`
- CHR brute : `chr_rom.chr` (binaire 8KB / banque)
- CHR en ASM (réassemblable) : `chr_rom.asm`
- Aperçu image complète : `chr_tiles.png` (512 tiles)
- Pattern table BG : `pattern_table_bg.png`
- Pattern table sprites : `pattern_table_spr.png`

---

_Pour modder cette ROM, voir le désassemblage annoté généré séparément._
