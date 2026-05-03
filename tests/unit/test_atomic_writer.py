from pathlib import Path

import pytest

from qlnes.io.atomic import atomic_write_bytes, atomic_write_text, atomic_writer


def test_atomic_write_bytes_roundtrip(tmp_path):
    p = tmp_path / "out.bin"
    atomic_write_bytes(p, b"hello")
    assert p.read_bytes() == b"hello"


def test_atomic_write_text_utf8(tmp_path):
    p = tmp_path / "out.txt"
    atomic_write_text(p, "café")
    assert p.read_text(encoding="utf-8") == "café"


def test_atomic_writer_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "c.bin"
    atomic_write_bytes(p, b"x")
    assert p.read_bytes() == b"x"


def test_atomic_writer_unlinks_temp_on_exception(tmp_path):
    p = tmp_path / "out.bin"
    with pytest.raises(RuntimeError):
        with atomic_writer(p, "wb") as f:
            f.write(b"partial")
            raise RuntimeError("boom")
    assert not p.exists()
    leftover = list(tmp_path.glob(".out.bin.*"))
    assert leftover == []


def test_atomic_writer_overwrites_existing(tmp_path):
    p = tmp_path / "out.bin"
    p.write_bytes(b"old")
    atomic_write_bytes(p, b"new")
    assert p.read_bytes() == b"new"


def test_atomic_writer_keeps_old_on_failure(tmp_path):
    p = tmp_path / "out.bin"
    p.write_bytes(b"original")
    with pytest.raises(RuntimeError):
        with atomic_writer(p, "wb") as f:
            f.write(b"would-be-new")
            raise RuntimeError("boom")
    assert p.read_bytes() == b"original"


def test_temp_file_is_in_target_directory(tmp_path):
    """rename(2) is only atomic on the same filesystem; same-dir is the proxy."""
    seen_temps: list[Path] = []
    p = tmp_path / "out.bin"
    with atomic_writer(p, "wb") as f:
        seen_temps.extend(tmp_path.glob(".out.bin.*"))
        f.write(b"x")
    assert len(seen_temps) == 1
    assert seen_temps[0].parent == p.parent


def test_temp_file_hidden_during_write(tmp_path):
    """Hidden temp keeps `ls` clean during in-flight writes."""
    p = tmp_path / "out.bin"
    with atomic_writer(p, "wb") as f:
        f.write(b"x")
        for entry in tmp_path.iterdir():
            if entry.name.startswith(".out.bin."):
                assert entry.name.startswith(".")


def test_atomic_writer_accepts_string_path(tmp_path):
    target = str(tmp_path / "out.bin")
    atomic_write_bytes(target, b"x")
    assert Path(target).read_bytes() == b"x"


def test_no_temp_remains_on_success(tmp_path):
    p = tmp_path / "out.bin"
    atomic_write_bytes(p, b"x")
    leftover = [e for e in tmp_path.iterdir() if e.name.startswith(".out.bin.")]
    assert leftover == []
