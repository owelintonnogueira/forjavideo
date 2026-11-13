"""Autoteste do programa empacotado: abre a janela de verdade, tira capturas de tela e produz um vídeo curto.

Uso:  ForjaVideo.exe --selftest <pasta-de-saida>      (código de saída 0 = tudo certo)
"""
from __future__ import annotations

import queue
import sys
import tempfile
import time
import traceback
from pathlib import Path

SCRIPT = """#titulo: Autoteste do ForjaVideo
#thumb: TESTE OK

Esta é a primeira cena do autoteste, com algumas palavras para a legenda aparecer.

! Frase de impacto

E esta é a última cena, curta e direta.
"""


def run_selftest(outdir: str) -> int:
    out = Path(outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(f"{time.strftime('%H:%M:%S')} {msg}")
        (out / "selftest.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok = True
    app = None
    try:
        log(f"python {sys.version.split()[0]} | frozen={getattr(sys, 'frozen', False)}")
        from forja import config, util

        log(f"ffmpeg: {util.ffmpeg_exe()}")
        log(f"fonte: {util.font_path('Bold')}")

        from forja import gui

        gui.SILENT = True
        boxes: list[str] = []
        gui.messagebox.showinfo = lambda t, m, **k: boxes.append(f"info: {t}: {m}")
        gui.messagebox.showerror = lambda t, m, **k: boxes.append(f"erro: {t}: {m}")

        tmp = Path(tempfile.mkdtemp(prefix="forja_selftest_"))
        app = gui.App()
        app.geometry("1300x840+0+0")
        app.update()
        log("janela criada")

        def shot(name: str) -> None:
            try:
                from PIL import ImageGrab

                app.update()
                time.sleep(0.4)
                app.update()
                x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
                ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out / name)
                log(f"captura {name} ({w}x{h})")
            except Exception as e:
                log(f"captura {name} falhou: {e}")

        for theme in ("dark", "light"):
            app.cfg["theme"] = theme
            app.v["theme"].set(theme)
            app._apply_cfg_theme()
            for page in ("create", "thumbs", "settings"):
                app.show_page(page)
                shot(f"{theme}_{page}.png")
        log("temas e páginas ok")

        # produção real, pelo mesmo caminho do botão (thread + fila)
        app.cfg["theme"] = "dark"
        app.v["theme"].set("dark")
        app._apply_cfg_theme()
        app.show_page("create")
        v = app.v
        v["topic"].set("Autoteste")
        v["tts_engine"].set(gui.tts.ENGINES["none"])
        v["image_source"].set(gui.media.SOURCES["generated"])
        v["format"].set(gui.FORMATS["horizontal"])
        v["resolution"].set(gui.RESOLUTIONS["720p"])
        v["output_dir"].set(str(tmp / "saida"))
        app.script_box.delete("1.0", "end")
        app.script_box.insert("1.0", SCRIPT)
        app.on_produce()
        t0 = time.time()
        result = None
        while time.time() - t0 < 240:
            app.update()
            try:
                while True:
                    kind, data = app.q.get_nowait()
                    if kind == "done":
                        result = data
                    elif kind in ("error", "cancelled"):
                        raise RuntimeError(f"produção falhou: {data}")
                    app._handle(kind, data)
            except queue.Empty:
                pass
            if result is not None:
                break
            time.sleep(0.1)
        if result is None:
            raise RuntimeError("a produção não terminou em 4 minutos")
        app.update()
        dur = util.audio_duration(result.video)
        size = result.video.stat().st_size
        log(f"vídeo: {result.video.name} | {dur:.1f}s | {size // 1024} KB")
        if dur < 4 or size < 20_000:
            raise RuntimeError("vídeo gerado parece inválido")
        if len(result.thumbnails) != 3:
            raise RuntimeError(f"esperava 3 thumbnails, vieram {len(result.thumbnails)}")
        log("thumbnails: " + ", ".join(p.name for p in result.thumbnails))
        shot("producao_concluida.png")
        for p in result.thumbnails[:1]:
            (out / "amostra_thumbnail.jpg").write_bytes(p.read_bytes())

        # formato vertical
        v["format"].set(gui.FORMATS["vertical"])
        app.on_produce()
        result = None
        t0 = time.time()
        while time.time() - t0 < 240 and result is None:
            app.update()
            while not app.q.empty():
                kind, data = app.q.get_nowait()
                if kind in ("error", "cancelled"):
                    raise RuntimeError(f"produção vertical falhou: {data}")
                if kind == "done":
                    result = data
                app._handle(kind, data)
            time.sleep(0.1)
        if result is None:
            raise RuntimeError("a produção vertical não terminou")
        log(f"vídeo vertical ok: {result.video.name}")

        v["tt_text"].set("TESTE")
        app.on_make_thumbs()
        log("thumbnails avulsas ok")

        err = getattr(app, "last_tk_error", "")
        if err:
            raise RuntimeError("erro de callback do tkinter:\n" + err)
        if boxes:
            log("caixas de mensagem: " + " | ".join(boxes))
        log("AUTOTESTE OK")
    except BaseException:
        ok = False
        log("FALHOU:\n" + traceback.format_exc())
    finally:
        try:
            if app is not None:
                app.destroy()
        except Exception:
            pass
    return 0 if ok else 1
