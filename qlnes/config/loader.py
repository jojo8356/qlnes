"""Layered config (FR27 minimal in A.1; full in D.4)."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Layer(Enum):
    DEFAULT = 1
    TOML = 2
    ENV = 3
    CLI = 4


@dataclass(frozen=True)
class ResolvedConfig:
    section: str
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Layer] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


BUILTIN_DEFAULTS: dict[str, dict[str, Any]] = {
    "default": {
        "output_dir": ".",
        "quiet": False,
        "color": "auto",
        "hints": True,
        "progress": True,
    },
    "audio": {
        "format": "wav",
        "frames": 600,
        "reference_emulator": "fceux",
    },
}

ENV_PREFIX = "QLNES_"


class ConfigLoader:
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._config_path = config_path
        self._cwd = cwd or Path.cwd()
        self._env = env if env is not None else os.environ

    def resolve(
        self,
        command: str,
        cli_overrides: Mapping[str, Any] | None = None,
    ) -> ResolvedConfig:
        cli_overrides = cli_overrides or {}
        merged: dict[str, Any] = {}
        prov: dict[str, Layer] = {}
        defaults = {
            **BUILTIN_DEFAULTS["default"],
            **BUILTIN_DEFAULTS.get(command, {}),
        }
        for k, v in defaults.items():
            merged[k] = v
            prov[k] = Layer.DEFAULT
        for k, v in self._read_toml(command).items():
            merged[k] = v
            prov[k] = Layer.TOML
        for k, v in self._read_env(command).items():
            merged[k] = v
            prov[k] = Layer.ENV
        for k, v in cli_overrides.items():
            if v is None:
                continue
            merged[k] = v
            prov[k] = Layer.CLI
        return ResolvedConfig(command, merged, prov)

    def _read_toml(self, command: str) -> dict[str, Any]:
        for p in (self._config_path, self._cwd / "qlnes.toml"):
            if p and p.exists():
                with p.open("rb") as f:
                    doc = tomllib.load(f)
                return {**doc.get("default", {}), **doc.get(command, {})}
        return {}

    def _read_env(self, command: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        cmd_prefix = f"{command}_"
        for k, v in self._env.items():
            if not k.startswith(ENV_PREFIX):
                continue
            stripped = k[len(ENV_PREFIX) :].lower()
            if stripped.startswith(cmd_prefix):
                out[stripped[len(cmd_prefix) :]] = self._coerce(v)
            elif "_" not in stripped:
                out[stripped] = self._coerce(v)
        return out

    @staticmethod
    def _coerce(v: str) -> Any:
        low = v.lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
        if v.lstrip("-").isdigit():
            return int(v)
        return v
