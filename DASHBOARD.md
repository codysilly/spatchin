# Dashboard reader and design

The effective palette, typography, spacing, component outlines and responsive
breakpoints are recorded in [UI_DESIGN.md](UI_DESIGN.md). SPA-65 / PR #50
supersedes SPA-63 for the compact airport heading, category badge, METAR panel
and header removal/reordering controls. The paper-plane artwork is specified
separately in [BRANDING.md](BRANDING.md).

Spatchin remains v0.9 and is not ready for actual use. This reader indexes literal
runway references; it performs no closure, reciprocal, lifecycle or schedule interpretation.
All approved aviation snapshots remain unchanged.

## Notice presentation

Each runway has an independent `NOTAMs (n)` toggle and a following detail row
spanning the four runway-table columns. The bounded region contains a simple,
single-column list of complete **LOCAL_FORMAT** strings, visually separated by
source record. No identifier column, reconstructed headings, raw condition text,
ICAO/other representations or technical metadata is rendered, even in hidden DOM.
Source records with duplicate IDs remain distinct. Multiple LOCAL_FORMAT strings
keep source order and render once each within a record; CR, LF, CRLF, Unicode,
whitespace and markup-like text are preserved exactly with safe escaping.

Matching still indexes the original source fields and all provider representations.
Counts are associated **source-record counts**, not displayed string counts. Missing
LOCAL_FORMAT does not erase an association: show `LOCAL_FORMAT text unavailable.`
when no string entry exists. A supplied empty string renders as an empty string,
never as another representation or reconstructed notice. The normalizer's mapping
is unchanged; `formatted_texts` entries retain provider type and source field.

Named, keyboard-focusable, viewport-bounded scroll regions retain sticky runway
captions. Routine rerenders
retain practical scroll position/focus; explicit SCAN navigation reveals its target
inside the region and page viewport. Mobile source text is 14px, secondary text
at least 12px in the data labels, and primary touch controls at least 44px tall.

There is no airport-wide reader or replacement view. All original records,
representations, metadata, unmatched and airport-wide records remain in the
accepted snapshot and existing storage architecture. The published fixed MEM snapshot inspected on November 20, 2026 contains **38** notices and **59** provider text representations (38 LOCAL_FORMAT, 21 ICAO), retrieved 2026-11-15 10:39 UTC. Completeness remains UNKNOWN and automatic updates are disabled; this is not a live or complete airport feed.
Only associated LOCAL_FORMAT text is rendered and searchable. Source-data
preservation is checked in memory, not by claiming 131 DOM-rendered representations.

Sorting is ascending: explicit four-digit source year first (records without one
follow), then domestic, international, other, missing identifier families. Domestic
month and serial are numeric. International series, source suffix year and serial
use deterministic natural-numeric comparison, without expanding two-digit years.
Other identifiers use natural numeric tokens; ties preserve source order. Dates do
not supply missing years. Neither sorting nor matching changes original records.

Unavailable collections, unknown coverage and no literal matches have different
labels. Empty collections do not establish zero coverage. A display of explicitly
verified zero requires all of: an empty notices array, `completeness: "VERIFIED"`,
`zero_verified: true` and a nonempty `verification_reference`. These are explicit
local publication assertions, **not inferred FAA fields**. No current production
snapshot supplies this evidence. Elapsed snapshot age is shown without inventing
a freshness threshold. Existing collection warnings survive failed reloads.
The running dashboard shows this context once in the prominent per-airport
summary, with concise row labels associated through aria-describedby. Original
collection/legal warnings and failed-reload retention/recovery remain visible.

MEM's fixed diagram header link and dates are preserved from verified metadata
in commit `a986cedf13bcde536987848b16bf91d2d1213eff`; no URL is constructed.
The chart is effective 2026-10-29 through 2026-11-26, not automatically refreshed.
No verified diagram links exist locally for ORD, LAX, JFK or catalog-only airports.
The NASR bearing-source ZIP remains in the underlying runway data, never used as
a diagram. The removed card-details disclosure is not retained in hidden markup.

## METAR panel and airport actions (SPA-65)

Each configured airport has a separate **bordered inset METAR panel**. Its small,
muted METAR source label links to
`https://aviationweather.gov/data/metar/?ids=<verified ICAO>`. Only existing
verified station mappings are used; unknown mappings get a noninteractive label
with an accessible unavailable explanation. Links use a station-specific accessible
name, visible focus, `target="_blank"` and `rel="noopener noreferrer"`. No link
is fetched by the application or by offline tests. General site Sources remain.

The coded METAR remains unmodified in 21px Inconsolata (20px on compact mobile);
observation time, freshness, gusts and component/color calculations remain.
Show details and its duplicate fields/explanations are removed.

The **header**, not the footer, now contains a six-dot 44×44 reorder grip and
a 44×44 × remove button. Pointer, touch and keyboard reorder preserve the
saved `spatchin-airports` order. Removal focuses the next/previous remaining
card's removal control, or the add-airport field when empty. The footer retains
the NOTAM snapshot reload action and the label
`Published snapshot · No live provider request`; internal loader check timestamps
remain available to the data loader but are not displayed.

## Airport and time controls

`airport-catalog.js` contains the owner's 130-code export of approved C070
Sheet1!A1:A130, supplied locally on 2026-11-14, from
https://docs.google.com/spreadsheets/d/17J10F734gVQ5XfTDkPzEoYQZPZMvZ1CUmb8Ghw05fmA/edit.
The export is the selection authority, not verified airport metadata. For example,
DJT is retained verbatim, not corrected by guessing. Only the existing four airport
ICAO/name mappings and published feeds are available. Other selected airports show
unavailable metadata/data; no K-prefix mapping or provider lookup is attempted.
Existing saved selections remain usable; new additions must be catalog members.
Maximum 30 total, MEM is removable, and an intentional empty selection persists.

The per-card UTC dropdown contains the actual published observation with its UTC
date, or observation unavailable. Forecast is disabled. Each card retains a valid
selection through rerender; a new observation replaces an obsolete observed-time
option. There is no forecast timeline, TAF feed, or forecast computation. Existing
METAR calculations/65-minute freshness and ATIS explicit-clause extraction remain.

## Remaining acquisition dependencies

Current raw-NOTAM population across the 130-airport catalog still needs a trustworthy accepted live baseline/cutover, delta continuity, reviewed private request accounting and a separately authorized collection-to-publication path. Offline Initial Load decoding, airport association, message identity and synthetic delta candidate work have been merged in PRs #34–#38; these are not live FAA polling or permission to publish new data. Existing HTTP/history code from PR #22 remains separate. This UI work does not activate collectors, change schedules, consume FAA allowances or change production configuration.
