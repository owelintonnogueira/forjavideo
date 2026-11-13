"""Montagem do vídeo com ffmpeg: planos curtos com zoom/transições, legenda palavra por palavra, cartões de impacto, música."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import draw as D
from .align import Timing
from .util import CancelToken, run_ffmpeg

FPS = 30
SCALE_UP = 1.5  # imagem de entrada maior que a saída, para o zoom não pixelar
TAIL = 0.12  # respiro ao fim de cada cena (o silêncio inicial/final da voz é cortado)
SUB_LEAD = 0.04  # a legenda aparece um tico antes da palavra, o olho percebe como "em cima"

# ritmo da edição: duração média de cada imagem, duração da transição e velocidade da voz (Edge)
PACES = {
    "calm": {"shot": 4.0, "trans": 0.30, "rate": "+0%", "label": "Calmo (troca de imagem a cada ~4 s)"},
    "dynamic": {"shot": 2.5, "trans": 0.20, "rate": "+8%", "label": "Dinâmico (a cada ~2,5 s)"},
    "fast": {"shot": 1.8, "trans": 0.15, "rate": "+16%", "label": "Acelerado (a cada ~1,8 s)"},
}
TRANSITIONS = {
    "calm": ["fade"],
    "dynamic": ["fade", "slideleft", "slideright", "wipeleft", "wiperight", "circleopen", "smoothleft"],
    "fast": ["fade", "slideleft", "slideright", "wipeleft", "wiperight", "circleopen", "smoothright", "radial"],
}
# zoom / pan por plano: (z, x, y), {n} = nº de quadros do plano
MOTIONS = [
    ("1+0.16*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),  # zoom in centrado
    ("1.16-0.16*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),  # zoom out
    ("1.15", "(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2"),  # pan para a esquerda
    ("1.15", "(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2"),  # pan para a direita
    ("1+0.18*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)*0.2"),  # zoom in pelo alto
    ("1+0.18*on/{n}", "(iw-iw/zoom)*0.8", "(ih-ih/zoom)*0.8"),  # zoom in para o canto
]


def canvas_size(fmt: str, resolution: str) -> tuple[int, int]:
    short, long_ = (720, 1280) if resolution == "720p" else (1080, 1920)
    return (short, long_) if fmt == "vertical" else (long_, short)


# ------------------------------------------------------------------ planejamento da cena
@dataclass
class ScenePlan:
    dur: float  # duração da cena (já sem o silêncio inicial/final da voz)
    words: list[tuple[str, float, float]]  # palavras com tempo relativo ao início da cena
    cuts: list[float]  # [0, c1, ..., dur] — cada intervalo é um plano com uma imagem
    trans: float  # duração da transição entre planos

    @property
    def shots(self) -> int:
        return len(self.cuts) - 1


def plan_scene(kind: str, timing: Timing, pace: str) -> ScenePlan:
    a0, a1 = timing.start, timing.end
    dur = max(0.8, (a1 - a0) + TAIL)
    words = [(w, max(0.0, s - a0), max(0.0, e - a0)) for w, s, e in timing.words]
    p = PACES.get(pace, PACES["dynamic"])
    if kind == "impact":
        return ScenePlan(dur, words, [0.0, dur], p["trans"])
    k = max(1, int(round(dur / p["shot"])))
    k = min(k, max(1, int(dur / 1.1)))
    cuts = [dur * i / k for i in range(k + 1)]
    starts = [w[1] for w in words]
    for i in range(1, k):  # corta junto com o início de uma palavra (o corte "cai" na fala)
        if not starts:
            break
        best = min(starts, key=lambda s_: abs(s_ - cuts[i]))
        if abs(best - cuts[i]) <= 0.5:
            cuts[i] = best
    keep = [0.0]
    for c in cuts[1:-1]:  # nenhum plano com menos de ~1 s
        if c - keep[-1] >= 1.0 and dur - c >= 1.0:
            keep.append(c)
    keep.append(dur)
    return ScenePlan(dur, words, keep, p["trans"])


# ------------------------------------------------------------------ legendas palavra por palavra
def _ends_phrase(word: str) -> bool:
    return word.rstrip("\"”')»").endswith((",", ".", ";", ":", "!", "?", "…"))


def group_chunks(words, max_words: int, max_chars: int):
    chunks, cur = [], []
    for w, s, e in words:
        if cur:
            too_long = len(cur) >= max_words or len(" ".join([c[0] for c in cur] + [w])) > max_chars
            if too_long or _ends_phrase(cur[-1][0]) or (s - cur[-1][2]) > 0.4:
                chunks.append(cur)
                cur = []
        cur.append((w, s, e))
    if cur:
        chunks.append(cur)
    return chunks


def subtitle_states(words, dur: float, vertical: bool):
    """Lista de (palavras do trecho, índice da palavra falada agora, início, fim)."""
    chunks = group_chunks(words, 3 if vertical else 4, 20 if vertical else 28)
    states = []
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0][1] if ci + 1 < len(chunks) else None
        last_end = ch[-1][2]
        if nxt is not None and nxt - last_end <= 0.6:
            chunk_end = max(nxt - SUB_LEAD, last_end)  # emenda direto no próximo trecho
        else:
            chunk_end = min(dur, last_end + 0.35)  # pausa: some logo depois da última palavra
        names = [c[0] for c in ch]
        for j, (_, s, _) in enumerate(ch):
            t0 = max(0.0, s - SUB_LEAD)
            t1 = max(0.0, ch[j + 1][1] - SUB_LEAD) if j + 1 < len(ch) else chunk_end
            if t1 - t0 >= 0.02:
                states.append((names, j, t0, t1))
    return states


def render_subtitle_png(words: list[str], active: int, w: int, h: int, path: Path) -> tuple[int, int]:
    """PNG recortado com o trecho da legenda; a palavra falada agora fica em laranja."""
    vertical = h > w
    base = min(w, h)
    size = int(base * (0.088 if vertical else 0.076))
    font = D.load_font(size, "Bold")
    tmp = Image.new("RGBA", (10, 10))
    dr = ImageDraw.Draw(tmp)
    words_u = [x.upper() for x in words]
    lines = D.wrap_words(dr, words_u, font, int(w * 0.88))
    stroke = max(3, size // 9)
    line_h = int(size * 1.2)
    img_w = max(D.text_width(dr, " ".join(l), font) for l in lines) + stroke * 4
    img = Image.new("RGBA", (img_w, line_h * len(lines) + stroke * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    idx = 0
    for li, line in enumerate(lines):
        cols = []
        for _ in line:
            cols.append(D.ORANGE if idx == active else D.WHITE)
            idx += 1
        D.draw_line_colored(d, (img_w // 2, stroke * 2 + li * line_h), line, font, cols, stroke=stroke, anchor_x="m")
    img.save(path)
    return (w - img_w) // 2, int(h * (0.70 if vertical else 0.80))


# ------------------------------------------------------------------ imagens de apoio
def make_shade(w: int, h: int, path: Path) -> None:
    """Escurece as bordas e a parte de baixo para a legenda ficar legível."""
    layer = D.vertical_gradient_rgba((w, h), 0, 185, start=0.45)
    vig = D.vignette((w, h), 0.55)
    black = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    black.putalpha(vig)
    Image.alpha_composite(layer, black).save(path)


def prepare_background(src: Path, w: int, h: int, dest: Path, variant: int) -> None:
    img = Image.open(src)
    focus = [(0.5, 0.45), (0.35, 0.5), (0.65, 0.5), (0.5, 0.3), (0.5, 0.7)][variant % 5]
    D.cover_crop(img, int(w * SCALE_UP), int(h * SCALE_UP), focus).save(dest, quality=92)


def make_impact_card(text: str, w: int, h: int, dest: Path) -> None:
    W, H = int(w * SCALE_UP), int(h * SCALE_UP)
    bg = Image.new("RGB", (W, H), (11, 11, 12))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = min(W, H) // 2
    gd.ellipse([W // 2 - r, int(H * 0.95) - r, W // 2 + r, int(H * 0.95) + r], fill=(255, 110, 0))
    glow = glow.filter(ImageFilter.GaussianBlur(min(W, H) // 5))
    bg = Image.blend(bg, glow, 0.45)
    d = ImageDraw.Draw(bg)
    box_w, box_h = int(W * 0.78), int(H * 0.55)
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 4, int(min(W, H) * 0.16), 30)
    lh = int(font.size * 1.12)
    y = (H - lh * len(lines)) // 2
    for li, line in enumerate(lines):
        cols = [D.ORANGE if li == len(lines) - 1 else D.WHITE] * len(line)
        D.draw_line_colored(d, (W // 2, y + li * lh), line, font, cols, stroke=0, anchor_x="m")
    bar_w = int(W * 0.12)
    d.rectangle(
        [W // 2 - bar_w // 2, y - int(lh * 0.35), W // 2 + bar_w // 2, y - int(lh * 0.35) + max(6, H // 120)], fill=D.ORANGE
    )
    bg.save(dest, quality=94)


# ------------------------------------------------------------------ cena
def render_scene(
    idx: int,
    text: str,
    kind: str,
    plan: ScenePlan,
    images: list[Path],
    audio: Path,
    timing: Timing,
    work: Path,
    w: int,
    h: int,
    shade: Path,
    out: Path,
    pace: str = "dynamic",
    cancel: CancelToken | None = None,
) -> float:
    dur, cuts, tr = plan.dur, plan.cuts, plan.trans
    k = plan.shots
    rng = random.Random(idx * 7919 + 13)

    # plano de fundo de cada tomada
    bgs: list[Path] = []
    for i in range(k):
        bg = work / f"bg_{idx:03d}_{i:02d}.jpg"
        if kind == "impact" or not images:
            make_impact_card(text, w, h, bg)
        else:
            prepare_background(images[i % len(images)], w, h, bg, idx * 3 + i)
        bgs.append(bg)

    # legendas: um PNG por palavra falada (a palavra atual fica em laranja)
    subs: list[tuple[Path, int, int, float, float]] = []
    if kind != "impact":
        for si, (names, active, t0, t1) in enumerate(subtitle_states(plan.words, dur, h > w)):
            png = work / f"sub_{idx:03d}_{si:03d}.png"
            x, y = render_subtitle_png(names, active, w, h, png)
            subs.append((png, x, y, t0, t1))

    inputs: list[str] = []
    for bg in bgs:
        inputs += ["-i", str(bg)]
    inputs += ["-loop", "1", "-i", str(shade)]
    shade_i = k
    for png, *_ in subs:
        inputs += ["-loop", "1", "-i", str(png)]
    inputs += ["-i", str(audio)]
    audio_i = k + 1 + len(subs)

    fc: list[str] = []
    for i in range(k):
        n = int(math.ceil(((cuts[i + 1] - cuts[i]) + (tr / 2 if i > 0 else 0) + (tr / 2 if i < k - 1 else 0)) * FPS)) + 1
        if kind == "impact":
            z, xe, ye = f"1+0.05*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        else:
            z, xe, ye = [m.format(n=n) for m in MOTIONS[(idx * 5 + i * 2 + i // 3) % len(MOTIONS)]]
        fc.append(
            f"[{i}:v]zoompan=z='{z}':x='{xe}':y='{ye}':d={n}:s={w}x{h}:fps={FPS},format=yuv420p,setsar=1[v{i}]"
        )
    last = "v0"
    names = TRANSITIONS.get(pace, TRANSITIONS["dynamic"])
    for i in range(1, k):  # transição centrada no corte
        fc.append(
            f"[{last}][v{i}]xfade=transition={rng.choice(names)}:duration={tr:.3f}:offset={cuts[i] - tr / 2:.3f}[x{i}]"
        )
        last = f"x{i}"
    if kind != "impact":
        fc.append(f"[{last}][{shade_i}:v]overlay=0:0:format=auto[s]")
        last = "s"
    for si, (png, x, y, t0, t1) in enumerate(subs):
        fc.append(f"[{last}][{k + 1 + si}:v]overlay={x}:{y}:format=auto:enable='gte(t,{t0:.3f})*lt(t,{t1:.3f})'[c{si}]")
        last = f"c{si}"
    fc.append(f"[{last}]scale=out_range=tv:out_color_matrix=bt709,format=yuv420p[vout]")
    fc.append(
        f"[{audio_i}:a]atrim=start={timing.start:.3f}:end={timing.end:.3f},asetpts=PTS-STARTPTS,"
        f"aresample=48000,apad=pad_dur={TAIL},aformat=channel_layouts=stereo[aout]"
    )

    script = work / f"filtro_{idx:03d}.txt"  # em arquivo: a linha de comando do Windows tem limite de tamanho
    script.write_text(";\n".join(fc), encoding="utf-8")
    run_ffmpeg(
        [
            *inputs,
            "-filter_complex_script",
            str(script),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            f"{dur:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-r",
            str(FPS),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(out),
        ],
        cancel,
    )
    return dur


# ------------------------------------------------------------------ montagem final
def concat_scenes(files: list[Path], out: Path, cancel: CancelToken | None = None) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)], cancel)


def add_music(video: Path, music: Path, volume: float, out: Path, cancel: CancelToken | None = None) -> None:
    run_ffmpeg(
        [
            "-i",
            str(video),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            f"[1:a]volume={volume:.3f}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        cancel,
    )


def finalize_without_music(video: Path, out: Path, cancel: CancelToken | None = None) -> None:
    run_ffmpeg(["-i", str(video), "-c", "copy", "-movflags", "+faststart", str(out)], cancel)
