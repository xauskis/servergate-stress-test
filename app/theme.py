"""SERVER GATE — visual theme (navy / white / orange).

Central palette + font helpers so every widget pulls from one source of truth.
"""
from __future__ import annotations

import tkinter.font as tkfont

# ----------------------------------------------------------------------------
# Palette — SERVER GATE brand (servergate.ru): azure blue #0684BD + orange
# #FF9000 on white, tuned for a technical operations dashboard.
# ----------------------------------------------------------------------------
NAVY        = "#075E88"   # deep brand blue (headings / structure)
NAVY_2      = "#0A6FA0"   # deep panel
BLUE        = "#0684BD"   # brand primary (logo blue)
BLUE_DK     = "#056C9C"
BLUE_SOFT   = "#E3F1F8"   # tint fill

ORANGE      = "#FF9000"   # brand accent (logo orange) / CTA / progress
ORANGE_DK   = "#E07F00"
ORANGE_SOFT = "#FFEBD3"

BG          = "#F2F7FB"   # app background (cool light)
CARD        = "#FFFFFF"   # white surfaces
CARD_ALT    = "#F6FAFD"   # subtle alt surface
CARD_INSET  = "#EEF5FA"

INK         = "#0F2537"   # near-navy text
INK_MUTED   = "#54718A"   # secondary text
INK_FAINT   = "#7E96AC"
BORDER      = "#D9E6EF"
BORDER_DK   = "#C3D6E3"

GREEN       = "#17A673"   # pass
GREEN_SOFT  = "#DFF5EC"
RED         = "#E23D3D"   # fail
RED_SOFT    = "#FBE3E3"
AMBER       = "#F2A93B"   # warning
AMBER_SOFT  = "#FCEFD6"

# status -> (fg, soft-bg)
STATUS_COLORS = {
    "PASSED":  (GREEN, GREEN_SOFT),
    "FAILED":  (RED, RED_SOFT),
    "STOPPED": (AMBER, AMBER_SOFT),
    "RUNNING": (BLUE, BLUE_SOFT),
    "WAITING": (INK_FAINT, CARD_INSET),
    "ERROR":   (RED, RED_SOFT),
}

# ----------------------------------------------------------------------------
# Typography.  Segoe UI ships on every modern Windows; Consolas is the
# guaranteed monospaced face used for numbers / timers / throughput.
# ----------------------------------------------------------------------------
UI_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"

# Candidate families in preference order, so the UI looks right on Windows
# (Segoe UI / Consolas) AND on a Linux live system (DejaVu / Noto).
_UI_CANDIDATES = ["Segoe UI", "DejaVu Sans", "Noto Sans", "Cantarell",
                  "Liberation Sans", "Arial", "Helvetica"]
_MONO_CANDIDATES = ["Consolas", "DejaVu Sans Mono", "Noto Sans Mono",
                    "Liberation Mono", "Courier New", "Courier"]


def _pick_first(candidates, hard_fallback):
    try:
        fams = set(tkfont.families())
        for c in candidates:
            if c in fams:
                return c
    except Exception:
        pass
    return hard_fallback


def init_fonts():
    """Resolve font families once a Tk root exists. Returns a dict of specs."""
    global UI_FAMILY, MONO_FAMILY
    ui = _pick_first(_UI_CANDIDATES, "TkDefaultFont")
    mono = _pick_first(_MONO_CANDIDATES, "TkFixedFont")
    UI_FAMILY, MONO_FAMILY = ui, mono
    return {
        "display":   (ui, 30, "bold"),
        "wordmark":  (ui, 22, "bold"),
        "h1":        (ui, 20, "bold"),
        "h2":        (ui, 15, "bold"),
        "h3":        (ui, 13, "bold"),
        "body":      (ui, 13, "normal"),
        "body_bold": (ui, 13, "bold"),
        "small":     (ui, 11, "normal"),
        "small_bold":(ui, 11, "bold"),
        "tiny":      (ui, 10, "normal"),
        "mono_xl":   (mono, 30, "bold"),
        "mono_lg":   (mono, 20, "bold"),
        "mono":      (mono, 13, "normal"),
        "mono_bold": (mono, 13, "bold"),
        "mono_sm":   (mono, 11, "normal"),
    }
