"""Roda forja/selftest.py com o tkinter simulado (pega erros de Python; o teste real roda no Windows do GitHub)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tk
fake_tk.install()
from forja import config
tmp = Path(tempfile.mkdtemp(prefix="forja_st_"))
config.CONFIG_DIR = tmp / "cfg"; config.CONFIG_FILE = config.CONFIG_DIR / "config.json"
from forja.selftest import run_selftest
code = run_selftest(str(tmp / "out"))
print((tmp / "out" / "selftest.log").read_text())
print("exit:", code)
sys.exit(code)
