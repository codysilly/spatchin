# Spatchin branding

**Geometry approved 19 November 2026; solid fill and compact header approved 27 November 2026 (SPA-116).**

## Canonical airplane mark

The master asset is `assets/branding/logo-cyan-magenta.svg`. Do not replace its geometry with a different paper airplane.

- Sharp corners and the original silhouette and fold geometry. The body has a solid gradient fill; the original outline overlays it as dark translucent fold detail.
- Tail-to-nose gradient **cyan → blue/violet → magenta**, running diagonally from the lower-left folded tail to the upper-right nose. This is **not** a left-to-right horizontal fade.
- Stops in the current SVG: `#04e3ed` (0), `#31bafc` (0.24), `#8979fe` (0.52), `#c837f2` (0.73), `#f312d9` (1).
- The header displays the SVG at **18 × 18 px** at all viewport widths. Responsive values are in `charcoal-dashboard.css`.
- The same vector is linked as the SVG favicon. PNG sizes **16, 32, 64, 128, 180** in `assets/branding/` are raster derivatives, not independent artwork. The 16px/32px PNGs are browser fallbacks; 180px is the Apple touch icon.

Run `python scripts/render-brand-icons.py` after an approved SVG change to regenerate all PNG derivatives. The local script requires **CairoSVG** and **Pillow** (developer-only dependencies; no runtime package or provider request). Commit the SVG and raster derivatives together.

`assets/branding/spatchin-logo-source.png` is retained as an **original/historical source**; it is not the current icon and must not be substituted for the approved vector.

## Wordmark

Render **SPATCHIN** as selectable text, not part of the airplane image:

- Inconsolata Bold 700; `#e6e6e1`.
- Desktop letter spacing `0.0325em`; ≤400px letter spacing `0.0175em`.
- Separate muted `v0.9` version label. Do not increment application version for branding changes.
- Overpass remains the interface text font; Inconsolata is the aviation-data font.

## Maintenance and checks

- Keep all five PNGs consistent with the master SVG; update the browser favicon and Apple touch icon together.
- Run `node --test tests/branding-assets.test.cjs` and the existing offline frontend checks. Review the 16px favicon on dark and light tab backgrounds and the 180px home-screen icon.
- These are visual brand assets only: they do not change aviation data sources, runway state, NOTAM interpretation or source freshness.

**History:** PR #48 introduced a nonmatching airplane and gold-era PNG fallbacks. PR #49 corrected the primary SVG to the owner-approved shape and gradient. SPA-66 aligns every PNG fallback to that final SVG.
