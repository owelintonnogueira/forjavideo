"""Busca de imagens: Wikimedia Commons (sem chave), Pexels (chave grátis), pasta local, fundos gerados."""
from __future__ import annotations

import html
import re
from pathlib import Path

import requests
from PIL import Image

from .util import USER_AGENT, CancelToken

HEADERS = {"User-Agent": USER_AGENT}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

SOURCES = {
    "commons": "Wikimedia Commons (grátis, sem chave)",
    "pexels": "Pexels (grátis, precisa de chave)",
    "folder": "Minha pasta de imagens",
    "generated": "Só fundos gerados",
}


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


class ImageProvider:
    def __init__(self, cfg: dict, assets_dir: Path, vertical: bool, log=print, cancel: CancelToken | None = None):
        self.cfg = cfg
        self.dir = Path(assets_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vertical = vertical
        self.log = log
        self.cancel = cancel
        self.used_urls: set[str] = set()
        self.credits: list[str] = []
        self.counter = 0
        self._folder_files: list[Path] = []
        self._net_down = False
        if cfg.get("image_source") == "folder":
            folder = Path(cfg.get("image_folder", ""))
            if folder.is_dir():
                self._folder_files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXT)
            if not self._folder_files:
                self.log("Pasta de imagens vazia ou não encontrada; usando fundos gerados.")

    # ---------------------------------------------------------------- API pública
    def get(self, query: str, seed: int = 0, fallback: str = "") -> Path:
        self.counter += 1
        if self.cancel:
            self.cancel.check()
        src = self.cfg.get("image_source", "commons")
        path: Path | None = None
        try:
            if src == "folder" and self._folder_files:
                path = self._folder_files[(self.counter - 1) % len(self._folder_files)]
            elif src in ("commons", "pexels") and not self._net_down:
                search = self._commons if src == "commons" else self._pexels
                path = search(query)
                if path is None and fallback and fallback != query:
                    path = search(fallback)
        except requests.exceptions.ConnectionError:
            self._net_down = True
            self.log("Sem conexão para buscar imagens; usando fundos gerados.")
        except Exception as e:  # nunca derruba a produção por causa de uma imagem
            self.log(f"Imagem não encontrada para “{query}” ({e}); usando fundo gerado.")
        if path is not None:
            try:
                with Image.open(path) as im:
                    im.verify()
                return path
            except Exception:
                path = None
        return self.generated_background(seed or self.counter)

    # ---------------------------------------------------------------- Commons
    def _commons(self, query: str) -> Path | None:
        tries = [query]
        words = query.split()
        if len(words) > 2:
            tries.append(" ".join(words[:2]))
        for q in tries:
            r = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrsearch": f"{q} filetype:bitmap",
                    "gsrlimit": 15,
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": 1920,
                },
                headers=HEADERS,
                timeout=20,
            )
            r.raise_for_status()
            pages = list(r.json().get("query", {}).get("pages", {}).values())
            pages.sort(key=lambda p: p.get("index", 0))
            for p in pages:
                info = (p.get("imageinfo") or [{}])[0]
                if info.get("mime") not in ("image/jpeg", "image/png"):
                    continue
                w, h = info.get("width", 0), info.get("height", 0)
                if max(w, h) < 1000 or min(w, h) < 600:
                    continue
                if not self.vertical and w < h:
                    continue
                if self.vertical and h < w * 0.8:
                    continue
                url = info.get("thumburl") or info.get("url")
                if not url or url in self.used_urls:
                    continue
                path = self._download(url)
                if path:
                    meta = info.get("extmetadata", {})
                    author = _strip_html(meta.get("Artist", {}).get("value", "")) or "autor desconhecido"
                    lic = _strip_html(meta.get("LicenseShortName", {}).get("value", "")) or "licença livre"
                    self.credits.append(
                        f"Imagem: {p.get('title', '')} — {author} — {lic} — {info.get('descriptionurl', '')}"
                    )
                    self.used_urls.add(url)
                    return path
        return None

    # ---------------------------------------------------------------- Pexels
    def _pexels(self, query: str) -> Path | None:
        key = self.cfg.get("pexels_key", "").strip()
        if not key:
            raise RuntimeError("chave do Pexels não informada")
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 10, "orientation": "portrait" if self.vertical else "landscape"},
            headers={"Authorization": key, "User-Agent": USER_AGENT},
            timeout=20,
        )
        if r.status_code == 401:
            raise RuntimeError("chave do Pexels inválida")
        r.raise_for_status()
        for ph in r.json().get("photos", []):
            url = ph["src"].get("large2x") or ph["src"].get("large")
            if not url or url in self.used_urls:
                continue
            path = self._download(url)
            if path:
                self.used_urls.add(url)
                self.credits.append(f"Foto: {ph.get('photographer', '')} — Pexels — {ph.get('url', '')}")
                return path
        return None

    # ---------------------------------------------------------------- download / fundo gerado
    def _download(self, url: str) -> Path | None:
        ext = ".png" if url.lower().split("?")[0].endswith(".png") else ".jpg"
        dest = self.dir / f"img_{self.counter:03d}{ext}"
        r = requests.get(url, headers=HEADERS, timeout=60)
        if not r.ok or len(r.content) < 5000:
            return None
        dest.write_bytes(r.content)
        return dest

    def generated_background(self, seed: int) -> Path:
        """Fundo escuro com brilho laranja (nunca falha, funciona offline)."""
        from .draw import glow_background

        w, h = (1080, 1920) if self.vertical else (1920, 1080)
        dest = self.dir / f"bg_{seed:03d}.jpg"
        glow_background(w, h, seed).save(dest, quality=88)
        return dest
