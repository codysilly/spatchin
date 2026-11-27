# Spatchin branding

**Current artwork approved November 27, 2026 — SPA-122.** This supersedes the airplane artwork used in SPA-64, SPA-66 and SPA-116. The compact header size and wordmark typography from SPA-116 remain unchanged.

## Canonical airplane mark

The master source is `assets/branding/paperplane-cyan-magenta-fade.svg`, supplied by the owner on November 27, 2026. It uses a 1254 × 1254 viewBox, two filled paper-airplane paths, and a diagonal cyan-to-magenta gradient. **Do not redraw, reconstruct or recolor the owner-supplied artwork.**

- Outer/fold edges are integrated into the vector silhouette. The body gradient uses the same tail-to-nose axis and its color is layered beneath the more opaque edge/fold details.
- Tail-to-nose gradient: cyan `#04e3ed` → blue `#31bafc` → violet `#8979fe` → purple `#c837f2` → magenta `#f312d9`.
- The original supplied `paperplane-cyan-magenta-fade.png` is a **1254 × 1254 transparent RGBA image**. Local pixel comparison confirmed it is identical to a CairoSVG render of the supplied SVG. The uploaded PNG remains available in the owner's original source material; it is not necessary to store the large PNG in the published site.
- Header image: **18 × 18 px** at all viewport widths, as specified in `charcoal-dashboard.css`.
- Browser favicon: the canonical SVG and resized, transparent `paperplane-16.png` and `paperplane-32.png` fallbacks.
- Apple touch icon: `paperplane-180.png`. These three PNGs are derivatives, not independent artwork.

To regenerate the three published PNGs from the SVG, run `python scripts/render-brand-icons.py`. The development-only dependencies are CairoSVG and Pillow; the live site has no new dependency or external image request.

## Wordmark

Render **SPATCHIN** as selectable text, separate from the airplane:

- Inconsolata Bold, weight 700, color `#e6e6e1`.
- Desktop letter spacing `0.0325em`; ≤400px letter spacing `0.0175em`.
- Keep the muted `v0.9` label. Branding updates do not authorize application version increments.
- Overpass remains the interface font; Inconsolata remains the aviation-data font.

## Asset retirement and maintenance

On November 27, the owner explicitly authorized retirement of all seven previous `assets/branding/` assets: `logo-cyan-magenta.svg`, `logo-16.png`, `logo-32.png`, `logo-64.png`, `logo-128.png`, `logo-180.png`, and `spatchin-logo-source.png`. These are no longer in the current Git tree; Git history preserves their previous contents if recovery is ever needed.

When new artwork is approved, update root `index.html`, the compatibility `dashboard/index.html`, the staging manifest/check, the existing Pages asset allowlist entries, this document, and the offline asset tests. Remove obsolete references before retiring files. Do not enlarge the public asset surface or alter GitHub Pages configuration in the course of branding work.

Verify `node --test tests/branding-assets.test.cjs`, the full offline frontend and staging tests, visual appearance at 18px, and successful GitHub Pages deployment of the exact merge commit. The artwork does **not** change METAR, ATIS, NOTAM, SCAN, runway or any aviation calculations.
