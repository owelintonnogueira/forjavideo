"""Narração: Edge TTS (grátis), voz do Windows (offline), Piper (IA local), ElevenLabs (API) ou sem voz."""
from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import requests

from .util import USER_AGENT

ENGINES = {
    "edge": "Edge TTS (grátis, online, sem chave)",
    "sapi": "Voz do Windows (grátis, offline)",
    "piper": "Piper (IA local, grátis, offline)",
    "elevenlabs": "ElevenLabs (API própria)",
    "none": "Sem narração (só legendas)",
}

EDGE_VOICES = [
    "pt-BR-AntonioNeural",
    "pt-BR-FranciscaNeural",
    "pt-BR-ThalitaMultilingualNeural",
    "pt-PT-DuarteNeural",
    "pt-PT-RaquelNeural",
]

PIPER_MODEL_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"
)


class TTSError(RuntimeError):
    pass


Entries = "list[tuple[str, float, float]] | None"  # (texto, início, duração) em segundos


def synthesize_timed(text: str, out_base: Path, cfg: dict):
    """Gera o áudio da cena. Retorna (caminho, marcas de tempo da voz ou None)."""
    engine = cfg.get("tts_engine", "edge")
    out_base = Path(out_base)
    if engine == "edge":
        return _edge(text, out_base.with_suffix(".mp3"), cfg)
    if engine == "sapi":
        return _sapi(text, out_base.with_suffix(".wav"), cfg), None
    if engine == "piper":
        return _piper(text, out_base.with_suffix(".wav"), cfg), None
    if engine == "elevenlabs":
        return _elevenlabs(text, out_base.with_suffix(".mp3"), cfg)
    return _silence(text, out_base.with_suffix(".wav")), None


def synthesize(text: str, out_base: Path, cfg: dict) -> Path:
    """Compatível com o uso antigo: só o caminho do áudio."""
    return synthesize_timed(text, out_base, cfg)[0]


# ------------------------------------------------------------------ sem voz
def _silence(text: str, out: Path) -> Path:
    words = max(1, len(text.split()))
    seconds = max(2.5, words / 2.6)  # ~156 palavras/min
    rate = 24000
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return out


# ------------------------------------------------------------------ Edge TTS
def _edge(text: str, out: Path, cfg: dict):
    try:
        import edge_tts
    except ImportError as e:
        raise TTSError("Pacote 'edge-tts' não instalado (pip install edge-tts).") from e

    voice = cfg.get("edge_voice", "pt-BR-AntonioNeural")
    rate = cfg.get("edge_rate", "+0%")
    marks: list[tuple[str, float, float]] = []

    async def go():
        try:  # versões novas: pede marcas por palavra
            comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        except TypeError:  # versões antigas já mandam por palavra
            comm = edge_tts.Communicate(text, voice, rate=rate)
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                kind = chunk.get("type")
                if kind == "audio":
                    f.write(chunk["data"])
                elif kind in ("WordBoundary", "SentenceBoundary"):
                    # offset/duração vêm em unidades de 100 ns
                    marks.append((chunk.get("text", ""), chunk["offset"] / 1e7, chunk["duration"] / 1e7))

    try:
        asyncio.run(go())
    except Exception as e:
        raise TTSError(f"Edge TTS falhou (precisa de internet): {e}") from e
    if not out.exists() or out.stat().st_size == 0:
        raise TTSError("Edge TTS não gerou áudio.")
    return out, (marks or None)


# ------------------------------------------------------------------ Voz do Windows (SAPI)
def sapi_voices() -> list[tuple[str, str]]:
    try:
        import pyttsx3

        eng = pyttsx3.init()
        return [(v.id, v.name) for v in eng.getProperty("voices")]
    except Exception:
        return []


def _sapi(text: str, out: Path, cfg: dict) -> Path:
    try:
        import pyttsx3
    except ImportError as e:
        raise TTSError("Pacote 'pyttsx3' não instalado (pip install pyttsx3).") from e
    try:
        eng = pyttsx3.init()
        voice_id = cfg.get("sapi_voice", "")
        if voice_id:
            eng.setProperty("voice", voice_id)
        else:  # tenta achar uma voz em português
            for v in eng.getProperty("voices"):
                langs = " ".join(str(x) for x in getattr(v, "languages", []))
                if "pt" in langs.lower() or "portug" in v.name.lower() or "maria" in v.name.lower():
                    eng.setProperty("voice", v.id)
                    break
        eng.setProperty("rate", 165)
        eng.save_to_file(text, str(out))
        eng.runAndWait()
        eng.stop()
    except Exception as e:
        raise TTSError(f"Voz do Windows falhou: {e}") from e
    if not out.exists() or out.stat().st_size < 100:
        raise TTSError("A voz do Windows não gerou áudio (instale uma voz em português nas configurações do Windows).")
    return out


# ------------------------------------------------------------------ Piper (IA local)
def piper_default_model_path() -> Path:
    from .config import CONFIG_DIR

    return CONFIG_DIR / "piper" / "pt_BR-faber-medium.onnx"


def download_piper_model(progress=lambda frac: None) -> Path:
    """Baixa a voz pt_BR-faber-medium (~60 MB) do repositório oficial do Piper."""
    dest = piper_default_model_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    for url, path in ((PIPER_MODEL_URL, dest), (PIPER_MODEL_URL + ".json", Path(str(dest) + ".json"))):
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        progress(done / total)
    return dest


_piper_cache: dict = {}


def _piper(text: str, out: Path, cfg: dict) -> Path:
    try:
        from piper import PiperVoice
    except ImportError as e:
        raise TTSError("Pacote 'piper-tts' não instalado (pip install piper-tts).") from e
    model = cfg.get("piper_model") or str(piper_default_model_path())
    if not Path(model).exists():
        raise TTSError("Modelo do Piper não encontrado. Baixe-o em Configurações → Narração.")
    try:
        voice = _piper_cache.get(model)
        if voice is None:
            voice = PiperVoice.load(model)
            _piper_cache[model] = voice
        with wave.open(str(out), "wb") as wf:
            if hasattr(voice, "synthesize_wav"):  # piper-tts >= 1.3
                voice.synthesize_wav(text, wf)
            else:  # versões antigas
                voice.synthesize(text, wf)
    except Exception as e:
        raise TTSError(f"Piper falhou: {e}") from e
    return out


# ------------------------------------------------------------------ ElevenLabs
def elevenlabs_voices(api_key: str) -> list[tuple[str, str]]:
    r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": api_key}, timeout=20)
    if r.status_code == 401:
        raise TTSError("Chave da ElevenLabs inválida.")
    r.raise_for_status()
    return [(v["voice_id"], v["name"]) for v in r.json().get("voices", [])]


def _elevenlabs(text: str, out: Path, cfg: dict):
    import base64

    from .align import entries_from_chars

    key = cfg.get("elevenlabs_key", "").strip()
    if not key:
        raise TTSError("Informe a chave da ElevenLabs em Configurações → Narração.")
    voice_id = cfg.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
    body = {"text": text, "model_id": cfg.get("elevenlabs_model", "eleven_multilingual_v2")}
    base = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    # 1) com marcas de tempo por caractere (legenda precisa)
    try:
        r = requests.post(
            base + "/with-timestamps",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        if r.status_code == 401:
            raise TTSError("Chave da ElevenLabs inválida ou sem créditos.")
        if r.ok:
            js = r.json()
            out.write_bytes(base64.b64decode(js["audio_base64"]))
            al = js.get("alignment") or {}
            entries = entries_from_chars(
                text,
                al.get("characters", []),
                al.get("character_start_times_seconds", []),
                al.get("character_end_times_seconds", []),
            )
            return out, entries
    except TTSError:
        raise
    except Exception:
        pass  # cai para o endpoint simples

    # 2) endpoint simples (a legenda usa a análise do áudio)
    r = requests.post(
        base,
        headers={"xi-api-key": key, "Accept": "audio/mpeg", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    if r.status_code == 401:
        raise TTSError("Chave da ElevenLabs inválida ou sem créditos.")
    if not r.ok:
        raise TTSError(f"ElevenLabs respondeu {r.status_code}: {r.text[:200]}")
    out.write_bytes(r.content)
    return out, None
