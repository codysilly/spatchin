# Local published NOTAM snapshot loading

The dashboard loads only `./data/notams.json` on its own origin, once at startup.
“Reload NOTAM snapshot” reads that same published file. It never runs an updater,
contacts NMS, authenticates, follows redirects, or schedules collection. Concurrent
reloads share one in-flight request. Clock updates, airport changes, SCAN and
ordinary rerenders do not trigger another NOTAM fetch. Existing aviation-feed
schedules are unchanged.

A separately reviewed, fixed production snapshot is now published at `data/notams.json`. As inspected on 2026-11-20, it contains 38 KMEM notices, `completeness: UNKNOWN`, retrieval timestamp `2026-11-15T10:39:04.087408+00:00`, and `automatic_updates: false`. Its existence is not proof of live FAA collection or 130-airport data coverage. A missing file still produces NOTAM data unavailable. Production rejects explicitly synthetic snapshots. A local synthetic transport and inventory
are available only in the separate `preview/snapshot-loader.html` harness.

## Accepted input and failure behavior

Input follows the merged offline adapter's reader contract: a parseable,
timezone-qualified retrieval timestamp, an airports object with per-airport notices
arrays, optional warning/completeness strings, display strings or nulls, optional
string warnings and separately typed text representations. Original features and
other metadata survive validation; duplicates are retained. Missing notice text and
raw reported effective-time strings are allowed. Validation makes no claim about
provider semantics, original-text completeness, scope, applicability or lifecycle.

HTTP/JSON/schema errors, timeouts, synthetic production input, retrieval times in
the future, and snapshots older than the accepted snapshot are rejected. The last
accepted snapshot remains mounted with a failure warning. With no accepted data,
the reader shows unavailable and UNKNOWN coverage. A successful empty collection
is not proof that there are no NOTAMs. Snapshots are retained only in the current
page session; reloading the entire page starts a new load. Nothing is written to
localStorage, preferences, a database, or the request ledger.

The display separates source retrieval time from the browser's last attempt and
successful-check times. No production age/staleness threshold is invented: users
continue to see the retrieval time and the explicit “Freshness policy not
established” message. Future times are rejected, so a bad future snapshot cannot
prevent subsequent recovery with valid current data.

Reader disclosures, summary focus and reload-button focus survive rerenders;
SCAN observes inserted notice text normally. Reload controls describe only local
published-file loading and do not expose provider-refresh actions.

## MEM runway inventory

The current `data/runways.json` contains eight MEM runway ends, added through PR #13 from the supplied airport chart. The headings are chart-derived approximate true bearings, not newly verified NASR runway survey measurements. This documentation does not run the updater or change runway data. Malformed incoming MEM data still requires rejection with retention of the previous valid snapshot.

## Offline verification and review

Run Python tests with the network-blocking harness in preview/README.md. Run Node
unit and VM integration tests with:

```sh
node --test tests/airport-storage.test.cjs tests/notam-reader.test.cjs \
  tests/notam-snapshots.test.cjs tests/notam-snapshot-app.test.cjs
```

Run browser/SCAN regressions in a browser-capable environment with:

```sh
CHROMIUM_PATH=/usr/bin/chromium node --test tests/*.test.cjs
```

Browser suites block external requests. New desktop/390px cases route explicit
synthetic NOTAM and eight-end runway fixtures at the local HTTP boundary; neither
fixture is published. Review `/preview/snapshot-loader.html` on a local server.
Try success, failed refresh, malformed input and an older snapshot. Confirm retained
notices and timestamps, then use SCAN and inspect focus/disclosure behavior. Check
production's initial unavailable state separately. Screenshots, if browser checks
succeed, go to `/tmp/spatchin-snapshot-review/`.

This implementation session attempted Chromium but its process-singleton socket
was denied by the runtime (Operation not permitted). No browser/layout pass is
claimed. Browser regressions and user visual review are required before merge.
