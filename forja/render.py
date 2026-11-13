"""Montagem do vídeo com ffmpeg: cenas com zoom lento, legendas, cartões de impacto, música."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from . import draw as D
from .util import CancelToken, run_ffmpeg

FPS = 30
SCALE_UP = 1.5  # imagem de entrada maior que a saída, para o zoom não pixelar
PAD_END = 0.35  # silêncio ao fim de cada cena


def canvas_size(fmt: str, resolution: str) -> tuple[int, int]:
    short, long_ = (720, 1280) if resolution == "720p" else (1080, 1920)
    return (short, long_) if fmt == "vertical" else (long_, short)


# ------------------------------------------------------------------ legendas
def subtitle_chunks(text: str, duration: float, max_words: int = 4, max_chars: int = 26):
    words = text.split()
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(cur + [w])) > max_chars):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    weights = [max(1, sum(len(w) for w in g) + len(g)) for g in groups]
    total = sum(weights)
    t, out = 0.0, []
    for g, wgt in zip(groups, weights):
        d = duration * wgt / total
        out.append((t, t + d, g))
        t += d
    return out


def render_subtitle_png(words: list[str], w: int, h: int, path: Path) -> tuple[int, int]:
    """Gera um PNG recortado com a legenda. Retorna (x, y) para posicioná-lo no quadro."""
    vertical = h > w
    base = min(w, h)
    size = int(base * (0.085 if vertical else 0.072))
    font = D.load_font(size, "Bold")
    tmp = Image.new("RGBA", (10, 10))
    dr = ImageDraw.Draw(tmp)
    max_w = int(w * 0.88)
    words_u = [x.upper() for x in words]
    lines = D.wrap_words(dr, words_u, font, max_w)
    hi = D.longest_word_index(words_u)
    stroke = max(3, size // 9)
    line_h = int(size * 1.2)
    img_w = max(D.text_width(dr, " ".join(l), font) for l in lines) + stroke * 4
    img_h = line_h * len(lines) + stroke * 4
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    idx = 0
    for li, line in enumerate(lines):
        cols = []
        for _ in line:
            cols.append(D.ORANGE if idx == hi else D.WHITE)
            idx += 1
        D.draw_line_colored(d, (img_w // 2, stroke * 2 + li * line_h), line, font, cols, stroke=stroke, anchor_x="m")
    x = (w - img_w) // 2
    y = int(h * (0.70 if vertical else 0.80))
    img.save(path)
    return x, y


# ------------------------------------------------------------------ imagens de apoio
def make_shade(w: int, h: int, path: Path) -> None:
    """Escurece as bordas e a parte de baixo para a legenda ficar legível."""
    layer = D.vertical_gradient_rgba((w, h), 0, 185, start=0.45)
    vig = D.vignette((w, h), 0.55)
    black = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    black.putalpha(vig)
    Image.alpha_composite(layer, black).save(path)


def prepare_background(src: Path, w: int, h: int, dest: Path, idx: int) -> None:
    img = Image.open(src)
    focus = [(0.5, 0.45), (0.4, 0.5), (0.6, 0.5), (0.5, 0.35)][idx % 4]
    big = D.cover_crop(img, int(w * SCALE_UP), int(h * SCALE_UP), focus)
    big.save(dest, quality=92)


def make_impact_card(text: str, w: int, h: int, dest: Path) -> None:
    W, H = int(w * SCALE_UP), int(h * SCALE_UP)
    bg = Image.new("RGB", (W, H), (11, 11, 12))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = min(W, H) // 2
    gd.ellipse([W // 2 - r, int(H * 0.95) - r, W // 2 + r, int(H * 0.95) + r], fill=(255, 110, 0))
    from PIL import ImageFilter

    glow = glow.filter(ImageFilter.GaussianBlur(min(W, H) // 5))
    bg = Image.blend(bg, glow, 0.45)
    d = ImageDraw.Draw(bg)
    box_w, box_h = int(W * 0.78), int(H * 0.55)
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 4, int(min(W, H) * 0.16), 30)
    lh = int(font.size * 1.12)
    y = (H - lh * len(lines)) // 2
    hi_line = len(lines) - 1
    for li, line in enumerate(lines):
        cols = [D.ORANGE if li == hi_line else D.WHITE] * len(line)
        D.draw_line_colored(d, (W // 2, y + li * lh), line, font, cols, stroke=0, anchor_x="m")
    bar_w = int(W * 0.12)
    d.rectangle([W // 2 - bar_w // 2, y - int(lh * 0.35), W // 2 + bar_w // 2, y - int(lh * 0.35) + max(6, H // 120)], fill=D.ORANGE)
    bg.save(dest, quality=94)


# ------------------------------------------------------------------ cena
def render_scene(
    idx: int,
    text: str,
    kind: str,
    image: Path | None,
    audio: Path,
    audio_dur: float,
    work: Path,
    w: int,
    h: int,
    shade: Path,
    out: Path,
    cancel: CancelToken | None = None,
) -> float:
    dur = audio_dur + PAD_END
    frames = max(2, int(round(dur * FPS)))
    bg = work / f"bg_{idx:03d}.jpg"
    if kind == "impact" or image is None:
        make_impact_card(text, w, h, bg)
    else:
        prepare_background(image, w, h, bg, idx)

    # legendas (cartões de impacto já mostram o texto, então não duplicam)
    chunks = []
    if kind != "impact":
        for ci, (a, b, g) in enumerate(subtitle_chunks(text, audio_dur)):
            png = work / f"sub_{idx:03d}_{ci:02d}.png"
            x, y = render_subtitle_png(g, w, h, png)
            chunks.append((png, x, y, a, b))
    # estende o último trecho até o fim da cena
    if chunks:
        p, x, y, a, b = chunks[-1]
        chunks[-1] = (p, x, y, a, dur)

    motions = [
        ("1+0.12*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
        ("1.12-0.12*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
        ("1.10", "(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2"),
        ("1.10", "(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2"),
    ]
    z, xe, ye = [m.format(n=frames) for m in motions[idx % 4]]
    if kind == "impact":
        z, xe, ye = f"1+0.05*on/{frames}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"

    inputs = ["-i", str(bg), "-loop", "1", "-i", str(shade)]
    for png, *_ in chunks:
        inputs += ["-loop", "1", "-i", str(png)]
    inputs += ["-i", str(audio)]
    audio_idx = 2 + len(chunks)

    fc = [f"[0:v]zoompan=z='{z}':x='{xe}':y='{ye}':d={frames}:s={w}x{h}:fps={FPS}[z]"]
    last = "z"
    if kind != "impact":
        fc.append(f"[{last}][1:v]overlay=0:0:format=auto[s]")
        last = "s"
    for i, (png, x, y, a, b) in enumerate(chunks):
        fc.append(f"[{last}][{2 + i}:v]overlay={x}:{y}:format=auto:enable='between(t,{a:.3f},{b:.3f})'[c{i}]")
        last = f"c{i}"
    fc.append(f"[{last}]format=yuv420p[vout]")
    fc.append(f"[{audio_idx}:a]aresample=48000,apad=pad_dur={PAD_END},aformat=channel_layouts=stereo[aout]")

    run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(fc),
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
