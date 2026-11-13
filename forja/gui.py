"""Interface gráfica (tkinter) com tema escuro (laranja + preto) e claro (laranja + branco)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import config, media, pipeline, scriptgen, thumbs, tts
from .theme import THEMES
from .util import CancelToken, Cancelled

FONT = "Segoe UI" if os.name == "nt" else "Helvetica"
SILENT = False  # True no autoteste: não abre caixas de mensagem que travariam o teste

FORMATS = {"horizontal": "Horizontal 16:9 (YouTube)", "vertical": "Vertical 9:16 (Shorts / Reels / TikTok)"}
RESOLUTIONS = {"720p": "720p (mais rápido)", "1080p": "1080p (melhor qualidade)"}
SCRIPT_SOURCES = {
    "auto": "Automático (IA local se houver, senão Wikipédia)",
    "ollama": "IA local (Ollama)",
    "wikipedia": "Wikipédia (grátis, básico)",
    "manual": "Eu escrevo / colo o roteiro",
}
MINUTES = ["1", "2", "3", "5", "8", "10", "15"]
EDGE_RATES = {"-15%": "Mais devagar", "+0%": "Normal", "+10%": "Um pouco mais rápido", "+20%": "Rápido"}
ELEVEN_MODELS = ["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"]


def key_of(mapping: dict, display: str, default: str = "") -> str:
    for k, v in mapping.items():
        if v == display:
            return k
    return default


def open_path(path: str | Path) -> None:
    path = str(path)
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Não consegui abrir", str(e))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ForjaVideo — gerador de vídeos e thumbnails")
        try:
            sw, sh = int(self.winfo_screenwidth()), int(self.winfo_screenheight())
        except (TypeError, ValueError, tk.TclError):
            sw, sh = 1920, 1080
        w, h = min(1300, sw - 60), min(840, sh - 120)  # cabe até em telas 1366x768
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(1000, w), min(600, h))

        self.cfg = config.load()
        self.T = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])
        self._reg: list[tuple[tk.Misc, tuple]] = []
        self._combos: list[ttk.Combobox] = []
        self._photos: dict = {}
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_token: CancelToken | None = None
        self.last_result: pipeline.Result | None = None
        self.last_tk_error: str = ""
        self.v: dict[str, tk.Variable] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}

        self.report_callback_exception = self._on_tk_error
        self._init_style()
        self._build()
        self._load_vars()
        self.apply_theme()
        self.show_page("create")
        self.after(120, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_tk_error(self, exc, val, tb) -> None:
        import traceback

        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.CONFIG_DIR / "erro.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
        except Exception:
            pass
        self.last_tk_error = text
        if not SILENT:
            messagebox.showerror("Erro inesperado", f"{val}\n\nDetalhes em: {config.CONFIG_DIR / 'erro.log'}")

    # ================================================================== estilo / tema
    def _init_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

    def reg(self, widget, kind: str, bg: str = "panel"):
        self._reg.append((widget, (kind, bg)))
        return widget

    def apply_theme(self) -> None:
        T = self.T
        self.configure(bg=T["bg"])
        for w, (kind, bgk) in self._reg:
            try:
                self._style_widget(w, kind, bgk)
            except tk.TclError:
                pass
        s = self.style
        s.configure(
            "Forja.TCombobox",
            fieldbackground=T["input_bg"],
            background=T["panel2"],
            foreground=T["text"],
            arrowcolor=T["accent"],
            bordercolor=T["border"],
            lightcolor=T["border"],
            darkcolor=T["border"],
            selectbackground=T["input_bg"],
            selectforeground=T["text"],
            padding=4,
        )
        s.map(
            "Forja.TCombobox",
            fieldbackground=[("readonly", T["input_bg"])],
            foreground=[("readonly", T["text"])],
            selectbackground=[("readonly", T["input_bg"])],
            selectforeground=[("readonly", T["text"])],
            bordercolor=[("focus", T["accent"])],
        )
        s.configure(
            "Forja.Horizontal.TProgressbar",
            troughcolor=T["panel2"],
            background=T["accent"],
            bordercolor=T["border"],
            lightcolor=T["accent"],
            darkcolor=T["accent"],
        )
        s.configure(
            "Forja.Vertical.TScrollbar",
            troughcolor=T["bg"],
            background=T["panel2"],
            bordercolor=T["bg"],
            arrowcolor=T["accent"],
            lightcolor=T["panel2"],
            darkcolor=T["panel2"],
        )
        for cb in self._combos:  # lista suspensa dos comboboxes
            try:
                pd = str(cb.tk.call("ttk::combobox::PopdownWindow", str(cb)))
                cb.tk.call(
                    f"{pd}.f.l",
                    "configure",
                    "-background",
                    T["input_bg"],
                    "-foreground",
                    T["text"],
                    "-selectbackground",
                    T["accent"],
                    "-selectforeground",
                    T["on_accent"],
                )
            except tk.TclError:
                pass
        self._refresh_nav()
        if hasattr(self, "theme_btn"):
            self.theme_btn.configure(text="Tema: Escuro" if self.cfg["theme"] == "dark" else "Tema: Claro")

    def _style_widget(self, w, kind: str, bgk: str) -> None:
        T = self.T
        if kind == "frame":
            w.configure(bg=T[bgk])
        elif kind == "card":
            w.configure(bg=T["panel"], highlightbackground=T["border"], highlightcolor=T["border"], highlightthickness=1)
        elif kind == "accentbar":
            w.configure(bg=T["accent"])
        elif kind in ("label", "muted", "title", "accent", "h2"):
            fg = {"label": T["text"], "muted": T["muted"], "title": T["text"], "accent": T["accent"], "h2": T["accent"]}[kind]
            w.configure(bg=T[bgk], fg=fg)
        elif kind == "entry":
            w.configure(
                bg=T["input_bg"],
                fg=T["text"],
                insertbackground=T["accent"],
                highlightthickness=1,
                highlightbackground=T["border"],
                highlightcolor=T["accent"],
                selectbackground=T["accent"],
                selectforeground=T["on_accent"],
                disabledbackground=T["panel2"],
                disabledforeground=T["muted"],
                relief="flat",
            )
        elif kind == "text":
            w.configure(
                bg=T["log_bg"],
                fg=T["text"],
                insertbackground=T["accent"],
                highlightthickness=1,
                highlightbackground=T["border"],
                highlightcolor=T["accent"],
                selectbackground=T["accent"],
                selectforeground=T["on_accent"],
                relief="flat",
            )
        elif kind == "btn":
            state = str(w.cget("state"))
            if state == "disabled":
                w.configure(bg=T["panel2"], fg=T["muted"], activebackground=T["panel2"], activeforeground=T["muted"])
            else:
                w.configure(bg=T["accent"], fg=T["on_accent"], activebackground=T["accent_hover"], activeforeground=T["on_accent"])
        elif kind == "ghost":
            disabled = str(w.cget("state")) == "disabled"
            w.configure(
                bg=T["panel2"],
                fg=T["muted"] if disabled else T["text"],
                activebackground=T["border"],
                activeforeground=T["text"],
                highlightbackground=T["border"],
            )
        elif kind in ("check", "radio"):
            w.configure(
                bg=T[bgk],
                fg=T["text"],
                activebackground=T[bgk],
                activeforeground=T["text"],
                selectcolor=T["input_bg"],
                highlightthickness=0,
            )
        elif kind == "canvas":
            w.configure(bg=T[bgk], highlightthickness=0)

    # ------------------------------------------------------------------ fábricas de widgets
    def frame(self, parent, bg: str = "bg") -> tk.Frame:
        return self.reg(tk.Frame(parent, bd=0, highlightthickness=0), "frame", bg)

    def card(self, parent) -> tk.Frame:
        return self.reg(tk.Frame(parent, bd=0), "card")

    def label(self, parent, text: str, kind: str = "label", bg: str = "panel", size: int = 10, bold: bool = False, **kw):
        font = (FONT, size, "bold") if bold else (FONT, size)
        lb = tk.Label(parent, text=text, font=font, anchor="w", justify="left", bd=0, **kw)
        return self.reg(lb, kind, bg)

    def entry(self, parent, var: tk.Variable, width: int = 30, show: str = "") -> tk.Entry:
        e = tk.Entry(parent, textvariable=var, width=width, font=(FONT, 10), bd=0, show=show)
        return self.reg(e, "entry")

    def button(self, parent, text: str, cmd, primary: bool = False, width: int | None = None) -> tk.Button:
        b = tk.Button(
            parent,
            text=text,
            command=cmd,
            font=(FONT, 10, "bold" if primary else "normal"),
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=7 if primary else 5,
            highlightthickness=0,
            width=width if width else 0,
        )
        if primary:

            def _enter(e, w=b):
                if str(w.cget("state")) == "normal":
                    w.configure(bg=self.T["accent_hover"])

            def _leave(e, w=b):
                if str(w.cget("state")) == "normal":
                    w.configure(bg=self.T["accent"])

            b.bind("<Enter>", _enter)
            b.bind("<Leave>", _leave)
        return self.reg(b, "btn" if primary else "ghost")

    def check(self, parent, text: str, var: tk.Variable, bg: str = "panel") -> tk.Checkbutton:
        c = tk.Checkbutton(parent, text=text, variable=var, font=(FONT, 10), anchor="w", bd=0, cursor="hand2")
        return self.reg(c, "check", bg)

    def combo(self, parent, var: tk.StringVar, values: list[str], width: int = 34, readonly: bool = True) -> ttk.Combobox:
        cb = ttk.Combobox(
            parent,
            textvariable=var,
            values=values,
            width=width,
            state="readonly" if readonly else "normal",
            style="Forja.TCombobox",
            font=(FONT, 10),
        )
        self._combos.append(cb)
        return cb

    def textbox(self, parent, height: int = 10, wrap: str = "word") -> tk.Text:
        t = tk.Text(parent, height=height, wrap=wrap, font=(FONT, 10), bd=0, padx=8, pady=6, undo=True)
        return self.reg(t, "text")

    def row(self, parent, r: int, text: str, widget_factory, hint: str = "") -> None:
        self.label(parent, text, "muted").grid(row=r, column=0, sticky="w", padx=(14, 10), pady=(6, 2))
        w = widget_factory()
        w.grid(row=r, column=1, sticky="ew", padx=(0, 14), pady=(6, 2))
        if hint:
            self.label(parent, hint, "muted", size=8).grid(row=r + 1, column=1, sticky="w", padx=(0, 14))

    # ================================================================== layout
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ---- barra lateral
        side = self.frame(self, "panel")
        side.grid(row=0, column=0, sticky="ns")
        side.configure(width=210)
        side.grid_propagate(False)
        side.pack_propagate(False)
        logo = self.frame(side, "panel")
        logo.pack(fill="x", padx=18, pady=(22, 18))
        self.label(logo, "FORJA", "accent", bg="panel", size=22, bold=True).pack(anchor="w")
        self.label(logo, "gerador de vídeos", "muted", bg="panel", size=9).pack(anchor="w")
        bar = self.reg(tk.Frame(side, height=2), "accentbar")
        bar.pack(fill="x", padx=18, pady=(0, 14))

        for key, text in (("create", "Criar vídeo"), ("thumbs", "Thumbnails"), ("settings", "Configurações")):
            b = tk.Button(
                side,
                text="   " + text,
                anchor="w",
                font=(FONT, 11, "bold"),
                bd=0,
                relief="flat",
                cursor="hand2",
                padx=10,
                pady=11,
                command=lambda k=key: self.show_page(k),
                highlightthickness=0,
            )
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = b

        self.theme_btn = tk.Button(side, text="Tema", font=(FONT, 10), bd=0, cursor="hand2", pady=7, command=self.toggle_theme)
        self.reg(self.theme_btn, "ghost")
        self.theme_btn.pack(side="bottom", fill="x", padx=18, pady=18)

        # ---- conteúdo
        content = self.frame(self, "bg")
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        for key in ("create", "thumbs", "settings"):
            f = self.frame(content, "bg")
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = f
        self._build_create(self.pages["create"])
        self._build_thumbs(self.pages["thumbs"])
        self._build_settings(self.pages["settings"])

    def show_page(self, key: str) -> None:
        self.pages[key].tkraise()
        self.current_page = key
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        T = self.T
        for k, b in self.nav_buttons.items():
            active = k == getattr(self, "current_page", "create")
            b.configure(
                bg=T["accent"] if active else T["panel"],
                fg=T["on_accent"] if active else T["text"],
                activebackground=T["accent_hover"] if active else T["panel2"],
                activeforeground=T["on_accent"] if active else T["text"],
            )

    # ---------------------------------------------------------------- página: criar
    def _build_create(self, page: tk.Frame) -> None:
        page.columnconfigure(0, weight=0)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        v = self.v
        for name in (
            "topic", "thumb_text", "minutes", "format", "resolution", "script_source", "tts_engine",
            "image_source", "music_file", "status",
        ):
            v[name] = tk.StringVar()
        v["make_thumbs"] = tk.BooleanVar(value=True)
        v["progress"] = tk.DoubleVar(value=0.0)

        # coluna esquerda: ajustes
        left = self.card(page)
        left.grid(row=0, column=0, sticky="ns", padx=(22, 10), pady=22)
        left.columnconfigure(1, weight=1)
        self.label(left, "Novo vídeo", "h2", size=14, bold=True).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 4))
        self.row(left, 1, "Tema do vídeo", lambda: self.entry(left, v["topic"], 32))
        self.row(left, 2, "Texto da thumbnail", lambda: self.entry(left, v["thumb_text"], 32), "Opcional — vazio = automático")
        self.row(left, 4, "Duração (min)", lambda: self.combo(left, v["minutes"], MINUTES, 10, readonly=False))
        self.row(left, 5, "Formato", lambda: self.combo(left, v["format"], list(FORMATS.values()), 32))
        self.row(left, 6, "Qualidade", lambda: self.combo(left, v["resolution"], list(RESOLUTIONS.values()), 32))
        self.row(left, 7, "Roteiro", lambda: self.combo(left, v["script_source"], list(SCRIPT_SOURCES.values()), 32))
        self.row(left, 8, "Narração", lambda: self.combo(left, v["tts_engine"], list(tts.ENGINES.values()), 32))
        self.row(left, 9, "Imagens", lambda: self.combo(left, v["image_source"], list(media.SOURCES.values()), 32))

        mrow = self.frame(left, "panel")
        mrow.columnconfigure(0, weight=1)
        self.entry(mrow, v["music_file"], 22).grid(row=0, column=0, sticky="ew")
        self.button(mrow, "…", self._pick_music, width=3).grid(row=0, column=1, padx=(6, 0))
        self.row(left, 10, "Música de fundo", lambda: mrow, "Opcional — mp3/wav, volume baixo")
        self.check(left, "Gerar thumbnails junto com o vídeo", v["make_thumbs"]).grid(
            row=12, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 14)
        )

        # coluna direita: roteiro + produção
        right = self.frame(page, "bg")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 22), pady=22)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(6, weight=2)

        head = self.frame(right, "bg")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.label(head, "Roteiro (editável)", "title", bg="bg", size=13, bold=True).grid(row=0, column=0, sticky="w")
        self.gen_btn = self.button(head, "Gerar roteiro", self.on_generate_script)
        self.gen_btn.grid(row=0, column=1, sticky="e")

        self.script_box = self.textbox(right, height=12)
        self.script_box.grid(row=1, column=0, sticky="nsew", pady=(8, 4))
        self.label(
            right,
            "Cenas separadas por linha em branco.  “@ termo” no início da cena define a busca da imagem; “!” cria um cartão de impacto.",
            "muted",
            bg="bg",
            size=8,
        ).grid(row=2, column=0, sticky="w")

        act = self.frame(right, "bg")
        act.grid(row=3, column=0, sticky="ew", pady=(12, 6))
        act.columnconfigure(2, weight=1)
        self.produce_btn = self.button(act, "PRODUZIR VÍDEO", self.on_produce, primary=True)
        self.produce_btn.grid(row=0, column=0)
        self.cancel_btn = self.button(act, "Cancelar", self.on_cancel)
        self.cancel_btn.grid(row=0, column=1, padx=8)
        self.cancel_btn.configure(state="disabled")
        self.open_btn = self.button(act, "Abrir pasta", self.on_open_folder)
        self.open_btn.grid(row=0, column=3, sticky="e")

        pb = ttk.Progressbar(right, variable=v["progress"], maximum=1.0, style="Forja.Horizontal.TProgressbar")
        pb.grid(row=4, column=0, sticky="ew", pady=(2, 2))
        self.label(right, "", "muted", bg="bg", size=9, textvariable=v["status"]).grid(row=5, column=0, sticky="w")

        self.log_box = self.textbox(right, height=6)
        self.log_box.grid(row=6, column=0, sticky="nsew", pady=(4, 8))
        self.log_box.configure(state="disabled", font=("Consolas" if os.name == "nt" else "Courier", 9))

        self.thumb_strip = self.frame(right, "bg")
        self.thumb_strip.grid(row=7, column=0, sticky="ew")

    # ---------------------------------------------------------------- página: thumbnails
    def _build_thumbs(self, page: tk.Frame) -> None:
        v = self.v
        v["tt_text"] = tk.StringVar()
        v["tt_bg"] = tk.StringVar()
        page.columnconfigure(0, weight=1)
        card = self.card(page)
        card.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 10))
        card.columnconfigure(1, weight=1)
        self.label(card, "Gerar thumbnails", "h2", size=14, bold=True).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 4))
        self.row(card, 1, "Texto (curto!)", lambda: self.entry(card, v["tt_text"], 50), "Ex.: JAPÃO RENASCEU — 2 a 4 palavras funcionam melhor")
        bgrow = self.frame(card, "panel")
        bgrow.columnconfigure(0, weight=1)
        self.entry(bgrow, v["tt_bg"], 40).grid(row=0, column=0, sticky="ew")
        self.button(bgrow, "Escolher…", self._pick_thumb_bg).grid(row=0, column=1, padx=(6, 0))
        self.row(card, 3, "Imagem de fundo", lambda: bgrow, "Vazio = usa as imagens do último vídeo, ou um fundo laranja/preto")
        btns = self.frame(card, "panel")
        btns.grid(row=5, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 14))
        self.button(btns, "GERAR 3 THUMBNAILS", self.on_make_thumbs, primary=True).pack(side="left")
        self.button(btns, "Abrir pasta", self._open_thumb_folder).pack(side="left", padx=8)

        self.thumb_page_strip = self.frame(page, "bg")
        self.thumb_page_strip.grid(row=1, column=0, sticky="nsew", padx=22, pady=10)
        self._thumb_folder: Path | None = None

    # ---------------------------------------------------------------- página: configurações
    def _build_settings(self, page: tk.Frame) -> None:
        v = self.v
        for name in (
            "theme", "output_dir", "edge_voice", "edge_rate", "piper_model", "elevenlabs_key", "elevenlabs_voice_id",
            "elevenlabs_model", "pexels_key", "image_folder", "ollama_url", "ollama_model", "sapi_voice",
        ):
            v[name] = tk.StringVar()
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        canvas = self.reg(tk.Canvas(page, highlightthickness=0, bd=0), "canvas", "bg")
        sb = ttk.Scrollbar(page, orient="vertical", command=canvas.yview, style="Forja.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        inner = self.frame(canvas, "bg")
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        inner.columnconfigure(0, weight=1)

        def section(r: int, title: str) -> tk.Frame:
            c = self.card(inner)
            c.grid(row=r, column=0, sticky="ew", padx=22, pady=(22 if r == 0 else 0, 14))
            c.columnconfigure(1, weight=1)
            self.label(c, title, "h2", size=13, bold=True).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 4))
            return c

        # aparência e pastas
        c = section(0, "Aparência e pastas")
        themes = self.frame(c, "panel")
        for val, text in (("dark", "Escuro (laranja + preto)"), ("light", "Claro (laranja + branco)")):
            rb = tk.Radiobutton(themes, text=text, value=val, variable=v["theme"], command=self._on_theme_radio, font=(FONT, 10), cursor="hand2", bd=0)
            self.reg(rb, "radio")
            rb.pack(side="left", padx=(0, 18))
        self.row(c, 1, "Tema", lambda: themes)
        od = self.frame(c, "panel")
        od.columnconfigure(0, weight=1)
        self.entry(od, v["output_dir"], 40).grid(row=0, column=0, sticky="ew")
        self.button(od, "Escolher…", lambda: self._pick_dir("output_dir")).grid(row=0, column=1, padx=(6, 0))
        self.row(c, 2, "Pasta dos vídeos", lambda: od)
        imf = self.frame(c, "panel")
        imf.columnconfigure(0, weight=1)
        self.entry(imf, v["image_folder"], 40).grid(row=0, column=0, sticky="ew")
        self.button(imf, "Escolher…", lambda: self._pick_dir("image_folder")).grid(row=0, column=1, padx=(6, 0))
        self.row(c, 3, "Minha pasta de imagens", lambda: imf, "Usada quando “Imagens” = Minha pasta de imagens")

        # roteiro (Ollama)
        c = section(1, "Roteiro com IA local (Ollama)")
        self.row(c, 1, "Endereço", lambda: self.entry(c, v["ollama_url"], 40))
        self.ollama_combo = self.combo(c, v["ollama_model"], [], 36, readonly=False)
        self.row(c, 2, "Modelo", lambda: self.ollama_combo, "Instale o Ollama (ollama.com) e baixe um modelo, ex.: ollama pull llama3.1")
        self.button(c, "Detectar modelos instalados", self._detect_ollama).grid(row=4, column=1, sticky="w", pady=(4, 14))

        # narração
        c = section(2, "Narração")
        self.row(c, 1, "Voz do Edge (grátis)", lambda: self.combo(c, v["edge_voice"], tts.EDGE_VOICES, 36))
        self.row(c, 2, "Velocidade", lambda: self.combo(c, v["edge_rate"], [f"{k}  {t}" for k, t in EDGE_RATES.items()], 36))
        self.sapi_combo = self.combo(c, v["sapi_voice"], [], 36, readonly=False)
        self.row(c, 3, "Voz do Windows", lambda: self.sapi_combo)
        self.button(c, "Listar vozes do Windows", self._list_sapi).grid(row=4, column=1, sticky="w", pady=(4, 8))

        pm = self.frame(c, "panel")
        pm.columnconfigure(0, weight=1)
        self.entry(pm, v["piper_model"], 40).grid(row=0, column=0, sticky="ew")
        self.button(pm, "Escolher…", self._pick_piper).grid(row=0, column=1, padx=(6, 0))
        self.row(c, 5, "Modelo Piper (.onnx)", lambda: pm, "Vazio = usa a voz baixada pelo botão abaixo")
        self.piper_btn = self.button(c, "Baixar voz em português do Piper (~60 MB)", self._download_piper)
        self.piper_btn.grid(row=7, column=1, sticky="w", pady=(4, 12))

        self.label(c, "ElevenLabs (opcional — voz mais natural, usa créditos da sua conta)", "accent", size=10, bold=True).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=14, pady=(6, 0)
        )
        self.row(c, 9, "Chave da API", lambda: self.entry(c, v["elevenlabs_key"], 40, show="•"))
        self.eleven_combo = self.combo(c, v["elevenlabs_voice_id"], [], 36, readonly=False)
        self.row(c, 10, "Voz (ID)", lambda: self.eleven_combo)
        self.row(c, 11, "Modelo", lambda: self.combo(c, v["elevenlabs_model"], ELEVEN_MODELS, 36, readonly=False))
        eb = self.frame(c, "panel")
        eb.grid(row=12, column=1, sticky="w", pady=(4, 14))
        self.button(eb, "Carregar minhas vozes", self._load_eleven_voices).pack(side="left")
        self.button(eb, "Testar voz", self._test_eleven).pack(side="left", padx=8)

        # imagens
        c = section(3, "Imagens")
        self.row(c, 1, "Chave do Pexels", lambda: self.entry(c, v["pexels_key"], 40, show="•"), "Grátis em pexels.com/api — só é preciso se escolher Pexels")

        # salvar
        sv = self.frame(inner, "bg")
        sv.grid(row=4, column=0, sticky="w", padx=22, pady=(0, 28))
        self.button(sv, "SALVAR CONFIGURAÇÕES", self.on_save_settings, primary=True).pack(side="left")
        self.settings_status = self.label(sv, "", "muted", bg="bg", size=9)
        self.settings_status.pack(side="left", padx=12)

    # ================================================================== config <-> widgets
    def _load_vars(self) -> None:
        c, v = self.cfg, self.v
        v["topic"].set("")
        v["thumb_text"].set(c.get("thumb_text", ""))
        v["minutes"].set(str(c.get("minutes", 3)))
        v["format"].set(FORMATS.get(c.get("format"), FORMATS["horizontal"]))
        v["resolution"].set(RESOLUTIONS.get(c.get("resolution"), RESOLUTIONS["720p"]))
        v["script_source"].set(SCRIPT_SOURCES.get(c.get("script_source"), SCRIPT_SOURCES["auto"]))
        v["tts_engine"].set(tts.ENGINES.get(c.get("tts_engine"), tts.ENGINES["edge"]))
        v["image_source"].set(media.SOURCES.get(c.get("image_source"), media.SOURCES["commons"]))
        v["music_file"].set(c.get("music_file", ""))
        v["make_thumbs"].set(bool(c.get("make_thumbs", True)))
        v["theme"].set(c.get("theme", "dark"))
        for k in (
            "output_dir", "edge_voice", "piper_model", "elevenlabs_key", "elevenlabs_voice_id", "elevenlabs_model",
            "pexels_key", "image_folder", "ollama_url", "ollama_model", "sapi_voice",
        ):
            v[k].set(c.get(k, ""))
        rate = c.get("edge_rate", "+0%")
        v["edge_rate"].set(f"{rate}  {EDGE_RATES.get(rate, '')}".strip())
        v["tt_text"].set("")

    def collect_cfg(self) -> dict:
        v, c = self.v, self.cfg
        try:
            minutes = float(v["minutes"].get().replace(",", "."))
        except ValueError:
            minutes = 3.0
        c["minutes"] = max(0.5, min(minutes, 30))
        c["thumb_text"] = v["thumb_text"].get().strip()
        c["format"] = key_of(FORMATS, v["format"].get(), "horizontal")
        c["resolution"] = key_of(RESOLUTIONS, v["resolution"].get(), "720p")
        c["script_source"] = key_of(SCRIPT_SOURCES, v["script_source"].get(), "auto")
        c["tts_engine"] = key_of(tts.ENGINES, v["tts_engine"].get(), "edge")
        c["image_source"] = key_of(media.SOURCES, v["image_source"].get(), "commons")
        c["music_file"] = v["music_file"].get().strip()
        c["make_thumbs"] = bool(v["make_thumbs"].get())
        c["theme"] = v["theme"].get() or c.get("theme", "dark")
        for k in (
            "output_dir", "edge_voice", "piper_model", "elevenlabs_key", "elevenlabs_voice_id", "elevenlabs_model",
            "pexels_key", "image_folder", "ollama_url", "ollama_model",
        ):
            c[k] = v[k].get().strip()
        c["edge_rate"] = v["edge_rate"].get().split()[0] if v["edge_rate"].get().strip() else "+0%"
        sapi = v["sapi_voice"].get().strip()
        c["sapi_voice"] = sapi.split("  |  ")[0] if sapi else ""
        eid = v["elevenlabs_voice_id"].get().strip()
        c["elevenlabs_voice_id"] = eid.split("  |  ")[0] if eid else ""
        return c

    # ================================================================== temas
    def toggle_theme(self) -> None:
        self.cfg["theme"] = "light" if self.cfg["theme"] == "dark" else "dark"
        self.v["theme"].set(self.cfg["theme"])
        self._apply_cfg_theme()

    def _on_theme_radio(self) -> None:
        self.cfg["theme"] = self.v["theme"].get()
        self._apply_cfg_theme()

    def _apply_cfg_theme(self) -> None:
        self.T = THEMES[self.cfg["theme"]]
        self.apply_theme()
        config.save(self.cfg)

    # ================================================================== seletores de arquivo
    def _pick_music(self) -> None:
        p = filedialog.askopenfilename(title="Música de fundo", filetypes=[("Áudio", "*.mp3 *.wav *.m4a *.ogg *.flac"), ("Todos", "*.*")])
        if p:
            self.v["music_file"].set(p)

    def _pick_dir(self, key: str) -> None:
        p = filedialog.askdirectory(title="Escolher pasta")
        if p:
            self.v[key].set(p)

    def _pick_piper(self) -> None:
        p = filedialog.askopenfilename(title="Modelo Piper", filetypes=[("Modelo ONNX", "*.onnx"), ("Todos", "*.*")])
        if p:
            self.v["piper_model"].set(p)

    def _pick_thumb_bg(self) -> None:
        p = filedialog.askopenfilename(title="Imagem de fundo", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")])
        if p:
            self.v["tt_bg"].set(p)

    # ================================================================== ações de configurações
    def on_save_settings(self) -> None:
        self.collect_cfg()
        config.save(self.cfg)
        self.settings_status.configure(text="Configurações salvas.")
        self.after(3000, lambda: self.settings_status.configure(text=""))

    def _detect_ollama(self) -> None:
        url = self.v["ollama_url"].get().strip() or "http://localhost:11434"

        def work():
            models = scriptgen.ollama_models(url)
            self.q.put(("ollama_models", models))

        threading.Thread(target=work, daemon=True).start()

    def _list_sapi(self) -> None:
        def work():
            self.q.put(("sapi_voices", tts.sapi_voices()))

        threading.Thread(target=work, daemon=True).start()

    def _load_eleven_voices(self) -> None:
        key = self.v["elevenlabs_key"].get().strip()
        if not key:
            messagebox.showinfo("ElevenLabs", "Cole primeiro a sua chave da API.")
            return

        def work():
            try:
                self.q.put(("eleven_voices", tts.elevenlabs_voices(key)))
            except Exception as e:
                self.q.put(("error_box", f"ElevenLabs: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _test_eleven(self) -> None:
        cfg = dict(self.collect_cfg())
        cfg["tts_engine"] = "elevenlabs"

        def work():
            try:
                out = tts.synthesize("Olá! Esta é a minha voz no ForjaVideo.", config.CONFIG_DIR / "teste_voz", cfg)
                self.q.put(("open_file", str(out)))
            except Exception as e:
                self.q.put(("error_box", str(e)))

        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=work, daemon=True).start()

    def _download_piper(self) -> None:
        self.piper_btn.configure(state="disabled", text="Baixando…")

        def work():
            try:
                p = tts.download_piper_model(lambda f: self.q.put(("piper_progress", f)))
                self.q.put(("piper_done", str(p)))
            except Exception as e:
                self.q.put(("piper_fail", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # ================================================================== roteiro / produção
    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.produce_btn.configure(state=state)
        self._style_widget(self.produce_btn, "btn", "panel")
        self.gen_btn.configure(state=state)
        self._style_widget(self.gen_btn, "ghost", "panel")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        self._style_widget(self.cancel_btn, "ghost", "panel")

    def _log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _validate(self, need_topic: bool) -> dict | None:
        cfg = self.collect_cfg()
        config.save(cfg)
        topic = self.v["topic"].get().strip()
        if need_topic and not topic:
            messagebox.showinfo("Falta o tema", "Digite o tema do vídeo.")
            return None
        if cfg["tts_engine"] == "elevenlabs" and not cfg["elevenlabs_key"]:
            messagebox.showinfo("ElevenLabs", "Informe a chave da API em Configurações → Narração, ou escolha outra narração.")
            return None
        if cfg["image_source"] == "pexels" and not cfg["pexels_key"]:
            messagebox.showinfo("Pexels", "Informe a chave do Pexels em Configurações → Imagens, ou escolha outra fonte.")
            return None
        return cfg

    def on_generate_script(self) -> None:
        cfg = self._validate(need_topic=True)
        if cfg is None or self.worker:
            return
        topic = self.v["topic"].get().strip()
        if cfg["script_source"] == "manual":
            messagebox.showinfo("Roteiro manual", "Você escolheu escrever o roteiro. Cole-o na caixa de texto.")
            return
        self._busy(True)
        self.cancel_token = CancelToken()
        self._log("Gerando roteiro…")

        def work():
            try:
                s = scriptgen.generate_script(topic, cfg["minutes"], cfg, lambda m: self.q.put(("log", m)), self.cancel_token)
                self.q.put(("script", scriptgen.script_to_text(s)))
            except Cancelled:
                self.q.put(("cancelled", None))
            except Exception as e:
                self.q.put(("error", str(e)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_produce(self) -> None:
        if self.worker:
            return
        text = self.script_box.get("1.0", "end").strip()
        cfg = self._validate(need_topic=not text)
        if cfg is None:
            return
        topic = self.v["topic"].get().strip() or "video"
        if not text and cfg["script_source"] == "manual":
            messagebox.showinfo("Roteiro manual", "Cole ou escreva o roteiro na caixa de texto.")
            return
        self._busy(True)
        self.cancel_token = CancelToken()
        self.v["progress"].set(0.0)
        self._clear(self.thumb_strip)
        self._log(f"Iniciando: {topic}")

        def work():
            try:
                res = pipeline.produce(
                    topic,
                    text,
                    cfg,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda f, m: self.q.put(("progress", (f, m))),
                    cancel=self.cancel_token,
                )
                self.q.put(("done", res))
            except Cancelled:
                self.q.put(("cancelled", None))
            except Exception as e:
                self.q.put(("error", str(e)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_cancel(self) -> None:
        if self.cancel_token:
            self.cancel_token.cancel()
            self.v["status"].set("Cancelando…")

    def on_open_folder(self) -> None:
        if self.last_result:
            open_path(self.last_result.folder)
        else:
            Path(self.cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
            open_path(self.cfg["output_dir"])

    # ================================================================== thumbnails avulsas
    def on_make_thumbs(self) -> None:
        text = self.v["tt_text"].get().strip()
        if not text:
            messagebox.showinfo("Falta o texto", "Digite o texto da thumbnail.")
            return
        cfg = self.collect_cfg()
        bgs: list[Path] = []
        bg = self.v["tt_bg"].get().strip()
        if bg and Path(bg).exists():
            bgs = [Path(bg)]
        elif self.last_result and self.last_result.backgrounds:
            bgs = list(self.last_result.backgrounds[:3])
        out_dir = Path(cfg["output_dir"]) / "Thumbnails" / time.strftime("%Y%m%d-%H%M%S")
        try:
            paths = pipeline.thumbnails_only(text, bgs, out_dir)
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self._thumb_folder = out_dir
        self._show_thumbs(self.thumb_page_strip, paths, 300)

    def _open_thumb_folder(self) -> None:
        target = self._thumb_folder or (Path(self.cfg["output_dir"]) / "Thumbnails")
        target.mkdir(parents=True, exist_ok=True)
        open_path(target)

    def _clear(self, frame: tk.Frame) -> None:
        for ch in frame.winfo_children():
            ch.destroy()
        self._reg = [(w, s) for (w, s) in self._reg if self._alive(w)]

    @staticmethod
    def _alive(w) -> bool:
        try:
            return bool(w.winfo_exists())
        except tk.TclError:
            return False

    def _show_thumbs(self, frame: tk.Frame, paths: list[Path], width: int) -> None:
        self._clear(frame)
        self._photos[str(frame)] = []
        for i, p in enumerate(paths):
            try:
                im = Image.open(p)
                im.thumbnail((width, int(width * 9 / 16)))
                ph = ImageTk.PhotoImage(im)
            except Exception:
                continue
            self._photos[str(frame)].append(ph)
            cell = self.frame(frame, "bg")
            cell.grid(row=0, column=i, padx=(0, 12), pady=4)
            lb = tk.Label(cell, image=ph, bd=0, cursor="hand2")
            self.reg(lb, "frame", "bg")
            lb.pack()
            lb.bind("<Button-1>", lambda e, pp=p: open_path(pp))
            self.label(cell, Path(p).name, "muted", bg="bg", size=8).pack(anchor="w")
        self._apply_theme_to_new()

    def _apply_theme_to_new(self) -> None:
        for w, (kind, bgk) in self._reg:
            try:
                self._style_widget(w, kind, bgk)
            except tk.TclError:
                pass

    # ================================================================== fila de mensagens da thread
    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.q.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _handle(self, kind: str, data) -> None:
        v = self.v
        if kind == "log":
            self._log(data)
        elif kind == "progress":
            frac, msg = data
            v["progress"].set(frac)
            v["status"].set(msg)
        elif kind == "script":
            self.script_box.delete("1.0", "end")
            self.script_box.insert("1.0", data)
            self.worker = None
            self._busy(False)
            self._log("Roteiro pronto. Revise e clique em PRODUZIR VÍDEO.")
        elif kind == "done":
            self.worker = None
            self._busy(False)
            self.last_result = data
            self._log(f"Vídeo salvo em: {data.video}")
            if data.thumbnails:
                self._show_thumbs(self.thumb_strip, data.thumbnails, 165)
            v["status"].set("Pronto!")
        elif kind == "cancelled":
            self.worker = None
            self._busy(False)
            v["status"].set("Cancelado.")
            self._log("Cancelado.")
        elif kind == "error":
            self.worker = None
            self._busy(False)
            v["status"].set("Erro.")
            self._log("ERRO: " + data)
            messagebox.showerror("Algo deu errado", data)
        elif kind == "error_box":
            messagebox.showerror("Erro", data)
        elif kind == "ollama_models":
            self.ollama_combo.configure(values=data)
            if data:
                if v["ollama_model"].get() not in data:
                    v["ollama_model"].set(data[0])
                messagebox.showinfo("Ollama", f"{len(data)} modelo(s) encontrado(s).")
            else:
                messagebox.showinfo("Ollama", "Não encontrei o Ollama rodando nesse endereço.")
        elif kind == "sapi_voices":
            vals = [f"{i}  |  {n}" for i, n in data]
            self.sapi_combo.configure(values=vals)
            if not vals:
                messagebox.showinfo("Vozes", "Nenhuma voz do Windows encontrada (ou o pacote pyttsx3 não está instalado).")
        elif kind == "eleven_voices":
            vals = [f"{i}  |  {n}" for i, n in data]
            self.eleven_combo.configure(values=vals)
            if vals:
                v["elevenlabs_voice_id"].set(vals[0])
        elif kind == "piper_progress":
            self.piper_btn.configure(text=f"Baixando… {int(data * 100)}%")
        elif kind == "piper_done":
            v["piper_model"].set(data)
            self.piper_btn.configure(state="normal", text="Baixar voz em português do Piper (~60 MB)")
            messagebox.showinfo("Piper", "Voz baixada. Escolha “Piper” em Narração e salve.")
        elif kind == "piper_fail":
            self.piper_btn.configure(state="normal", text="Baixar voz em português do Piper (~60 MB)")
            messagebox.showerror("Piper", data)
        elif kind == "open_file":
            open_path(data)

    def _on_close(self) -> None:
        try:
            self.collect_cfg()
            config.save(self.cfg)
        except Exception:
            pass
        if self.cancel_token:
            self.cancel_token.cancel()
        self.destroy()


def run() -> None:
    app = App()
    app.mainloop()
