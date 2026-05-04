import json

import pytest

from qlnes.io.errors import (
    DEFAULT_HINTS,
    EXIT_CODES,
    QlnesError,
    emit,
    warn,
)


def test_qlneserror_known_class_has_code():
    e = QlnesError("bad_rom", "not iNES")
    assert e.code == 65
    assert e.cls == "bad_rom"
    assert e.reason == "not iNES"


def test_qlneserror_unknown_class_raises():
    with pytest.raises(ValueError, match="unknown error class"):
        QlnesError("nonexistent_class", "x")


def test_qlneserror_extra_default_empty():
    e = QlnesError("bad_rom", "x")
    assert e.extra == {}


def test_emit_writes_three_lines_default(capsys):
    with pytest.raises(SystemExit) as exc:
        emit(QlnesError("bad_rom", "not an iNES ROM"))
    assert exc.value.code == 65
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "qlnes: error: not an iNES ROM"
    assert err[1] == "hint: " + DEFAULT_HINTS["bad_rom"]
    payload = json.loads(err[2])
    assert payload["code"] == 65
    assert payload["class"] == "bad_rom"
    assert "qlnes_version" in payload


def test_emit_no_hints_strips_hint_line(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "x"), no_hints=True)
    err = capsys.readouterr().err.splitlines()
    assert not any(line.startswith("hint:") for line in err)
    assert err[0].endswith("x")
    json.loads(err[-1])


def test_emit_custom_hint_overrides_default(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "x", hint="Custom guidance."))
    err = capsys.readouterr().err.splitlines()
    assert err[1] == "hint: Custom guidance."


def test_emit_extra_fields_in_payload(capsys):
    with pytest.raises(SystemExit):
        emit(
            QlnesError(
                "unsupported_mapper",
                "mapper 5 audio not covered",
                extra={"mapper": 5, "rom_sha256": "deadbeef"},
            )
        )
    err = capsys.readouterr().err.splitlines()
    payload = json.loads(err[-1])
    assert payload["mapper"] == 5
    assert payload["rom_sha256"] == "deadbeef"
    assert payload["code"] == 100


def test_emit_payload_is_canonical_json(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "x", extra={"z": 1, "a": 2}))
    err = capsys.readouterr().err.splitlines()
    raw = err[-1]
    assert ", " not in raw
    assert ": " not in raw
    keys_in_order = list(json.loads(raw).keys())
    assert keys_in_order == sorted(keys_in_order)


def test_emit_color_off_has_no_ansi(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "x"), color=False)
    err = capsys.readouterr().err
    assert "\033[" not in err


def test_emit_color_on_has_ansi(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "x"), color=True)
    err = capsys.readouterr().err
    assert "\033[31;1m" in err


def test_emit_interrupted_no_hint_by_default(capsys):
    """`interrupted` has DEFAULT_HINTS == None — no hint line emitted."""
    with pytest.raises(SystemExit) as exc:
        emit(QlnesError("interrupted", "interrupted"))
    assert exc.value.code == 130
    err = capsys.readouterr().err.splitlines()
    assert not any(line.startswith("hint:") for line in err)


def test_warn_writes_three_lines_no_exit(capsys):
    warn("bilan_stale", "bilan.json is stale", hint="Run `qlnes coverage --refresh`.")
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "qlnes: warning: bilan.json is stale"
    assert err[1] == "hint: Run `qlnes coverage --refresh`."
    payload = json.loads(err[2])
    assert payload["class"] == "bilan_stale"
    assert "code" not in payload  # warnings have no exit code


def test_warn_no_hint_omits_line(capsys):
    warn("x", "no hint here")
    err = capsys.readouterr().err.splitlines()
    assert err[0].endswith("no hint here")
    json.loads(err[-1])
    assert len(err) == 2


def test_exit_codes_disjoint():
    """Exit codes are reusable across classes (e.g. usage_error and bad_format_arg both 64),
    but the class names must be unique. Verify class set is a set."""
    assert len(EXIT_CODES) == len(set(EXIT_CODES))


def test_exit_codes_match_locked_taxonomy():
    expected = {
        "usage_error": 64,
        "bad_format_arg": 64,
        "bad_rom": 65,
        "missing_input": 66,
        "internal_error": 70,
        "cant_create": 73,
        "io_error": 74,
        "unsupported_mapper": 100,
        "in_process_unavailable": 100,  # F.5: engine has no in-process support
        "equivalence_failed": 101,
        "missing_reference": 102,
        "interrupted": 130,
    }
    assert expected == EXIT_CODES
