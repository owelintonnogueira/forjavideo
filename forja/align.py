"""Tempo de cada palavra falada (para legendas e cortes precisos).

Ordem de preferência:
  1. marcas de tempo da própria voz (Edge TTS / ElevenLabs) — mapeadas letra a letra;
  2. análise da energia do áudio (onde há fala e onde há pausa);
  3. proporcional ao tamanho das palavras (último recurso, p.ex. narração desligada).
"""
from __future__ import annotations

import bisect
import subprocess
import sys
from array import array
from dataclasses import dataclass
from operator import mul
from pathlib import Path

from .util import _popen_flags, audio_duration, ffmpeg_exe

FRAME_S = 0.01  # resolução da análise de energia: 10 ms


@dataclass
class Timing:
    words: list[tuple[str, float, float]]  # (palavra, início, fim) em segundos, no áudio original
    start: float  # início útil do áudio (depois do silêncio inicial)
    end: float  # fim útil do áudio (antes do silêncio final)
    source: str  # "voz" | "energia" | "proporcional"


def letters(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _weight(word: str) -> float:
    return max(1, len(letters(word))) + 0.6


# ------------------------------------------------------------------ energia do áudio
def decode_pcm(path: str | Path, rate: int = 16000) -> array:
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_flags())
    a = array("h")
    a.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def frame_rms(pcm: array, rate: int = 16000) -> list[float]:
    n = int(rate * FRAME_S)
    out = []
    for i in range(0, len(pcm) - n + 1, n):
        seg = pcm[i : i + n]
        out.append((sum(map(mul, seg, seg)) / n) ** 0.5)
    return out


def _runs(mask: list[bool]) -> list[list]:
    runs: list[list] = []
    for v in mask:
        if runs and runs[-1][0] == v:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    return runs


def voiced_mask(rms: list[float]) -> list[bool]:
    if not rms:
        return []
    peak = max(rms)
    if peak < 60:  # silêncio digital
        return [False] * len(rms)
    noise = sorted(rms)[int(len(rms) * 0.10)]
    thr = max(noise * 3.0, peak * 0.05, 40.0)
    mask = [r > thr for r in rms]
    runs = _runs(mask)
    # fecha lacunas curtas (< 80 ms) entre trechos de fala: são só consoantes/respiros dentro de palavras
    for i in range(1, len(runs) - 1):
        if not runs[i][0] and runs[i][1] < 8:
            runs[i][0] = True
    # descarta estalos isolados (< 30 ms)
    for r in runs:
        if r[0] and r[1] < 3:
            r[0] = False
    out: list[bool] = []
    for v, n in runs:
        out.extend([v] * n)
    return out


def from_energy(audio_path: str | Path, words: list[str]) -> Timing | None:
    if not words:
        return None
    pcm = decode_pcm(audio_path)
    mask = voiced_mask(frame_rms(pcm))
    voiced = [i for i, m in enumerate(mask) if m]
    if len(voiced) < 8:
        return None
    start, end = voiced[0] * FRAME_S, (voiced[-1] + 1) * FRAME_S
    weights = [_weight(w) for w in words]
    total, acc, out = sum(weights), 0.0, []
    nv = len(voiced)
    for w, wt in zip(words, weights):
        k0 = min(nv - 1, int(acc / total * nv))
        acc += wt
        k1 = min(nv - 1, max(k0, int(acc / total * nv) - 1))
        out.append((w, voiced[k0] * FRAME_S, (voiced[k1] + 1) * FRAME_S))
    return Timing(out, start, end, "energia")


# ------------------------------------------------------------------ marcas da própria voz
def from_boundaries(words: list[str], entries: list[tuple[str, float, float]]) -> Timing | None:
    """entries: (texto, início, duração) em segundos — por palavra OU por frase.
    Mapeia letra a letra, então funciona com qualquer granularidade."""
    spans = []  # (letra inicial, nº de letras, início, duração)
    base = 0
    for text, s, d in entries:
        n = len(letters(text))
        if n:
            spans.append((base, n, float(s), float(d)))
            base += n
    wl = [len(letters(w)) for w in words]
    total_words = sum(wl)
    if not spans or total_words == 0 or abs(base - total_words) > max(3, 0.06 * total_words):
        return None
    scale = base / total_words
    bases = [b for b, _, _, _ in spans]

    def t_start(p: float) -> float:
        p = min(max(p, 0.0), base - 1e-6)
        b, n, s, d = spans[bisect.bisect_right(bases, p) - 1]
        return s + d * (p - b) / n

    def t_end(p: float) -> float:
        p = min(max(p, 1e-6), base)
        b, n, s, d = spans[max(0, bisect.bisect_left(bases, p) - 1)]
        return s + d * min(1.0, (p - b) / n)

    out, pos, last_end = [], 0, 0.0
    for w, n in zip(words, wl):
        if n == 0:
            out.append((w, last_end, last_end))
            continue
        a, b = pos * scale, (pos + n) * scale
        pos += n
        st, en = t_start(a), t_end(b)
        out.append((w, st, max(en, st + 0.03)))
        last_end = out[-1][2]
    return Timing(out, out[0][1], out[-1][2], "voz")


# ------------------------------------------------------------------ juntando tudo
def analyze(audio_path: str | Path, text: str, entries: list[tuple[str, float, float]] | None = None) -> Timing:
    words = text.split()
    dur = audio_duration(audio_path)
    voice = from_boundaries(words, entries) if entries else None
    try:
        energy = from_energy(audio_path, words)
    except Exception:
        energy = None
    if voice is None and energy is None:  # último recurso
        weights = [_weight(w) for w in words]
        total, acc, out = sum(weights), 0.0, []
        for w, wt in zip(words, weights):
            out.append((w, dur * acc / total, dur * (acc + wt) / total))
            acc += wt
        return Timing(out, 0.0, dur, "proporcional")
    base = voice or energy
    assert base is not None
    start, end = base.start, base.end
    if energy is not None:  # o silêncio inicial/final real vem do áudio
        start = min(start, energy.start) if voice else energy.start
        end = max(end, energy.end) if voice else energy.end
    start = max(0.0, start - 0.05)
    end = min(dur, end + 0.10)
    return Timing(base.words, start, max(end, start + 0.3), base.source)


# ------------------------------------------------------------------ conversão de formatos dos motores
def entries_from_chars(text: str, chars: list[str], starts: list[float], ends: list[float]) -> list[tuple[str, float, float]] | None:
    """ElevenLabs devolve tempo por caractere; agrupa por palavra."""
    if not chars or len(chars) != len(starts) or len(starts) != len(ends):
        return None
    out: list[tuple[str, float, float]] = []
    cur, s0, e0 = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                out.append((cur, s0, e0 - s0))
                cur = ""
            continue
        if not cur:
            s0 = s
        cur += ch
        e0 = e
    if cur:
        out.append((cur, s0, e0 - s0))
    return out or None
