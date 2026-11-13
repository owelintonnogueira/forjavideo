"""ForjaVideo — ponto de entrada."""
import os
import sys


def _dpi_awareness() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


if __name__ == "__main__":
    _dpi_awareness()
    from forja.gui import run

    run()
