#!/usr/bin/env python3
"""Build all favicon PNGs from the approved SVG, without altering its geometry.

Developer dependencies (not website dependencies): pip install cairosvg pillow
"""
from io import BytesIO
from pathlib import Path

try:
    import cairosvg
    from PIL import Image
except ImportError as error:
    raise SystemExit("Install development packages: pip install cairosvg pillow") from error

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "assets" / "branding"
MASTER = BRANDING / "logo-cyan-magenta.svg"

def main():
    for size in (16, 32, 64, 128, 180):
        # Render at 4x for antialiasing of the sharp, thin diagonal.
        rendered = cairosvg.svg2png(
            url=str(MASTER),
            output_width=size * 4,
            output_height=size * 4,
        )
        img = Image.open(BytesIO(rendered)).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        colors = 64 if size == 16 else 128
        img = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE,
                           dither=Image.Dither.NONE)
        output = BRANDING / f"logo-{size}.png"
        img.save(output, optimize=True)
        print(f"{output.relative_to(ROOT)} ({size}×{size})")

if __name__ == "__main__":
    main()
