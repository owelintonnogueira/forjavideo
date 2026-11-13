"""Utilitários comuns: caminhos, ffmpeg, fontes, cancelamento."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

APP_NAME = "ForjaVideo"
USER_AGENT = "ForjaVideo/1.0 (gerador de videos pessoal; contato: usuario local)"


class Cancelled(Exception):
    """Disparada quando o usuário cancela a produção."""


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self._procs: list[subprocess.Popen] = []

    def cancel(self) -> None:
        self._ev.set()
        for p in list(self._procs):
            try:
                p.kill()
            except Exception:
                pass

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()


def resource_path(rel: str) -> Path:
    """Caminho de recurso, funciona no código-fonte e no .exe (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).resolve().parent.parent / rel


def font_path(weight: str = "Bold") -> str:
    p = resource_path(f"assets/fonts/Poppins-{weight}.ttf")
    if p.exists():
        return str(p)
    for cand in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(cand):
            return cand
    return ""


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "ffmpeg não encontrado. Instale o pacote 'imageio-ffmpeg' (pip install imageio-ffmpeg) "
        "ou coloque o ffmpeg no PATH."
    )


def _popen_flags() -> dict:
    if os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def run_ffmpeg(args: list[str], cancel: CancelToken | None = None) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_flags()
    )
    if cancel:
        cancel._procs.append(proc)
    try:
        _, err = proc.communicate()
    finally:
        if cancel and proc in cancel._procs:
            cancel._procs.remove(proc)
    if cancel:
        cancel.check()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg falhou: " + err.decode("utf-8", "replace")[-1500:])


def audio_duration(path: str | Path) -> float:
    """Duração do áudio em segundos (usa o ffmpeg, sem precisar do ffprobe)."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-i", str(path)]
    proc = subprocess.run(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_flags()
    )
    txt = proc.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if not m:
        raise RuntimeError(f"Não consegui ler a duração de {path}")
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def slugify(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text or "video")[:maxlen].strip("-")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ0-9\"“«(])", text)
    return [p.strip() for p in parts if p.strip()]


def default_output_dir() -> Path:
    home = Path.home()
    for name in ("Videos", "Vídeos", "Documents"):
        if (home / name).exists():
            return home / name / APP_NAME
    return home / APP_NAME
