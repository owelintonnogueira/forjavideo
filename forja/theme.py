"""Paletas: laranja + preto (escuro) e laranja + branco (claro)."""

ORANGE = "#FF7A00"
ORANGE_HOVER = "#FF9433"
ORANGE_DARK = "#CC6200"

THEMES = {
    "dark": {
        "bg": "#0B0B0C",
        "panel": "#161618",
        "panel2": "#1F1F22",
        "border": "#2E2E33",
        "text": "#F5F5F5",
        "muted": "#9A9AA3",
        "accent": ORANGE,
        "accent_hover": ORANGE_HOVER,
        "on_accent": "#0B0B0C",
        "input_bg": "#101012",
        "log_bg": "#0F0F11",
        "danger": "#FF4D4D",
        "ok": "#3DDC84",
    },
    "light": {
        "bg": "#FFFFFF",
        "panel": "#FFF6EC",
        "panel2": "#FFEBD6",
        "border": "#F2D2AE",
        "text": "#1A1A1A",
        "muted": "#7A6A5A",
        "accent": ORANGE,
        "accent_hover": ORANGE_DARK,
        "on_accent": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "log_bg": "#FFFBF6",
        "danger": "#D93025",
        "ok": "#1E8E3E",
    },
}
