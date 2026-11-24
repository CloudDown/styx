"""Rebuild the public login crops.

Development-only dependencies: Pillow, and `avifenc` (libavif) for AVIF. If
`avifenc` and a Pillow AVIF plugin are both missing, WebP is rebuilt and AVIF
is skipped with a warning.

    python scripts/build_login_backgrounds.py

The installed gate only reads the prebuilt files; it needs neither Pillow nor
libavif.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from styx.backend.login_page import BACKGROUND_SIZES  # noqa: E402

_AVIF_QUALITY = 50
_AVIF_SPEED = 6


def _write_avif(image: Image.Image, path: Path) -> bool:
    """Encode AVIF with avifenc, or Pillow when it has an AVIF plugin."""
    avifenc = shutil.which("avifenc")
    if avifenc:
        with tempfile.TemporaryDirectory() as raw:
            png = Path(raw) / "crop.png"
            image.save(png, "PNG")
            subprocess.run(
                [avifenc, "-q", str(_AVIF_QUALITY), "-s", str(_AVIF_SPEED), str(png), str(path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    try:
        image.save(path, "AVIF", quality=_AVIF_QUALITY, speed=_AVIF_SPEED)
    except (KeyError, OSError, ValueError):
        return False
    return True


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
            webp = destination / f"{variant}.webp"
            crop.save(webp, "WEBP", quality=78, method=6)
            avif = destination / f"{variant}.avif"
            if _write_avif(crop, avif):
                print(
                    f"{variant}: {size[0]}x{size[1]}, webp {webp.stat().st_size} B, "
                    f"avif {avif.stat().st_size} B"
                )
            else:
                print(
                    f"{variant}: {size[0]}x{size[1]}, webp {webp.stat().st_size} B "
                    "(AVIF skipped: install avifenc or a Pillow AVIF plugin)"
                )


if __name__ == "__main__":
    main()
