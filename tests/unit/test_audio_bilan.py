from __future__ import annotations

from pathlib import Path

from qlnes.audio.bilan import build_audio_bilan
from qlnes.audio.renderer import RenderResult, TrackResult


def _result(tmp_path: Path) -> RenderResult:
    wav = tmp_path / "rom.00.famitracker.wav"
    return RenderResult(
        output_paths=[wav],
        engine_name="famitracker",
        tier=1,
        rom_stem="rom",
        engine_mode_used="in-process",
        rom_sha256="abc123",
        mapper=0,
        detection_evidence=["signature:FamiTracker"],
        detection_metadata={"apu_writes_static": 4},
        tracks=[
            TrackResult(
                output_path=wav,
                song_index=0,
                label="main",
                referenced=True,
                status="rendered",
                sample_rate=44_100,
                duration_seconds=1.5,
                pcm_sha256="pcmhash",
                output_sha256="outhash",
                loop_start_sample=100,
                loop_end_sample=1000,
                song_metadata={"source": "embedded_nsf_header"},
            )
        ],
    )


def test_audio_bilan_records_core_provenance(tmp_path):
    bilan = build_audio_bilan(_result(tmp_path), fmt="wav", frames=90)
    assert bilan["schema"] == "qlnes.audio_bilan.v1"
    assert bilan["rom"]["sha256"] == "abc123"
    assert bilan["engine"]["name"] == "famitracker"
    assert bilan["engine"]["tier"] == 1
    assert bilan["tracks"][0]["pcm_sha256"] == "pcmhash"
    assert bilan["tracks"][0]["loop"] == {"start_sample": 100, "end_sample": 1000}
    assert bilan["tracks"][0]["loop_provenance"] == {
        "status": "verified",
        "source": "engine",
    }


def test_audio_bilan_records_mp3_encoder_profile(tmp_path):
    bilan = build_audio_bilan(_result(tmp_path), fmt="mp3", frames=90)
    assert bilan["render"]["encoder"]["name"] == "lameenc"
    assert bilan["render"]["encoder"]["profile"] == "VBR V2"
    assert bilan["render"]["encoder"]["sample_rate"] == 44_100


def test_audio_bilan_records_unverified_loop_when_unavailable(tmp_path):
    result = _result(tmp_path)
    result.tracks[0].loop_start_sample = None
    result.tracks[0].loop_end_sample = None
    bilan = build_audio_bilan(result, fmt="wav", frames=90)
    assert bilan["tracks"][0]["loop"] is None
    assert bilan["tracks"][0]["loop_provenance"] == {
        "status": "unverified",
        "reason": "unavailable",
    }
