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


def wait_for_production(app, previous, boxes: list, timeout: float = 240.0):
    """Espera a produção terminar olhando o ESTADO do app (o próprio app também consome a fila de mensagens)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.update()
        try:
            while True:
                kind, data = app.q.get_nowait()
                app._handle(kind, data)
        except queue.Empty:
            pass
        if app.worker is None and app.last_result is not None and app.last_result is not previous:
            return app.last_result
        if app.v["status"].get() == "Erro.":
            raise RuntimeError("produção falhou: " + " | ".join(boxes) + " | " + app.log_box.get("1.0", "end")[-800:])
        time.sleep(0.1)
    alive = app.worker.is_alive() if app.worker else None
    raise RuntimeError(
        f"a produção não terminou em {int(timeout)}s (worker vivo={alive}, status={app.v['status'].get()!r}) | "
        + app.log_box.get("1.0", "end")[-800:]
    )


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
        result = wait_for_production(app, None, boxes)
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
        result = wait_for_production(app, result, boxes)
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
