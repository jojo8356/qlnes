import json
from pathlib import Path

from PIL import Image

from qlnes.smb_graphics import (
    ENEMY_METASPRITES,
    PLAYER_METASPRITES,
    render_smb_blocks,
    render_smb_characters,
    render_smb_level,
    render_smb_level_batch,
    render_smb_title_assets,
    validate_smb_nrom,
)
from tests.test_setup import ines_header


def test_validate_smb_nrom_rejects_non_nrom_mapper():
    rom = ines_header(2, 1, 2) + bytes(0x8000) + bytes(0x2000)

    try:
        validate_smb_nrom(rom)
    except ValueError as exc:
        assert "mapper 0" in str(exc)
    else:
        raise AssertionError("validate_smb_nrom accepted a non-NROM mapper")


def test_render_smb_level_1_1_when_local_rom_is_available(tmp_path):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    export = render_smb_level(rom, tmp_path, stage="1-1")

    assert export.stage == "1-1"
    assert export.columns > 100
    assert export.rows == 13
    assert export.width == export.columns * 16
    assert export.height == 13 * 16
    assert export.unique_metatiles > 10
    assert export.png.exists()
    assert export.manifest_json.exists()

    with Image.open(export.png) as image:
        assert image.size == (export.width, export.height)
        assert image.convert("RGB").getbbox() == (0, 0, export.width, export.height)

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert data["kind"] == "smb_assembled_level_export"
    assert data["engine_symbols"]["AreaParserCore"] == "0x93FC"


def test_render_smb_level_batch_when_local_rom_is_available(tmp_path):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    batch = render_smb_level_batch(
        rom,
        tmp_path,
        stages=["1-1", "1-2", "bonus"],
        allow_failures=True,
    )

    assert batch.success_count == 3
    assert batch.failure_count == 0
    assert batch.manifest_json.exists()
    data = json.loads(batch.manifest_json.read_text(encoding="utf-8"))
    assert data["success_count"] == 3
    assert {entry["stage"] for entry in data["levels"]} == {"1-1", "1-2", "bonus"}


def test_smb_pipe_intro_stages_do_not_replace_main_stages_when_local_rom_is_available(
    tmp_path,
):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    main = render_smb_level(rom, tmp_path, stage="1-2")
    intro = render_smb_level(rom, tmp_path, stage="1-2-intro")

    assert main.width > intro.width
    assert main.area_type == 2
    assert intro.area_type == 1


def test_render_smb_characters_when_local_rom_is_available(tmp_path):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    export = render_smb_characters(rom, tmp_path)

    assert len(export.sprites) == len(PLAYER_METASPRITES) + len(ENEMY_METASPRITES)
    assert export.spritesheet.exists()
    assert export.manifest_json.exists()
    assert (tmp_path / "players" / "small-stand.png").exists()
    assert (tmp_path / "enemies" / "goomba.png").exists()

    with Image.open(export.spritesheet) as image:
        assert image.convert("RGBA").getchannel("A").getbbox() is not None

    with Image.open(tmp_path / "enemies" / "goomba.png") as image:
        assert image.size[0] >= 16
        assert image.convert("RGBA").getchannel("A").getbbox() is not None

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert data["kind"] == "smb_character_metasprite_export"
    assert data["engine_symbols"]["PlayerGraphicsTable"] == "0xEE17"


def test_render_smb_blocks_when_local_rom_is_available(tmp_path):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    export = render_smb_blocks(rom, tmp_path)

    assert len(export.metatile_sheets) == 4
    assert len(export.block_sheets) == 4
    assert export.sprite_sheet.exists()
    assert export.manifest_json.exists()
    assert (tmp_path / "blocks" / "ground-question-block-state-1-0xc1.png").exists()
    assert (tmp_path / "blocks" / "ground-used-empty-block-0xc4.png").exists()
    assert (tmp_path / "sprites" / "jumping-coin-frame-0.png").exists()

    with Image.open(export.metatile_sheets[1]) as image:
        assert image.size == (16 * 17 + 1, 16 * 17 + 1)
        assert image.convert("RGBA").getchannel("A").getbbox() is not None

    with Image.open(export.sprite_sheet) as image:
        assert image.convert("RGBA").getchannel("A").getbbox() is not None

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert data["kind"] == "smb_block_metatile_export"
    assert data["engine_symbols"]["JumpingCoinTiles"] == "0xF99E"


def test_render_smb_title_assets_when_local_rom_is_available(tmp_path):
    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    export = render_smb_title_assets(rom, tmp_path)

    assert export.title_screen.exists()
    assert export.title_logo.exists()
    assert export.font_sheet.exists()
    assert export.title_glyph_sheet.exists()
    assert export.manifest_json.exists()

    with Image.open(export.title_screen) as image:
        assert image.size == (256, 240)
        assert image.convert("RGB").getbbox() is not None

    with Image.open(export.title_logo) as image:
        assert image.size == (176, 80)
        assert image.convert("RGB").getbbox() is not None

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert data["kind"] == "smb_title_logo_font_export"
    assert data["title_screen_data_offset"] == "0x1EC0"
