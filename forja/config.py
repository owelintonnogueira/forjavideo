"""Configurações salvas em ~/.forjavideo/config.json"""
from __future__ import annotations

import json
from pathlib import Path

from .util import default_output_dir

CONFIG_DIR = Path.home() / ".forjavideo"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    "theme": "dark",  # dark | light
    "output_dir": "",
    # Roteiro
    "script_source": "auto",  # auto | ollama | wikipedia | manual
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
    # Narração
    "tts_engine": "edge",  # edge | sapi | piper | elevenlabs | none
    "edge_voice": "pt-BR-AntonioNeural",
    "edge_rate": "+0%",
    "sapi_voice": "",
    "piper_model": "",
    "elevenlabs_key": "",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
    "elevenlabs_model": "eleven_multilingual_v2",
    # Imagens
    "image_source": "commons",  # commons | pexels | folder | generated
    "pexels_key": "",
    "image_folder": "",
    # Vídeo
    "format": "horizontal",  # horizontal | vertical
    "resolution": "720p",  # 720p | 1080p
    "minutes": 3,
    "music_file": "",
    "music_volume": 0.12,
    "make_thumbs": True,
    "thumb_text": "",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    if not cfg.get("output_dir"):
        cfg["output_dir"] = str(default_output_dir())
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
