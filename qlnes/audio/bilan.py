"""Audio provenance writer for `qlnes audio --bilan`.

This is intentionally small and local to the audio command. The broader
corpus-level `qlnes audit` contract belongs to Epic 2, but Epic 1 needs enough
provenance to prove tier-2 unknown output is never recorded as a pass.
"""

from __future__ import annotations

from pathlib import Path

from .._version import __version__
from ..det import canonical_json_bytes
from ..io.atomic import atomic_write_bytes
from .mp3 import INSTALLED_VERSION as LAMEENC_VERSION
from .renderer import RenderResult


def build_audio_bilan(result: RenderResult, *, fmt: str, frames: int) -> dict:
    return {
        "schema": "qlnes.audio_bilan.v1",
        "qlnes_version": __version__,
        "rom": {
            "stem": result.rom_stem,
            "sha256": result.rom_sha256,
            "mapper": result.mapper,
        },
        "engine": {
            "name": result.engine_name,
            "tier": result.tier,
            "mode": result.engine_mode_used,
            "detection_evidence": result.detection_evidence or [],
            "detection_metadata": result.detection_metadata or {},
        },
        "render": {
            "format": fmt,
            "frames": frames,
            "encoder": _encoder_block(fmt),
        },
        "tracks": [
            {
                "song_index": track.song_index,
                "label": track.label,
                "referenced": track.referenced,
                "status": track.status,
                "output_path": str(track.output_path),
                "sample_rate": track.sample_rate,
                "duration_seconds": track.duration_seconds,
                "pcm_sha256": track.pcm_sha256,
                "output_sha256": track.output_sha256,
                "loop": (
                    None
                    if track.loop_start_sample is None or track.loop_end_sample is None
                    else {
                        "start_sample": track.loop_start_sample,
                        "end_sample": track.loop_end_sample,
                    }
                ),
                "loop_provenance": _loop_provenance(track),
                "metadata": track.song_metadata,
            }
            for track in result.tracks
        ],
    }


def write_audio_bilan(
    path: Path | str,
    result: RenderResult,
    *,
    fmt: str,
    frames: int,
) -> None:
    atomic_write_bytes(path, canonical_json_bytes(build_audio_bilan(result, fmt=fmt, frames=frames)))


def _encoder_block(fmt: str) -> dict[str, object] | None:
    if fmt != "mp3":
        return None
    return {
        "name": "lameenc",
        "version": LAMEENC_VERSION,
        "profile": "VBR V2",
        "sample_rate": 44_100,
    }


def _loop_provenance(track) -> dict[str, object]:
    if track.loop_start_sample is not None and track.loop_end_sample is not None:
        return {"status": "verified", "source": "engine"}
    return {"status": "unverified", "reason": "unavailable"}
