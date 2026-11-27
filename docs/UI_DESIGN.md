# Spatchin UI design baseline

**SPA-116: compact UI first pass, owner approved 27 November 2026.**

This is the **current** dashboard appearance contract, not a new mockup. The previous functional UI redesign was [SPA-65 / PR #50](https://github.com/codysilly/spatchin/pull/50), merged as `79259221a774436c2a6bae0e8112a1f97eb2aa64`. It supersedes conflicting details in [SPA-63 / PR #39](https://github.com/codysilly/spatchin/pull/39): the airport code is now compact; the four-segment flight-category strip is gone; the remove control is in the header; raw METAR is an inset panel. SPA-116 supersedes the earlier header, airport identifier, report typography, freshness labels, ATIS labels and Sources presentation.

## Source of truth and precedence

1. `index.html` and `app.js`: public dashboard structure and semantic/UI behavior (`dashboard/index.html` is a local compatibility copy).
2. `styles.css`: consolidated **structural foundation**, containing layout, SCAN, ATIS, NOTAM reader and accessibility utilities (SPA-68).
3. `charcoal-dashboard.css`: **authoritative current palette and component appearance**, loaded after `styles.css`.
4. This document: approved values and the rationale for retaining them.
5. `BRANDING.md`: airplane geometry, gradient, wordmark tracking and raster icons. It is authoritative for the logo and should not be duplicated or reinterpreted here.

SPA-68 consolidated the original `styles.css` and `dashboard.css` into one structural `styles.css`, removed the superseded navy theme roots and gradients, and retired the `dashboard.css` file. Old component-compatibility rules remain only where needed for computed-style parity and SCAN/NOTAM functionality. SPA-65's obsolete category-strip and footer-remove selectors were removed. The charcoal layer retains the approved appearance. Do **not** infer final styling from an earlier foundation rule without checking computed styles.

## Palette

| Purpose | Effective value | Use |
| --- | --- | --- |
| Main background / card background | `#1b1d1f` | Page, airport cards and header |
| Inset surface | `#151617` | METAR, NOTAM and selected controls |
| Border / divider | `#3a3d40` | Thin panel outlines, table hairlines, separators |
| Primary text | `#e6e6e1` | Headings and primary data |
| Muted text | `#a3a6a8` | Descriptions, metadata, unavailable states |
| Warning / label | `#ffb000` | Staleness, NOTAM headings and SCAN label |
| Link / action | `#4fd1e6` | Links, outlined action buttons and focus ring |
| Headwind / VFR | `#b4e33d` | Headwind values and VFR badge |
| MVFR | `#4fd1e6` | Flight-category badge |
| IFR / high tailwind or crosswind | `#ff6b6b` | Flight badge and wind values |
| LIFR | `#ff4fd8` | Flight-category badge |

These colors are CSS custom properties at the top of `charcoal-dashboard.css`: `--bg`, `--panel`, `--panel2`, `--line`, `--text`, `--muted`, `--blue`, `--amber`, `--green`, `--red` and `--flight-*`.

**Limited exceptions:** the development warning banner uses a brown/gold warning treatment, link hover is lighter cyan (`#8deaff`), interactive selection backgrounds use charcoal shades (`#243034`, `#292c2e`), and SCAN highlight colors can vary by keyword. The approved *airplane logo itself* uses a cyan-to-magenta gradient; the restriction on decorative gradients applies to **dashboard surfaces**, not that mark.

## Typography

- **Overpass** (400, 600, 700, 800): headings, airport names, interface labels, controls.
- **Inconsolata** (400, 700): SPATCHIN wordmark, IATA airport code, coded METAR/TAF/ATIS, numeric weather, runway rows and UTC timestamps. Local fallback stacks are defined in `--font-ui` and `--font-data`.
- Wordmark: see `BRANDING.md` (desktop tracking `0.0325em`; compact mobile `0.0175em`). The logo is **18 px** at all widths; the desktop header targets 22 px.
- Airport IATA: **24 px**, weight 700, tracking `-0.045em` at all widths.
- Airport name: **12 px**, weight 500, line-height 1.15, muted, one line with ellipsis. Full name is available through the title and a keyboard/touch toggle.
- Raw METAR: **15 px**, weight 400, line-height **1.3**, preserved whitespace. Raw TAF uses the same typography. Never reformat or decode the original report merely for style.
- Runway data values: Inconsolata, generally **16 px** (15 px ≤760px); table column labels are small bold Overpass.

## Geometry, lines and spacing

- **Sharp corners:** 0 px radius on cards, ATIS, reader, controls and inputs; no shadows or decorative background gradients. The current SCAN keyword chip may use a small 2 px radius and the focus ring may use an outline.
- **Outlines:** generally **1 px solid `--line`**. Runway row dividers use the same 1 px line; links and actions are cyan; visible keyboard focus uses a 2 px cyan outline (some legacy, reader-specific selectors have stronger focus styles).
- Card grid: **3 equal columns**, **16 px gap** by default; **2 columns at ≤1120px**; **1 column at ≤760px**, **14 px gap** on mobile.
- Header: keep the full UTC clock readable at normal sizes; at **≤340px** the clock moves to a second, right-aligned header row rather than overflowing or shrinking the approved logo.
- Main content padding: **14 px top / 28 px sides / 36 px bottom** desktop, **12 / 14 / 28 px** at ≤760px.
- Card padding: **9 px top** at every width; 22 px sides/bottom desktop, 16 px ≤760px, 12 px ≤400px.
- Dashboard controls-to-cards separation: **40 px** desktop; **22 px ≤760px**.
- Airport header uses a content-driven IATA/badge row and one name line (4 px gap, 8 px to METAR). The grip and diagram/remove controls occupy independent columns spanning both text rows, each with a 44 px touch target. Flight badge is 8 px, 8 px clear horizontal gap and bottom-aligned to the IATA glyphs. No four-segment category bar.
- METAR, TAF and ATIS use equal-width bordered inset panels: **12 px vertical / 14 px horizontal** padding on desktop; **10 / 12 px** ≤760px. Raw METAR and TAF start without standalone labels, with source links on their original opening station text.
- Compact runway rows: **7 px vertical cell padding** and 1 px dividers. The inline NOTAM reader and snapshot warning remain associated with their airport; no inference of operational runway availability.
- Weather panel spacing is **10 px** between panels. NOTAM summary spacing is unchanged.

## UI behavior that styling changes must preserve

- Airport order: six-dot grip supports pointer/touch and keyboard reordering, persists under `spatchin-airports`. Up to 30 airports; MEM is removable.
- Flight badge: use only AWC-provided `fltCat`. Its value is the limiting category of ceiling and visibility; a stale report remains marked stale. Missing data gets **NO DATA**, not an inferred value.
- SCAN searches/highlights current dashboard content, case-sensitive when requested, and maintains an accessible navigation/count display.
- Keep the full runway-end list, original NOTAM text, notices with unknown coverage, source links and UTC/Zulu labels. **Never conceal warnings** to match a screenshot.
- ATIS and METAR data-source statuses and any unavailable/unsupported states remain visible. Do not invent forecasts or recency.

## Validation and change procedure

- Run the existing offline frontend checks, with **computed-style browser assertions** at 1440, 1120, 760, 390 and 320px (effective palette, 1px lines, square corners, typography, spacing, 44px controls and horizontal overflow). Check the intentional ≤340px clock wrap; recheck intermediate layouts if changing breakpoints.
- Compare synthetic browser screenshots when changes affect real page geometry or wrapping. Do not claim public-site pixel parity from source review alone.
- If values change after an owner-approved redesign, update this document and its tests in the **same PR**. Maintain `v0.9` unless the owner authorizes a version increment.
- This visual specification is not a license to change the FAA acquisition cadence, NOTAM semantics, or aviation calculations.

## Public site routing (owner decision: 2026-11-24)

The public root (`/`) once again serves the **working v0.9 dashboard**, not a holding page. At the top of the page, a prominent charcoal/amber banner reads exactly **“WORK IN PROGRESS. Under development and not yet validated.”** The same warning remains in `dashboard/index.html` for legacy offline tests. The primary public document is now `index.html`, with root-relative static asset resolution and no `<base href="../">` override. It loads `styles.css` followed by `charcoal-dashboard.css`.

Jekyll continues to exclude the legacy duplicate `dashboard/`, synthetic `preview/`, and retired private staging source `staging/`. No private login or Cloudflare Access check is required to view the public homepage. The old `dev.spatchin.com` Cloudflare resources are an external account cleanup task, not part of the GitHub Pages serving path. Keep aviation warnings, source links, data acquisition and version safeguards unchanged.

## SPA-116 compact display

The application header uses an 18 px solid gradient airplane, 14 px wordmark and 13 px UTC clock (12 px at narrow widths). The WIP banner is unchanged. Current METAR reports omit the routine status label; stale, unavailable and failed-refresh warnings remain. ATIS landing/departing labels omit arrows and the routine unofficial label; noncurrent warnings and source disclosure remain. Sources is a native details disclosure, closed by default, with five entries in owner-specified order. Preserve the distinction between forecast and observed winds in their controls and labels; retain heading-source warnings in their original context.

## SPA-117 second UI pass

Flight-category text is 8 px with 1 px vertical and 2 px horizontal padding and 4 px additional left separation. ATIS uses 15 px Inconsolata, weight 400 except runway values (700), line-height 1.3. Current TAF status is silent; all noncurrent warnings and source times remain. Links preserve original display tokens, and SCAN treats linked prefixes plus the remainder of a report as one logical text stream. When a verified station has no recognizable report prefix, retain an explicit source link. The existing logo is unchanged pending original artwork.

## SPA-118 third UI pass

The collapsed SCAN toggle, IATA input and Add button are 44 px high on one toolbar row; SCAN gets the flexible width, the input fits its placeholder and has an accessible name instead of a visible label. One parent gap matches the card grid (16 px desktop, 14 px mobile). At narrow widths show the numeric active-keyword count with the full label accessible. When expanded, the SCAN panel uses the full toolbar width; older browsers without subgrid may wrap the airport controls while SCAN is open. Airport names remain one line until deliberately expanded, and expanded state/focus survive refresh. Normal ATIS labels are LANDING and DEPARTING; all abnormal suffixes remain. No change to source content, calculations, logo, version or acquisition.
