from qlnes.config.loader import (
    BUILTIN_DEFAULTS,
    ConfigLoader,
    Layer,
)


def test_defaults_only(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert cfg["format"] == "wav"
    assert cfg["frames"] == 600
    assert cfg["reference_emulator"] == "fceux"
    assert cfg["quiet"] is False
    assert cfg.provenance["format"] == Layer.DEFAULT


def test_default_section_keys_present_on_every_command(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert "color" in cfg.values
    assert "hints" in cfg.values
    assert "progress" in cfg.values


def test_toml_overrides_defaults(tmp_path):
    (tmp_path / "qlnes.toml").write_text('[audio]\nformat = "mp3"\nframes = 300\n')
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert cfg["format"] == "mp3"
    assert cfg["frames"] == 300
    assert cfg.provenance["format"] == Layer.TOML
    assert cfg.provenance["reference_emulator"] == Layer.DEFAULT


def test_toml_default_section(tmp_path):
    (tmp_path / "qlnes.toml").write_text("[default]\nquiet = true\n")
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert cfg["quiet"] is True
    assert cfg.provenance["quiet"] == Layer.TOML


def test_env_overrides_toml(tmp_path):
    (tmp_path / "qlnes.toml").write_text('[audio]\nformat = "mp3"\n')
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_AUDIO_FORMAT": "wav"},
    ).resolve("audio")
    assert cfg["format"] == "wav"
    assert cfg.provenance["format"] == Layer.ENV


def test_env_command_unprefixed_key_targets_default_section(tmp_path):
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_QUIET": "1"},
    ).resolve("audio")
    assert cfg["quiet"] is True
    assert cfg.provenance["quiet"] == Layer.ENV


def test_cli_overrides_env(tmp_path):
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_AUDIO_FORMAT": "mp3"},
    ).resolve("audio", cli_overrides={"format": "wav"})
    assert cfg["format"] == "wav"
    assert cfg.provenance["format"] == Layer.CLI


def test_cli_none_does_not_override(tmp_path):
    """--flag not passed yields None; should NOT clobber TOML/env."""
    (tmp_path / "qlnes.toml").write_text('[audio]\nformat = "mp3"\n')
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve(
        "audio",
        cli_overrides={"format": None},
    )
    assert cfg["format"] == "mp3"
    assert cfg.provenance["format"] == Layer.TOML


def test_env_bool_coercion_yes_no(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={"QLNES_QUIET": "yes"}).resolve("audio")
    assert cfg["quiet"] is True
    cfg = ConfigLoader(cwd=tmp_path, env={"QLNES_QUIET": "no"}).resolve("audio")
    assert cfg["quiet"] is False


def test_env_bool_coercion_true_false(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={"QLNES_QUIET": "true"}).resolve("audio")
    assert cfg["quiet"] is True
    cfg = ConfigLoader(cwd=tmp_path, env={"QLNES_QUIET": "FALSE"}).resolve("audio")
    assert cfg["quiet"] is False


def test_env_int_coercion(tmp_path):
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_AUDIO_FRAMES": "1200"},
    ).resolve("audio")
    assert cfg["frames"] == 1200
    assert isinstance(cfg["frames"], int)


def test_env_negative_int_coercion(tmp_path):
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_AUDIO_FRAMES": "-5"},
    ).resolve("audio")
    assert cfg["frames"] == -5


def test_env_string_passthrough(tmp_path):
    cfg = ConfigLoader(
        cwd=tmp_path,
        env={"QLNES_AUDIO_FORMAT": "mp3"},
    ).resolve("audio")
    assert cfg["format"] == "mp3"


def test_explicit_config_path_wins_over_cwd(tmp_path):
    (tmp_path / "qlnes.toml").write_text('[audio]\nformat = "mp3"\n')
    other = tmp_path / "other.toml"
    other.write_text('[audio]\nformat = "wav"\n')
    cfg = ConfigLoader(config_path=other, cwd=tmp_path, env={}).resolve("audio")
    assert cfg["format"] == "wav"


def test_missing_toml_silently_falls_through(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert cfg["format"] == "wav"
    assert cfg.provenance["format"] == Layer.DEFAULT


def test_resolved_config_get_method(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("audio")
    assert cfg.get("format") == "wav"
    assert cfg.get("nonexistent", "fallback") == "fallback"


def test_unknown_command_uses_default_section_only(tmp_path):
    cfg = ConfigLoader(cwd=tmp_path, env={}).resolve("madeup")
    assert "color" in cfg.values
    assert "format" not in cfg.values  # no [madeup] section


def test_builtin_defaults_locked():
    """Lock the BUILTIN_DEFAULTS schema. Drift here is a contract change."""
    assert BUILTIN_DEFAULTS["default"] == {
        "output_dir": ".",
        "quiet": False,
        "color": "auto",
        "hints": True,
        "progress": True,
    }
    assert BUILTIN_DEFAULTS["audio"] == {
        "format": "wav",
        "frames": 600,
        "reference_emulator": "fceux",
    }
