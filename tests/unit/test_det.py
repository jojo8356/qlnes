import json

from qlnes.det import (
    canonical_json,
    canonical_json_bytes,
    deterministic_track_filename,
    sha256_bytes,
    sha256_file,
    stable_iter,
)


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_no_whitespace():
    out = canonical_json({"a": [1, 2, 3], "b": {"c": 1}})
    assert " " not in out


def test_canonical_json_unicode_passthrough():
    assert canonical_json({"name": "café"}) == '{"name":"café"}'


def test_canonical_json_bytes_is_utf8():
    out = canonical_json_bytes({"x": "é"})
    assert out == b'{"x":"\xc3\xa9"}'


def test_canonical_json_round_trip_stable():
    obj = {"z": 0, "a": [1, {"b": 2, "a": 1}]}
    out1 = canonical_json(obj)
    out2 = canonical_json(json.loads(out1))
    assert out1 == out2


def test_sha256_bytes_known_vector():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_bytes_lowercase_hex():
    h = sha256_bytes(b"x")
    assert h == h.lower()
    assert len(h) == 64


def test_sha256_file_matches_bytes(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == sha256_bytes(b"abc")


def test_sha256_file_chunked_consistency(tmp_path):
    data = b"x" * (1 << 17)
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    assert sha256_file(p, chunk=1024) == sha256_file(p, chunk=1 << 16)


def test_deterministic_track_filename_zero_pads():
    assert (
        deterministic_track_filename("game", 4, "famitracker", "wav") == "game.04.famitracker.wav"
    )


def test_deterministic_track_filename_two_digits_room_for_99():
    assert deterministic_track_filename("g", 99, "x", "wav") == "g.99.x.wav"


def test_deterministic_track_filename_handles_three_digits():
    # spec says 02d — index 100 just renders as 100, no surprise
    assert deterministic_track_filename("g", 100, "x", "wav") == "g.100.x.wav"


def test_stable_iter_default_sorted():
    assert stable_iter([3, 1, 2]) == [1, 2, 3]


def test_stable_iter_with_key():
    items = [{"k": 2}, {"k": 1}]
    assert stable_iter(items, key=lambda d: d["k"]) == [{"k": 1}, {"k": 2}]


def test_canonical_json_separator_invariant():
    """Lock the (',', ':') separator: this is the project invariant — see architecture step 7."""
    obj = {"a": [1, 2], "b": "c"}
    out = canonical_json(obj)
    assert ", " not in out and ": " not in out
