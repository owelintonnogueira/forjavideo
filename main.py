"""ForjaVideo — ponto de entrada."""
import os
import sys
import time
import traceback
from pathlib import Path


def _dpi_awareness() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _report(text: str, show: bool = True) -> None:
    """Programa sem console não mostra erros: grava em ~/.forjavideo/erro.log e avisa numa janela."""
    log = Path.home() / ".forjavideo" / "erro.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
    except Exception:
        pass
    if not show:
        return
    msg = f"O ForjaVideo encontrou um erro ao abrir.\n\nDetalhes salvos em:\n{log}\n\n{text[-1200:]}"
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ForjaVideo — erro", msg)
        root.destroy()
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "ForjaVideo — erro", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    _dpi_awareness()
    selftest = "--selftest" in sys.argv
    try:
        if selftest:
            from forja.selftest import run_selftest

            i = sys.argv.index("--selftest") + 1
            outdir = sys.argv[i] if i < len(sys.argv) else "selftest_out"
            sys.exit(run_selftest(outdir))
        from forja.gui import run

        run()
    except SystemExit:
        raise
    except BaseException:
        _report(traceback.format_exc(), show=not selftest)
        sys.exit(1)
