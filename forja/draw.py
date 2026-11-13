"""Funções de desenho com Pillow: fontes, quebra de texto, recorte, degradês."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .util import font_path

ORANGE = (255, 122, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


@lru_cache(maxsize=64)
def load_font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    p = font_path(weight)
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def cover_crop(img: Image.Image, w: int, h: int, focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """Redimensiona e recorta a imagem para preencher w×h sem distorcer."""
    img = img.convert("RGB")
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = max(w, int(sw * scale + 0.5)), max(h, int(sh * scale + 0.5))
    img = img.resize((nw, nh), Image.LANCZOS)
    x = int((nw - w) * focus[0])
    y = int((nh - h) * focus[1])
    return img.crop((x, y, x + w, y + h))


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def wrap_words(draw, words: list[str], font, max_w: int) -> list[list[str]]:
    lines: list[list[str]] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and text_width(draw, trial, font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def fit_text(
    draw, text: str, box_w: int, box_h: int, max_lines: int, max_size: int, min_size: int = 20, weight: str = "Bold",
    line_gap: float = 1.08,
):
    """Acha o maior tamanho de fonte em que o texto cabe na caixa. Retorna (fonte, linhas de palavras)."""
    words = text.split()
    size = max_size
    while size >= min_size:
        font = load_font(size, weight)
        lines = wrap_words(draw, words, font, box_w)
        if len(lines) <= max_lines and len(lines) * size * line_gap <= box_h:
            if all(text_width(draw, " ".join(l), font) <= box_w for l in lines):
                return font, lines
        size -= 2
    font = load_font(min_size, weight)
    return font, wrap_words(draw, words, font, box_w)


def longest_word_index(words: list[str]) -> int:
    best, bi = -1, 0
    for i, w in enumerate(words):
        core = "".join(ch for ch in w if ch.isalnum())
        if len(core) > best:
            best, bi = len(core), i
    return bi


def draw_line_colored(
    draw, xy: tuple[int, int], words: list[str], font, colors: list[tuple], stroke: int = 0, stroke_fill=BLACK,
    anchor_x: str = "l",
):
    """Desenha uma linha com cor por palavra. anchor_x: l (esquerda), m (centro). xy = (x, y_topo)."""
    space = int(draw.textlength(" ", font=font))
    widths = [int(draw.textlength(w, font=font)) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    x, y = xy
    if anchor_x == "m":
        x -= total // 2
    for w, wd, col in zip(words, widths, colors):
        draw.text((x, y), w, font=font, fill=col, stroke_width=stroke, stroke_fill=stroke_fill)
        x += wd + space
    return total


def vignette(size: tuple[int, int], strength: float = 0.75) -> Image.Image:
    """Máscara 'L' escura nas bordas (255 = escuro)."""
    w, h = size
    small = Image.new("L", (64, 36), 0)
    px = small.load()
    for yy in range(36):
        for xx in range(64):
            dx, dy = (xx - 31.5) / 32, (yy - 17.5) / 18
            d = (dx * dx + dy * dy) ** 0.5
            v = max(0.0, min(1.0, (d - 0.55) / 0.75))
            px[xx, yy] = int(255 * strength * v)
    return small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))


def vertical_gradient_rgba(size: tuple[int, int], top_alpha: int, bottom_alpha: int, start: float = 0.0, color=(0, 0, 0)):
    """Degradê vertical de transparência. 'start' = fração da altura onde o degradê começa."""
    w, h = size
    col = Image.new("L", (1, h), 0)
    px = col.load()
    y0 = int(h * start)
    for y in range(h):
        if y < y0:
            a = top_alpha
        else:
            t = (y - y0) / max(1, h - y0)
            a = int(top_alpha + (bottom_alpha - top_alpha) * t)
        px[0, y] = a
    alpha = col.resize((w, h))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(alpha)
    return layer


def glow_background(w: int, h: int, seed: int = 0) -> Image.Image:
    """Fundo escuro com brilho laranja (funciona offline)."""
    import random

    rnd = random.Random(seed)
    base = Image.new("RGB", (w, h), (11, 11, 12))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    for _ in range(3):
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        r = rnd.randint(min(w, h) // 5, min(w, h) // 2)
        col = rnd.choice([(255, 122, 0), (255, 150, 40), (200, 80, 0)])
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 4))
    img = Image.blend(base, glow, 0.55)
    dr = ImageDraw.Draw(img)
    step = max(60, min(w, h) // 12)
    for x in range(0, w, step):
        dr.line([(x, 0), (x, h)], fill=(60, 40, 25), width=1)
    for y in range(0, h, step):
        dr.line([(0, y), (w, y)], fill=(60, 40, 25), width=1)
    return Image.blend(img, base, 0.12)
