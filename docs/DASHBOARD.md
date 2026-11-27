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

The per-card UTC selector retains the original METAR observation option. When the
published TAF has decoded forecast periods, a separate TAF option, a 30-minute
step slider and an exact-minute UTC date/time control become available. Changing
the control updates all runway-end head/tail and crosswind calculations at that
airport. The same 5/10/15-kt color thresholds and gust calculations apply.
The UI marks forecast mode in blue and labels the selected UTC time, TAF issue
time, publication time, and heading source; selecting the observation returns
to METAR-only runway values. Forecast selection lasts for the current browser
session and is preserved during routine rerenders, but is not saved between
visits. Other C070 airports do not get guessed ICAO mappings or forecast data.
Existing METAR calculations/70-minute freshness and ATIS extraction remain.

## TAF collection (SPA-74)

The AWC TAF updater runs from `.github/workflows/taf-update.yml` at six UTC minutes per hour (08/18/28/38/48/58) and supports manual dispatch. Each run makes one batched HTTPS request, validates station, raw text and issue/validity times, and saves decoded `fcsts[]` wind periods alongside the original raw TAF. An issue already saved by SPA-74 can gain its missing decoded groups on a later collection of the same issue. Malformed periods are excluded; temporary upstream omission of decoded periods does not erase previously saved groups. Missing stations retain their latest accepted reports; complete retrieval failures do not rewrite the file. The browser polls the published snapshot every two minutes and does not call AWC directly. CI uses synthetic responses without provider contact.

The raw TAF display places FM (six-digit start time), BECMG/BCMG, TEMPO, and PROB groups on new indented lines; a combined PROB30 TEMPO group stays together. This is display-only formatting: the original `rawTAF` text and source link are preserved. The timeline selects BASE and FM as prevailing wind periods. It displays TEMPO and PROB changes as separate alternative wind components with their source labels; a TEMPO/PROB group without wind does not invent an alternate wind. During a BECMG wind transition, runway components are unavailable because the exact change time is unknown. After the transition, the new wind is used until a later FM period. VRB winds, missing decoded winds and stale TAF issues have no calculated components. A TAF issue becomes stale only when it is more than six hours old. At exactly six hours from issuance, the TAF remains current if still valid. At or after its validity end (exclusive), a TAF instead displays **NO LONGER VALID** in red, even when the issue is under six hours old. Expired reports keep their raw source text but cannot supply runway forecast components; forecast controls are unavailable. Raw stale forecasts also remain visible, but stale forecast wind calculations are disabled. All times are UTC, and no aviation data is used to make runway-operation or flight-safety decisions.

The project has not independently verified a current live AWC decoded response for these four stations through this issue. Passing offline tests establishes only synthetic-case behavior. Production collection and a browser check against an actual saved `data/tafs.json` are separate verification conditions.

Following the owner's November 24, 2026 decision, the dashboard and its TAF forecast timeline are visible on the public homepage with a prominent WIP/unvalidated banner. This is not a validation of the data for operational use.

## Remaining acquisition dependencies

Current raw-NOTAM population across the 130-airport catalog still needs a trustworthy accepted live baseline/cutover, delta continuity, reviewed private request accounting and a separately authorized collection-to-publication path. Offline Initial Load decoding, airport association, message identity and synthetic delta candidate work have been merged in PRs #34–#38; these are not live FAA polling or permission to publish new data. Existing HTTP/history code from PR #22 remains separate. This UI work does not activate collectors, change schedules, consume FAA allowances or change production configuration.

## Public URL — owner decision November 24, 2026

`https://www.spatchin.com/` publicly serves the v0.9 WIP dashboard, with the banner **“WORK IN PROGRESS. Under development and not yet validated.”** The retired holding page is gone. The public root loads the existing root scripts, styles and `data/` snapshots directly without an extra `<base>` element. The historic `dashboard/index.html` copy remains for local tests but is excluded from GitHub Pages, as are synthetic preview and private staging source files. No login is required for the public homepage. The separately deployed Cloudflare `dev.spatchin.com` Worker and Access applications must be retired through Cloudflare, without weakening their authentication while they remain active.

No change to aviation data, acquisition cadence, evidence/NOTAM safeguards or the v0.9 version accompanied this public UI change.

## SPA-116 compact UI first pass

METAR and TAF raw text use 15 px Inconsolata, weight 400, line-height 1.3. The ordinary current METAR status is omitted; stale/unavailable/retained-data warnings and the existing threshold remain. ATIS omits the routine unofficial label and arrow glyphs while retaining noncurrent statuses, source links and expanded source warnings. Sources is closed by default and retains five separate entries: ATIS, METAR, TAF, UTC forecast selector and NOTAM reader.

## SPA-117 second UI pass

Uniform METAR, TAF and ATIS inset panels replace the former standalone report labels and asymmetric layout. Verified source links are embedded in the report's existing prefix (METAR/SPECI/TAF plus station, or station alone when the report omits the type). If no recognizable prefix is present, source access remains available separately. TAF CURRENT is omitted; stale, future, expired, unavailable and failed-refresh warnings are unchanged. SCAN literal phrases continue across inline source links. All acquisition and forecast calculations are unchanged.

## SPA-118 compact card and toolbar

Card headers use 9 px top padding, a 4 px text-row gap and 8 px clearance before METAR. The IATA remains 24 px, flight category 8 px, and airport name 12 px with ellipsis and accessible disclosure. Controls remain 44 px with independent placement. Collapsed SCAN and airport-add controls share a row, with equal 44 px height and a compact labeled input. Current ATIS direction labels omit the routine CURRENT suffix; abnormal states remain visible.
