"""Rebuild the public login crops. Development-only dependency: Pillow.

Run with a Python environment containing Pillow and the plugin dependencies:
    python scripts/build_login_backgrounds.py
No image processing or Pillow dependency is needed by the installed gate.
"""

import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from styx.backend.login_page import BACKGROUND_SIZES  # noqa: E402


def main() -> None:
    destination = ROOT / "assets" / "login"
    destination.mkdir(exist_ok=True)
    with Image.open(ROOT / "assets" / "login-background.jpg") as original:
        original = ImageOps.exif_transpose(original).convert("RGB")
        # Tiny inline preview: visible with the form, before any image request.
        preview = original.copy()
        preview.thumbnail((48, 48), Image.Resampling.LANCZOS)
        preview.save(destination / "preview.webp", "WEBP", quality=40, method=6)
        for variant, size in BACKGROUND_SIZES.items():
            crop = ImageOps.fit(original, size, method=Image.Resampling.LANCZOS)
            path = destination / f"{variant}.webp"
            crop.save(path, "WEBP", quality=78, method=6)
            print(f"{variant}: {size[0]}x{size[1]}, {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
