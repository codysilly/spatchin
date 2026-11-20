# Spatchin UI design baseline

**Audited 20 November 2026 against GitHub `main` at `023ecaeed3c7384abde782343e60363445e51f71`.**

This is the **current** dashboard appearance contract, not a new mockup. The latest functional UI redesign is [SPA-65 / PR #50](https://github.com/codysilly/spatchin/pull/50), merged as `79259221a774436c2a6bae0e8112a1f97eb2aa64`. It supersedes conflicting details in [SPA-63 / PR #39](https://github.com/codysilly/spatchin/pull/39): the airport code is now compact; the four-segment flight-category strip is gone; the remove control is in the header; raw METAR is an inset panel. Later merges through the audit baseline updated aviation feeds/workflows and branding, **not** this dashboard layout.

## Source of truth and precedence

1. `index.html` and `app.js`: current structure and semantic/UI behavior.
2. `charcoal-dashboard.css`: **effective visual overrides**; loaded after `styles.css` and `dashboard.css`.
3. This document: approved values and the rationale for retaining them.
4. `BRANDING.md`: airplane geometry, gradient, wordmark tracking and raster icons. It is authoritative for the logo and should not be duplicated or reinterpreted here.

The three loaded CSS layers still contain superseded blue-theme and prior-layout declarations. The late charcoal overrides keep the live design consistent, but removing old declarations requires a separate, screenshot-tested refactor; see SPA-68. Do **not** choose an earlier CSS value without checking final computed styles.

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
- Wordmark: see `BRANDING.md` (desktop tracking `0.0325em`; compact mobile `0.0175em`). The logo is **60 px desktop, 52 px ≤760px, 46 px ≤400px**.
- Airport IATA: **60 px**, weight 700, tracking `-0.045em` on desktop; **56 px ≤1300px**, **54 px ≤760px**, **48 px ≤400px**.
- Airport name: **18 px** muted (17 px ≤400px); baseline aligned under the IATA after the handle.
- Raw METAR: **21 px**, line-height **1.6**, preserved whitespace; **20 px ≤400px**. Never reformat or decode the original report merely for style.
- Runway data values: Inconsolata, generally **16 px** (15 px ≤760px); table column labels are small bold Overpass.

## Geometry, lines and spacing

- **Sharp corners:** 0 px radius on cards, ATIS, reader, controls and inputs; no shadows or decorative background gradients. The current SCAN keyword chip may use a small 2 px radius and the focus ring may use an outline.
- **Outlines:** generally **1 px solid `--line`**. Runway row dividers use the same 1 px line; links and actions are cyan; visible keyboard focus uses a 2 px cyan outline (some legacy, reader-specific selectors have stronger focus styles).
- Card grid: **3 equal columns**, **16 px gap** by default; **2 columns at ≤1120px**; **1 column at ≤760px**, **14 px gap** on mobile.
- Header: keep the full UTC clock readable at normal sizes; at **≤340px** the clock moves to a second, right-aligned header row rather than overflowing or shrinking the approved logo.
- Main content padding: **14 px top / 28 px sides / 36 px bottom** desktop, **12 / 14 / 28 px** at ≤760px.
- Card padding: **20 px top, 22 px sides/bottom** desktop; **16 px ≤760px**, **12 px ≤400px**.
- Dashboard controls-to-cards separation: **40 px** desktop; **22 px ≤760px**.
- Airport header row: **six-dot grip** (44×44 px), code, single flight-category badge, flexible spacer, verified airport-diagram link if known, **× remove button** (44×44 px). Second row is the airport name, indented 50 px (48 px on mobile). No four-segment flight-category bar.
- Bordered METAR hero immediately below header: inset background, **12 px top / 14 px sides / 14 px bottom** padding on desktop; **10 / 12 / 13 px** ≤760px. Small muted source label with the raw text below.
- Compact runway rows: **7 px vertical cell padding** and 1 px dividers. The inline NOTAM reader and snapshot warning remain associated with their airport; no inference of operational runway availability.
- Section rhythm is intentionally uneven: TAF-to-ATIS spacing about **26 px**, ATIS bottom margin **30 px**, NOTAM summary bottom **18 px**. Avoid replacing this with uniform padding.

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
