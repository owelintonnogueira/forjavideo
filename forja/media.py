"""Busca de imagens: Wikimedia Commons (sem chave), Pexels (chave grátis), pasta local, fundos gerados."""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
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
        self.pool: list[Path] = []  # imagens reais já baixadas (para reaproveitar quando faltar)
        self._pool_next = 0
        self._folder_files: list[Path] = []
        self._net_down = False
        if cfg.get("image_source") == "folder":
            folder = Path(cfg.get("image_folder", ""))
            if folder.is_dir():
                self._folder_files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXT)
            if not self._folder_files:
                self.log("Pasta de imagens vazia ou não encontrada; usando fundos gerados.")

    # ---------------------------------------------------------------- API pública
    def get_many(self, queries: list[str], n: int, seed: int = 0) -> list[Path]:
        """Devolve n imagens para uma cena, tentando as buscas em ordem.
        Se faltar, reaproveita imagens já baixadas; só em último caso usa fundo gerado."""
        got: list[Path] = []
        src = self.cfg.get("image_source", "commons")
        if self.cancel:
            self.cancel.check()
        if src == "folder" and self._folder_files:
            for _ in range(n):
                got.append(self._folder_files[self.counter % len(self._folder_files)])
                self.counter += 1
            return got
        if src in ("commons", "pexels") and not self._net_down:
            seen: set[str] = set()
            for q in queries:
                if len(got) >= n:
                    break
                if not q or q.lower() in seen:
                    continue
                seen.add(q.lower())
                try:
                    got += self._search(src, q, n - len(got))
                except requests.exceptions.ConnectionError:
                    self._net_down = True
                    self.log("Sem conexão para buscar imagens; usando fundos gerados.")
                    break
                except Exception as e:  # nunca derruba a produção por causa de uma imagem
                    self.log(f"Imagem não encontrada para “{q}” ({e}).")
        for p in got:
            if p not in self.pool:
                self.pool.append(p)
        while len(got) < n:  # faltou: reaproveita imagens reais (outro corte/zoom) antes de usar fundo gerado
            if self.pool:
                got.append(self.pool[self._pool_next % len(self.pool)])
                self._pool_next += 1
            else:
                got.append(self.generated_background(seed * 10 + len(got) + 1))
        return got

    def get(self, query: str, seed: int = 0, fallback: str = "") -> Path:
        return self.get_many([query, fallback], 1, seed)[0]

    # ---------------------------------------------------------------- busca + download em paralelo
    def _search(self, src: str, query: str, n: int) -> list[Path]:
        cands = self._commons_candidates(query) if src == "commons" else self._pexels_candidates(query)
        cands = [c for c in cands if c["url"] not in self.used_urls][: max(n * 2, n + 2)]
        for c in cands:
            self.counter += 1
            c["dest"] = self.dir / f"img_{self.counter:03d}{c['ext']}"
        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(self._download, cands))
        out: list[Path] = []
        for c, ok in zip(cands, results):
            if ok and len(out) < n:
                self.used_urls.add(c["url"])
                self.credits.append(c["credit"])
                out.append(c["dest"])
        return out

    def _commons_candidates(self, query: str) -> list[dict]:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": 6,
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrlimit": 30,
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
        out = []
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
            if not url:
                continue
            meta = info.get("extmetadata", {})
            author = _strip_html(meta.get("Artist", {}).get("value", "")) or "autor desconhecido"
            lic = _strip_html(meta.get("LicenseShortName", {}).get("value", "")) or "licença livre"
            out.append(
                {
                    "url": url,
                    "ext": ".png" if url.lower().split("?")[0].endswith(".png") else ".jpg",
                    "credit": f"Imagem: {p.get('title', '')} — {author} — {lic} — {info.get('descriptionurl', '')}",
                }
            )
        return out

    def _pexels_candidates(self, query: str) -> list[dict]:
        key = self.cfg.get("pexels_key", "").strip()
        if not key:
            raise RuntimeError("chave do Pexels não informada")
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 20, "orientation": "portrait" if self.vertical else "landscape"},
            headers={"Authorization": key, "User-Agent": USER_AGENT},
            timeout=20,
        )
        if r.status_code == 401:
            raise RuntimeError("chave do Pexels inválida")
        r.raise_for_status()
        out = []
        for ph in r.json().get("photos", []):
            url = ph["src"].get("large2x") or ph["src"].get("large")
            if url:
                out.append(
                    {"url": url, "ext": ".jpg", "credit": f"Foto: {ph.get('photographer', '')} — Pexels — {ph.get('url', '')}"}
                )
        return out

    def _download(self, c: dict) -> bool:
        if self.cancel and self.cancel.cancelled:
            return False
        try:
            r = requests.get(c["url"], headers=HEADERS, timeout=60)
            if not r.ok or len(r.content) < 5000:
                return False
            c["dest"].write_bytes(r.content)
            with Image.open(c["dest"]) as im:
                im.verify()
            return True
        except Exception:
            return False

    def generated_background(self, seed: int) -> Path:
        """Fundo escuro com brilho laranja (nunca falha, funciona offline)."""
        from .draw import glow_background

        w, h = (1080, 1920) if self.vertical else (1920, 1080)
        dest = self.dir / f"bg_{seed:03d}.jpg"
        glow_background(w, h, seed).save(dest, quality=88)
        return dest
