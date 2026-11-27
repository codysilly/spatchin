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
MASTER = BRANDING / "paperplane-cyan-magenta-fade.svg"

def main():
    # The approved owner source is 1254 × 1254. Render it at native size,
    # then generate the browser and Apple icon derivatives.
    rendered = cairosvg.svg2png(url=str(MASTER), output_width=1254, output_height=1254)
    master = Image.open(BytesIO(rendered)).convert("RGBA")
    for size in (16, 32, 180):
        img = master.resize((size, size), Image.Resampling.LANCZOS)
        colors = 64 if size == 16 else 128
        img = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE,
                           dither=Image.Dither.NONE)
        output = BRANDING / f"paperplane-{size}.png"
        img.save(output, optimize=True)
        print(f"{output.relative_to(ROOT)} ({size}×{size})")

if __name__ == "__main__":
    main()
