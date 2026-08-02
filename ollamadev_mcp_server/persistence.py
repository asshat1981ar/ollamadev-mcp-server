"""Persistence helpers for user-configurable server settings.

Settings are stored as a single JSON object on disk. The file location follows:

1. the ``OLLAMADEV_SETTINGS_FILE`` environment variable (authoritative when set),
2. otherwise ``<WORKSPACE_ROOT>/store/server_settings.json``.

This module has no imports from ``constants`` so it can be safely imported from
there without creating a circular dependency.
"""

import json
import os
from pathlib import Path

DEFAULT_WORKSPACE_ROOT = "/home/userland/OllamaDev"
_SETTINGS_SUBPATH = Path("store") / "server_settings.json"


def settings_file_path() -> Path:
    """Return the resolved settings file path (env override first)."""
    override = os.environ.get("OLLAMADEV_SETTINGS_FILE")
    if override:
        return Path(override)
    base = os.environ.get("WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)
    return Path(base) / _SETTINGS_SUBPATH


def load_persisted_settings(path: Path | None = None) -> dict[str, str]:
    """Load persisted settings; returns {} when missing or malformed."""
    target = path or settings_file_path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if v not in (None, "")}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_persisted_settings(data: dict, path: Path | None = None) -> None:
    """Write settings atomically (temp file + rename)."""
    target = path or settings_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)


def clear_persisted_settings(path: Path | None = None) -> bool:
    """Remove the settings file; returns True if a file was removed."""
    target = path or settings_file_path()
    if target.exists():
        target.unlink()
        return True
    return False
