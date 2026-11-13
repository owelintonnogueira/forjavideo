"""Exercita a lógica da interface com o tkinter simulado (sem janela). Não substitui testar no Windows."""
import sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tk
mb = fake_tk.install()

from forja import config, gui
tmp = Path(tempfile.mkdtemp(prefix="forja_gui_"))
config.CONFIG_DIR = tmp / "cfg"; config.CONFIG_FILE = config.CONFIG_DIR / "config.json"

app = gui.App()
print("App criado. widgets registrados:", len(app._reg))

# temas
for _ in range(3):
    app.toggle_theme()
print("tema final:", app.cfg["theme"])
app._on_theme_radio()

# configura e produz
v = app.v
v["topic"].set("Teste do Japão")
v["tts_engine"].set(gui.tts.ENGINES["none"])
v["image_source"].set(gui.media.SOURCES["generated"])
v["format"].set(gui.FORMATS["vertical"])
app.cfg["output_dir"] = str(tmp / "out"); v["output_dir"].set(str(tmp / "out"))
app.script_box._text = "#thumb: JAPÃO FORTE\n\n@ japan\nPrimeira cena de teste com algumas palavras para narrar.\n\n! Frase de impacto\n\nSegunda cena de teste, também curta.\n"
app.on_produce()
t0 = time.time()
while app.worker is not None and time.time() - t0 < 120:
    try:
        while True:
            k, d = app.q.get(timeout=0.3); app._handle(k, d)
            if k in ("done", "error", "cancelled"): break
    except Exception:
        pass
print("messagebox:", mb.calls)
print("resultado:", app.last_result.video if app.last_result else None)
print("thumbs:", [p.name for p in app.last_result.thumbnails] if app.last_result else None)
print("log:", app.log_box._text.strip().splitlines()[-2:])

# thumbnails avulsas
v["tt_text"].set("MEU TESTE")
app.on_make_thumbs()
print("thumbs avulsas:", len(app._photos), "grupos de fotos")

# salvar config
app.on_save_settings()
print("config salva:", config.CONFIG_FILE.exists())
app._on_close()
print("OK")
