"""Optional diagram maintainer tool. Requires Inkscape and Pillow with WebP."""
from io import BytesIO
from pathlib import Path
import subprocess

from PIL import Image

here = Path(__file__).resolve().parent
for name in ("battery-duty-energy", "battery-sag-threshold"):
    for width, suffix in ((960, ""), (600, "-600")):
        png = subprocess.check_output(
            ["inkscape", str(here / f"{name}.svg"), f"--export-width={width}",
             "--export-type=png", "--export-filename=-"]
        )
        with Image.open(BytesIO(png)) as image:
            image.save(here / f"{name}{suffix}.webp", "WEBP", lossless=True, method=6)
