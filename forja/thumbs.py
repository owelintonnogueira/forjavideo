"""Geração de thumbnails 1280×720 em 3 estilos (laranja e preto)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from . import draw as D

TW, TH = 1280, 720
STYLES = {
    "impacto": "Impacto (texto grande embaixo à esquerda)",
    "centro": "Centro (texto centralizado com moldura)",
    "dividido": "Dividido (painel preto + imagem)",
}


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


def _background(bg: Path | None, seed: int) -> Image.Image:
    if bg and Path(bg).exists():
        try:
            return D.cover_crop(Image.open(bg), TW, TH)
        except Exception:
            pass
    return D.glow_background(TW, TH, seed)


def _style_impacto(text: str, base: Image.Image) -> Image.Image:
    img = _punch(base, 0.8).convert("RGBA")
    img = Image.alpha_composite(img, _hgrad((TW, TH), 235, 0, 0.0, 0.85))
    img = Image.alpha_composite(img, D.vertical_gradient_rgba((TW, TH), 0, 150, 0.55))
    d = ImageDraw.Draw(img)
    box_w, box_h = int(TW * 0.62), int(TH * 0.72)
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 4, 170, 54)
    lh = int(font.size * 1.1)
    total_h = lh * len(lines)
    y = (TH - total_h) // 2 + int(TH * 0.04)
    x = 78
    hi_global = D.longest_word_index([w for l in lines for w in l])
    idx = 0
    for li, line in enumerate(lines):
        cols = []
        for _ in line:
            cols.append(D.ORANGE if idx == hi_global else D.WHITE)
            idx += 1
        D.draw_line_colored(d, (x, y + li * lh), line, font, cols, stroke=max(5, font.size // 14))
    d.rectangle([40, y + 8, 54, y + total_h - 8], fill=D.ORANGE)
    return img.convert("RGB")


def _style_centro(text: str, base: Image.Image) -> Image.Image:
    img = _punch(base, 0.7).convert("RGBA")
    vig = D.vignette((TW, TH), 0.95)
    black = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    black.putalpha(vig)
    img = Image.alpha_composite(img, D.vertical_gradient_rgba((TW, TH), 70, 70))
    img = Image.alpha_composite(img, black)
    d = ImageDraw.Draw(img)
    box_w, box_h = int(TW * 0.84), int(TH * 0.70)
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 4, 160, 54)
    lh = int(font.size * 1.12)
    y = (TH - lh * len(lines)) // 2
    for li, line in enumerate(lines):
        col = D.ORANGE if li % 2 == 1 or len(lines) == 1 else D.WHITE
        D.draw_line_colored(
            d, (TW // 2, y + li * lh), line, font, [col] * len(line), stroke=max(6, font.size // 12), anchor_x="m"
        )
    b = 14
    d.rectangle([0, 0, TW - 1, TH - 1], outline=D.ORANGE, width=b)
    return img.convert("RGB")


def _style_dividido(text: str, base: Image.Image) -> Image.Image:
    img = _punch(base, 0.95).convert("RGBA")
    d = ImageDraw.Draw(img)
    edge = [(0, 0), (700, 0), (590, TH), (0, TH)]
    d.polygon([(p[0] + 14, p[1]) for p in edge[:2]] + [(edge[2][0] + 14, TH), (edge[3][0], TH)], fill=D.ORANGE)
    d.polygon(edge, fill=(11, 11, 12))
    box_w, box_h = 520, int(TH * 0.74)
    font, lines = D.fit_text(d, text.upper(), box_w, box_h, 5, 130, 44)
    lh = int(font.size * 1.1)
    y = (TH - lh * len(lines)) // 2
    for li, line in enumerate(lines):
        col = D.ORANGE if li == len(lines) - 1 else D.WHITE
        D.draw_line_colored(d, (50, y + li * lh), line, font, [col] * len(line), stroke=0)
    return img.convert("RGB")


_RENDER = {"impacto": _style_impacto, "centro": _style_centro, "dividido": _style_dividido}


def make_thumbnail(text: str, bg: Path | None, style: str, out: Path, seed: int = 0) -> Path:
    base = _background(bg, seed)
    img = _RENDER[style](text, base)
    out = Path(out)
    img.save(out, quality=93, optimize=True)
    return out


def make_thumbnails(text: str, backgrounds: list[Path], out_dir: Path, styles: list[str] | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    styles = styles or list(STYLES)
    paths = []
    for i, st in enumerate(styles):
        bg = backgrounds[i % len(backgrounds)] if backgrounds else None
        paths.append(make_thumbnail(text, bg, st, out_dir / f"thumbnail_{i + 1}_{st}.jpg", seed=i + 1))
    return paths
