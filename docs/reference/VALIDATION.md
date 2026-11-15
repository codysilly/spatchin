# Dashboard presentation cleanup validation

## Final upper-card correction

The final focused PR #24 follow-up applies the owner-supplied MEM close-up to the
airport card's upper presentation only. The tested source tree is the commit that
contains this section; its non-self-referential SHA is recorded in the PR update.
Changed source/test files are `app.js`, `dashboard.css`,
`docs/reference/VALIDATION.md`,
`tests/dashboard-design-browser.test.cjs`,
`tests/dashboard-refinement-browser.test.cjs` and `tests/scan.test.cjs`.

On November 14, 2026, the complete established native Windows JavaScript/browser
suite passed **77 tests, 0 failed, 0 skipped** in **29.574 seconds**. A corrected
focused visual rerun passed **4 tests, 0 failed, 0 skipped** in **4.263 seconds**
after normalizing the screenshot crop's scroll position. Tests remained serial,
used installed Chrome/Python and blocked external page/provider navigation. No
Python suite, package download or live aviation request was run.

The upper header now uses the requested airport-code/name hierarchy and keeps
verified chart dates only in the link title/accessibility description. METAR and
TAF use matching two-column grids; METAR freshness and exact raw observation
share one text edge without a visible wind-summary or observation-time row.
Parsed wind, observation time, gusts and runway calculations remain available to
lower controls and calculations. ATIS now has a roomier heading/provider/metadata
header, equal runway boxes and separated disclosure. Current, stale, unavailable
and retained-refresh states remain data-driven.

Actual-app visual evidence is outside tracked source at
`C:\Users\codys\Projects\niltsi\.test-output\dashboard-presentation-cleanup-2026-11-14-final-upper-card`.
Its 11 PNGs include 1440px/390px synthetic dashboards, 1440px/390px historical
MEM dashboards, historical and current/populated upper-card close-ups at both
widths, and a clearly labelled synthetic stale-METAR/unavailable-ATIS close-up.
Direct comparison with the supplied target found no material remaining layout
discrepancy; narrower production cards naturally wrap the airport name and raw
observation without overlap or page-level overflow.

## Base and scope

Worktree: `dashboard-presentation-cleanup`, branch
`feature/dashboard-presentation-cleanup`, from current origin/main
`1edddced6e6bf7f2d089cd6211cf25b5f64e759d`. Main already contains merged PR #22
HTTP/history integration and refined PR #23. Neither implementation was recreated
or cherry-picked. All prior worktrees, review images and private artifacts remain.

The owner-approved written cleanup supersedes PR #23's airport-wide reader and
technical presentation requirements. The named METAR/NOTAM annotation PNGs were
not found in the task attachment folder, Downloads root or supplied design-assets
folder; the written requirements were used without blocking. Both committed
original artwork hashes still match, and no approved aviation data, scripts,
workflows, snapshot loader, SCAN implementation or app version changed.

## Native Windows evidence

Validated November 14, 2026 on Windows 25H2 build 26200.9974, PowerShell
5.1.26100.9818, Node 22.18.0, installed Chrome 157.0.8103.51 and Playwright.
Existing native Python 3.12.10 serves localhost and supplies the existing offline
normalizer/browser contract tests. No WSL, new packages or provider requests.

Complete offline JavaScript/browser suite: **77 passed, 0 failed, 0 skipped**:

```powershell
$env:NODE_PATH='C:/Users/codys/Projects/spatchin/.test-output/preview-tools/node_modules'
$env:CHROMIUM_PATH='C:/Program Files/Google/Chrome/Application/chrome.exe'
node --require "$env:TEMP/mem-offline-python.cjs" --test --test-concurrency=1 --test-reporter=spec tests/*.test.cjs
```

The established temporary preload maps `python3` to the installed native Python
and blocks non-loopback Node socket connections. Browser contexts abort all
external page/provider requests before navigation; station links are checked by
href/attributes without opening them. No provider/DNS path is intentionally used.
Serial browser execution retains the previously documented bounded resource use.
Python behavior is unchanged; unrelated Python suites were not rerun.

## Assertions now checked

- Green METAR badge is the sole card METAR source hyperlink for verified KMEM,
  KORD, KLAX and KJFK. Exact destination is the owner-verified AWC page route
  `https://aviationweather.gov/data/metar/?ids=<station>`, with station-specific
  accessible names, keyboard focus, new-tab/noopener/noreferrer behavior and
  preserved green styling. No verified mapping means a noninteractive badge.
- `NOTAMs (n)` counts source records, including duplicate identifiers and records
  with no display text. Matching across original condition text and every provider
  representation, numeric month/year/family sorting and stable ties are unchanged.
- Single-column lists render only `formatted_texts` entries whose type is exactly
  LOCAL_FORMAT and whose text is a string. Multiple entries keep source order.
  Empty strings remain empty; absent string entries get exactly
  `LOCAL_FORMAT text unavailable.` No trim, punctuation edits or fallback to raw
  condition/ICAO/other text. Normalizer mapping is unchanged.
- CR, LF, CRLF, leading/trailing whitespace, Unicode and HTML-like literal text
  are compared exactly before/after SCAN, highlight removal, rerender and reload
  failure/recovery. Original loader input remains unchanged.
- No identifier headings/column, technical metadata/provenance disclosures,
  serialized source-record attributes, airport-wide reader/replacement or Show
  details markup exists, even hidden. Unmatched and airport-wide records remain
  in accepted data. Unique hidden ICAO/raw/metadata search terms produce zero
  SCAN matches; displayed LOCAL_FORMAT terms remain searchable.
- Long synthetic panels retain all 32 records, bounded named/focusable scroll
  regions, PageDown behavior, independent expansions and practical scroll/focus
  persistence. Forward/backward SCAN selects the final two lower notices, opens
  the correct collapsed panel and reveals each match in both internal region and
  page viewport. No nested marks or unrelated disclosure collapse.
- One per-airport coverage summary retains original retrieval, completeness,
  historical/no-update context and exact collection/legal warnings. Unknown,
  missing, no literal matches, explicitly verified zero and retained data stay
  distinct. Strict zero verification is unchanged. Failure/recovery still retains
  the last accepted snapshot. Internal loader check timestamps remain populated,
  while their old visible check-time lines are absent.
- Footer Remove airport retains preferences, 30-total selection behavior and
  deliberate empty selection across reload. Focus moves to a remaining card's
  removal control, or the airport-add input after the last card is removed.
- METAR raw observation/time/staleness/gusts/wind thresholds, ATIS interface,
  fixed verified MEM diagram URL/dates, WIP banner, original branding, v0.9 and
  all runway ends remain. At 1440px there are three columns; at 390px one column,
  readable data text/primary touch controls and no page-level horizontal overflow.

Initial focused assertions referencing the removed markup were replaced with
data-integrity/current-UI checks. A search test initially treated the comma in an
old disclosure title as a keyword separator; its terms were corrected to check
only removed phrases. There are no remaining failures in the complete serial run.

## Public historical MEM reconciliation

The approved snapshot is unchanged: **100 source records, 131 provider
representations: 48 LOCAL_FORMAT and 83 ICAO**, all retained in memory/data.
Every runway's displayed strings are compared against its associated records'
LOCAL_FORMAT entries. This is **not** a claim that all 131 representations or all
100 records are rendered. Unmatched/airport-wide data has no replacement reader.
Source-record associations are unchanged when LOCAL_FORMAT is missing.

Original retrieval: `2026-11-13T02:52:31.040326+00:00`. Final screenshots show
39 hours since retrieval, UNKNOWN coverage, fixed snapshot/no automatic updates
and original collection warning. Reported times do not imply operational validity.

## Actual running-app screenshots

Persistent review directory outside source:
`C:\Users\codys\Projects\niltsi\.test-output\dashboard-presentation-cleanup-2026-11-14`.
Tests emit these through `SPATCHIN_SCREENSHOTS` (temporary directory by default):

- `synthetic-1440.png`, `synthetic-390.png`: unmistakably synthetic multi-airport
  dashboards with an expanded long LOCAL_FORMAT list.
- `synthetic-scan-1440.png`, `synthetic-scan-390.png`: actual SCAN selection of
  LOWER_MATCH_B near the bottom of that list, reached through navigation.
- `public-historical-mem-desktop.png`, `public-historical-mem-mobile.png`:
  unchanged local public historical MEM snapshot; distinct from synthetic data.

The six PNGs are opened locally and packaged together for owner attachment/review.
The ZIP is checked to contain exactly those six byte-matching files. No screenshot,
capture or production snapshot is added to this source/test/documentation commit.
These are implementation evidence; owner acceptance of this new cleanup remains
pending, separate from prior approval of merged PR #23.

## Remaining limits

TAF/forecast remain unavailable. Only existing verified airport metadata/feeds
are supported; diagram links are not guessed or fetched. The FAA initial-content
decoder task has **not started**. No acquisition progress, schedule, collection,
history/accounting import, paid service, merge or deployment is part of this work.
