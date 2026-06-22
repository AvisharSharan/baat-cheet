"""JSON-backed application settings store.

Settings are persisted to *data/settings.json* and fall back to environment
variables when a key has never been saved.  The services layer (``mom.py``,
``transcription.py``, …) reads ``os.environ`` so ``save_settings`` patches
``os.environ`` as a side-effect to keep everything consistent without
restarting the server.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any, Dict

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(os.getenv("MOM_SETTINGS_PATH", "data/settings.json"))
_lock = RLock()

# ── schema: key → (env-var name, default value) ─────────────────────
_SCHEMA: Dict[str, tuple[str, str]] = {
    # Ollama / LLM
    "ollama_base_url":   ("OLLAMA_BASE_URL",       "http://127.0.0.1:11434"),
    "ollama_model":      ("OLLAMA_MOM_MODEL",      "qwen2.5:3b"),
    "mom_max_tokens":    ("MOM_MAX_TOKENS",        "1200"),
    "ollama_num_ctx":    ("OLLAMA_NUM_CTX",        "32768"),
    "ollama_num_gpu":    ("OLLAMA_NUM_GPU",        "0"),
    # Transcription
    "transcription_provider": ("TRANSCRIPTION_PROVIDER", "local"),
    "whisper_model":     ("FASTER_WHISPER_MODEL",  "base"),
    "whisper_device":    ("FASTER_WHISPER_DEVICE",  "cuda"),
    "live_whisper_model": ("LIVE_WHISPER_MODEL",   "base"),
    "indic_conformer_model": ("INDIC_CONFORMER_MODEL", "ai4bharat/indic-conformer-600m-multilingual"),
    "indic_conformer_language": ("INDIC_CONFORMER_LANGUAGE", "hi"),
    "indic_conformer_decoder": ("INDIC_CONFORMER_DECODER", "ctc"),
    "indic_conformer_device": ("INDIC_CONFORMER_DEVICE", "cuda"),
    # Diarization
    "diarization_provider": ("DIARIZATION_PROVIDER", "pyannote"),
    # Voiceprinting
    "voiceprinting_enabled": ("VOICEPRINTING_ENABLED", "1"),
}


def _read_file() -> Dict[str, str]:
    """Read the settings file, returning an empty dict on failure."""
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read settings from %s", _SETTINGS_PATH, exc_info=True)
        return {}


def _write_file(data: Dict[str, str]) -> None:
    """Atomically write settings to disk."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_PATH)


def load_settings() -> Dict[str, Any]:
    """Return the full settings dict, merging saved values with env/defaults."""
    with _lock:
        saved = _read_file()
    result: Dict[str, Any] = {}
    for key, (env_var, default) in _SCHEMA.items():
        result[key] = saved.get(key) or os.getenv(env_var, default)
    return result


def save_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist *updates* and patch ``os.environ`` so services pick up changes."""
    with _lock:
        current = _read_file()
        for key, value in updates.items():
            if key not in _SCHEMA:
                continue
            current[key] = str(value)
            env_var = _SCHEMA[key][0]
            os.environ[env_var] = str(value)
        _write_file(current)
    return load_settings()
