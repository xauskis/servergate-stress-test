"""Bundled image assets (brand logo) with PyInstaller-aware path resolution."""
from __future__ import annotations

import os
import sys

from PIL import Image

# Logo aspect ratio (2367 x 734 SVG): width = height * ASPECT
ASPECT = 2367 / 734


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_logo(height: int) -> "tuple[Image.Image, tuple[int, int]]":
    """Return (PIL image, (w, h)) for the full SERVERGATE logo at `height` px."""
    src = "logo_report.png" if height > 52 else "logo_header.png"
    img = Image.open(resource_path(src)).convert("RGBA")
    w = round(height * ASPECT)
    return img, (w, height)


def icon_path() -> str:
    return resource_path("servergate.ico")


def icon_png_path() -> str:
    return resource_path("logo_icon.png")
