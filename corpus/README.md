# qlnes test corpus

This directory is the **canonical source of truth** for the equivalence
test corpus that gates qlnes releases (PRD FR26).

## What's committed vs not

| File | Committed | Why |
|---|---|---|
| `manifest.toml` | ✓ yes | SHA-256 + metadata only — no ROM bytes |
| `README.md` | ✓ yes | This file |
| `roms/<sha>.nes` | ✗ never | Commercial / homebrew ROMs we don't redistribute (architecture step 11, ADR-09) |
| `references/<sha>.wav` | ✗ never | FCEUX-rendered reference PCM, derived from ROMs we don't redistribute |

Both `roms/` and `references/` are covered by the root `.gitignore` (`*.nes`,
plus `corpus/roms/` / `corpus/references/` explicit entries).

## Setup procedure

For each `[[rom]]` entry in `manifest.toml`:

1. **Obtain the ROM legally.** Each entry's `notes` field documents the
   distribution channel (scene.org, author website, store-bought cartridge
   dumped via your own hardware, …). qlnes does not bundle ROMs.
2. **Place the file** at `corpus/roms/<sha256>.nes`. The filename MUST be
   the lowercase hex SHA-256 of the ROM bytes — otherwise the audit
   refuses to use it.
3. **Verify the hash:**
   ```bash
   sha256sum corpus/roms/<sha256>.nes
   # The output's first column must equal the filename minus .nes
   ```
4. **(Optional) Generate the FCEUX reference PCM** for sample-equivalence
   tests:
   ```bash
   python scripts/generate_references.py --sha <sha256>     # B.3 lands this
   ```

Contributors without local ROMs can still run unit + integration tests;
only `tests/invariants/test_pcm_equivalence.py` parametrizes on this corpus
and skips per-ROM when the local file is absent.

## Adding a new ROM

1. Verify it has a covered audio engine (run `qlnes audio <rom>` first; if
   detection fails, the engine handler needs work — file an issue).
2. Compute the SHA-256:
   ```bash
   sha256sum your_rom.nes
   ```
3. Add a `[[rom]]` entry to `manifest.toml` with `name`, `sha256`, `mapper`,
   `region`, `engine`, `song_count` (best estimate), `frames` (capture
   window), and `notes` (distribution + license).
4. Place the file at `corpus/roms/<sha>.nes` locally and run the audit.

## License posture

- Commercial NES ROMs: **never redistribute** — even if copyright is
  contested, distribution risk is non-zero. Manifest references are facts
  about the ROM (its hash), not the ROM itself.
- Homebrew ROMs: case-by-case. Some authors permit redistribution (Shiru's
  Alter Ego is in this category per scene.org distribution). Even when
  permitted, qlnes follows hashes-only discipline for consistency.
- FCEUX reference outputs: derived works of FCEUX's emulation, not of the
  ROM. Hashes only.

If you spot a manifest entry that's distributable AND would benefit from
being committed inline (e.g., a contributor's own homebrew), open an issue
to discuss exceptions to the hashes-only rule.
