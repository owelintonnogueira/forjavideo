"""Thumbnails em 3 estilos (laranja e preto): horizontal 1280×720 ou vertical 1080×1920."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from . import draw as D

SIZE_H = (1280, 720)
SIZE_V = (1080, 1920)
STYLES = {
    "impacto": "Impacto (texto grande sobre a imagem)",
    "centro": "Centro (texto centralizado com moldura)",
    "dividido": "Dividido (painel preto + imagem)",
}


def thumb_size(vertical: bool) -> tuple[int, int]:
    return SIZE_V if vertical else SIZE_H


def _hgrad(size, a_left: int, a_right: int, start: float = 0.0, end: float = 1.0) -> Image.Image:
    """Camada preta RGBA com transparência variando da esquerda para a direita."""
    w, h = size
    row = Image.new("L", (w, 1), 0)
    px = row.load()
    x0, x1 = int(w * start), int(w * end)
    for x in range(w):
        if x <= x0:
            a = a_left
        elif x >= x1:
            a = a_right
        else:
            a = int(a_left + (a_right - a_left) * (x - x0) / max(1, x1 - x0))
        px[x, 0] = a
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.putalpha(row.resize((w, h)))
    return layer


def _punch(img: Image.Image, brightness: float = 0.85) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Color(img).enhance(1.30)
    return ImageEnhance.Brightness(img).enhance(brightness)


def _background(bg: Path | None, size: tuple[int, int], seed: int) -> Image.Image:
    if bg and Path(bg).exists():
        try:
            return D.cover_crop(Image.open(bg), size[0], size[1])
        except Exception:
            pass
    return D.glow_background(size[0], size[1], seed)


def _mark_words(lines: list[list[str]], hi: int) -> list[list[tuple]]:
    idx, out = 0, []
    for line in lines:
        cols = []
        for _ in line:
            cols.append(D.ORANGE if idx == hi else D.WHITE)
            idx += 1
        out.append(cols)
    return out


# ------------------------------------------------------------------ estilos
def _style_impacto(text: str, base: Image.Image, size: tuple[int, int]) -> Image.Image:
    W, H = size
    vertical = H > W
    u = min(W, H) / 720
    img = _punch(base, 0.8).convert("RGBA")
    if vertical:  # degradê de baixo para cima
        img = Image.alpha_composite(img, D.vertical_gradient_rgba((W, H), 0, 235, 0.35))
    else:  # degradê da esquerda para a direita
        img = Image.alpha_composite(img, _hgrad((W, H), 235, 0, 0.0, 0.85))
        img = Image.alpha_composite(img, D.vertical_gradient_rgba((W, H), 0, 150, 0.55))
    d = ImageDraw.Draw(img)
    box_w = int(W * (0.84 if vertical else 0.62))
    box_h = int(H * (0.42 if vertical else 0.72))
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 5 if vertical else 4, int(170 * u), int(54 * u))
    lh = int(font.size * 1.1)
    total_h = lh * len(lines)
    x = int(78 * u)
    y = (H - total_h - int(H * 0.09)) if vertical else ((H - total_h) // 2 + int(H * 0.04))
    hi = D.longest_word_index([w for l in lines for w in l])
    for li, (line, cols) in enumerate(zip(lines, _mark_words(lines, hi))):
        D.draw_line_colored(d, (x, y + li * lh), line, font, cols, stroke=max(5, font.size // 14))
    bar = int(14 * u)
    d.rectangle([int(40 * u), y + 8, int(40 * u) + bar, y + total_h - 8], fill=D.ORANGE)
    return img.convert("RGB")


def _style_centro(text: str, base: Image.Image, size: tuple[int, int]) -> Image.Image:
    W, H = size
    vertical = H > W
    u = min(W, H) / 720
    img = _punch(base, 0.7).convert("RGBA")
    vig = D.vignette((W, H), 0.95)
    black = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    black.putalpha(vig)
    img = Image.alpha_composite(img, D.vertical_gradient_rgba((W, H), 70, 70))
    img = Image.alpha_composite(img, black)
    d = ImageDraw.Draw(img)
    box_w, box_h = int(W * 0.84), int(H * (0.55 if vertical else 0.70))
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 5 if vertical else 4, int(160 * u), int(54 * u))
    lh = int(font.size * 1.12)
    y = (H - lh * len(lines)) // 2
    for li, line in enumerate(lines):
        col = D.ORANGE if li % 2 == 1 or len(lines) == 1 else D.WHITE
        D.draw_line_colored(
            d, (W // 2, y + li * lh), line, font, [col] * len(line), stroke=max(6, font.size // 12), anchor_x="m"
        )
    d.rectangle([0, 0, W - 1, H - 1], outline=D.ORANGE, width=int(14 * u))
    return img.convert("RGB")


def _style_dividido(text: str, base: Image.Image, size: tuple[int, int]) -> Image.Image:
    W, H = size
    vertical = H > W
    u = min(W, H) / 720
    img = _punch(base, 0.95).convert("RGBA")
    d = ImageDraw.Draw(img)
    if vertical:  # imagem em cima, painel preto embaixo
        top_l, top_r = int(H * 0.56), int(H * 0.48)
        edge = [(0, top_l), (W, top_r), (W, H), (0, H)]
        d.polygon([(0, top_l - int(14 * u)), (W, top_r - int(14 * u)), (W, H), (0, H)], fill=D.ORANGE)
        d.polygon(edge, fill=(11, 11, 12))
        box_w, box_h = int(W * 0.86), int((H - top_l) * 0.78)
        font, lines = D.fit_text(d, text.upper(), box_w, box_h, 4, int(130 * u), int(44 * u))
        lh = int(font.size * 1.1)
        y = top_l + ((H - top_l) - lh * len(lines)) // 2 + int(10 * u)
        x = int(W * 0.07)
    else:  # imagem à direita, painel preto à esquerda
        edge = [(0, 0), (700, 0), (590, H), (0, H)]
        d.polygon([(edge[0][0] + 14, 0), (edge[1][0] + 14, 0), (edge[2][0] + 14, H), (edge[3][0], H)], fill=D.ORANGE)
        d.polygon(edge, fill=(11, 11, 12))
        box_w, box_h = 520, int(H * 0.74)
        font, lines = D.fit_text(d, text.upper(), box_w, box_h, 5, 130, 44)
        lh = int(font.size * 1.1)
        y = (H - lh * len(lines)) // 2
        x = 50
    for li, line in enumerate(lines):
        col = D.ORANGE if li == len(lines) - 1 else D.WHITE
        D.draw_line_colored(d, (x, y + li * lh), line, font, [col] * len(line), stroke=0)
    return img.convert("RGB")


_RENDER = {"impacto": _style_impacto, "centro": _style_centro, "dividido": _style_dividido}


def make_thumbnail(text: str, bg: Path | None, style: str, out: Path, seed: int = 0, vertical: bool = False) -> Path:
    size = thumb_size(vertical)
    base = _background(bg, size, seed)
    img = _RENDER[style](text, base, size)
    out = Path(out)
    img.save(out, quality=93, optimize=True)
    return out


def make_thumbnails(
    text: str,
    backgrounds: list[Path],
    out_dir: Path,
    styles: list[str] | None = None,
    vertical: bool = False,
) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    styles = styles or list(STYLES)
    tag = "vertical" if vertical else "horizontal"
    paths = []
    for i, st in enumerate(styles):
        bg = backgrounds[i % len(backgrounds)] if backgrounds else None
        paths.append(make_thumbnail(text, bg, st, out_dir / f"thumbnail_{i + 1}_{st}_{tag}.jpg", seed=i + 1, vertical=vertical))
    return paths
