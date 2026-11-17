# SPA-10: one-PC, offline-tested refresh engine (not activated)

## SPA-56 supervised opaque Initial Load capture (not authorized to run)

`scripts/capture_initial_load.py` is a separate, capture-only procedure for the
documented all-classification `GET /nmsapi/v1/notams/il?allowRedirect=false`.
Its default invocation is a read-only review: it opens the existing migrated
Spatchin private ledger read-only, reports the account-wide bulk gate and a
distinct operation-approval digest, checks local disk headroom, and reads neither
credentials nor network.  It never reserves an allowance or creates evidence.

Only a future, separately owner-approved `--execute` invocation can use the
existing account-bound Store. It permits exactly one OAuth POST, one IL GET and,
only if the validated JSON control envelope supplies it, one same-host
authenticated content GET. Every call is durably reserved before I/O. Redirects,
non-200 responses, malformed/expired/cross-host content paths, timeout, TLS and
network failure stop without retry. The path does not call the decoder, accept an
outbox, establish a baseline, set a watermark, or write public data.

The legacy 64 MiB/30-second in-memory adapter remains the collector default.
This capture path uses its new bounded streaming mode: 1 GiB maximum opaque
content, 64 KiB chunks, and a five-minute per-call elapsed deadline. It requires
at least 1 GiB free in the existing private-ledger volume before approval. Content
is written first as a protected `content.partial`; success flushes and atomically
renames it to `initial-load.bin`, while partial data remains private evidence on
failure and the ledger's failed reservation is retained. A protected receipt holds
UTC capture start/completion, per-stage reservation times, byte count and SHA-256
but never URLs, tokens, headers or raw notices. The five-minute content-path bound
is checked before starting that one GET; provider material does not establish a
requirement that a hash-valid transfer must finish before temporary-path expiry.
Initial control bytes remain in the existing private response history;
the large opaque artifact remains under its existing private ledger directory,
not a new account store.

The engine uses explicit injected dependencies. The separate `nms_http.py` adapter
now implements one bounded HTTPS call when invoked; import/construction do not
connect. `import_nms_history.py` defaults to a read-only review and writes only
with an explicit approved digest. Neither integration has been activated on
production. There are no environment credential reads, schedules, website writes,
notice commits or v0.9 changes. No new service, hosting, dependency or distributed infrastructure is
needed. `sqlite3` is part of the tested native Python runtime.

The **private accepted outbox** is the publication handoff. The existing website
and `data/notams.json` are never opened for writing by this collector. Automatic
Git/Pages publication is deliberately absent. Publication failure/preflight and
outbox transaction failure retain the previous accepted bytes and cursor; an
ambiguous disk/commit outcome requires manual reconciliation before any export.

## Supplied contract, used without provider clarification

- [OpenAPI 1.0.18, revised 2026-02-12](https://drive.google.com/file/d/1Jbf-YgCDZ-TMVoPQyS5LraGXw_ThtM7M/view).
- [Supplied NMS FAQ](https://drive.google.com/file/d/1RazUuGb3o5xEkEUXon8_XR70K-KtJ8_R/view).
- [Production request examples](https://drive.google.com/file/d/1mN1B95eNRX_eMVp4TAnSZ8rEQO1ih1vc/view).

The FAQ allows at most one delta/data pull per three minutes and at most one
initial/full-classification bulk pull per 24 hours. All primary pulls use the
three-minute account gate; bulk also uses the 24-hour gate. A failed auth consumes
its reserved pull allowance conservatively. These are elapsed UTC intervals, not
calendar days or an arbitrary project time floor.

Auth is POST `https://api-nms.aim.faa.gov/v1/auth/token`, Basic authentication,
form `grant_type=client_credentials`. The engine accepts an explicit in-memory
credential mapping; it never reads process environment or credential stores.
Credentials/auth responses/response headers are never written to the ledger.

Documented initial-load preparation is GET `/nmsapi/v1/notams/il?allowRedirect=false`.
The IL file is **compressed AIXM inside SOAP**, not GeoJSON. Classification-only
GeoJSON request preparation is also supported using `/nmsapi/v1/notams` with
`classification=<documented enum>`, `allowRedirect=false`, and header
`nmsResponseFormat: GEOJSON`. There is no invented ALL classification value.
The executable engine currently uses only the all-classification IL path; the
classification-only plan is not silently substituted for a full baseline.

Initial responses use `status` and `data.url`. Only documented same-host content
paths are accepted: `/v1/content/{token}` relative to `/nmsapi`, or the explicit
`/nmsapi/v1/content/{token}` spelling in the FAQ. The same bearer token is used.
No redirects, arbitrary absolute/signed cloud URLs, URL decoding to a second host,
pagination or retry loop is implemented. Content paths expire after five minutes;
the client checks that interval conservatively from the initial request start.
The content GET is a logged continuation of the reserved bulk pull, not another
initial-load allowance; it must finish within the documented content-path lifetime.

Deltas use `/nmsapi/v1/notams?lastUpdatedDate=<UTC seconds>` and GEOJSON. OpenAPI
describes modifications (including inactive notices) within the preceding **24
hours**. The five-day limit on Location-Series is unrelated and is not reused.
No location/classification filters are added to the delta query. No pagination,
record cap, max-page controls, unsupported lifecycle code or deletions are invented.

## Account storage, locking and failure behavior

`Store` opens an explicitly supplied absolute private directory and existing
`account.sqlite3` plus `account.sqlite3-journal`. Missing paths/history, unsupported
schema, failed ACL/permission checks, corrupt SQLite, missing counted history rows
or clock rollback fail before transport. There is **no create-on-open/reset path**.

Both database and persistent rollback journal must first be created by the
existing `capture_storage.platform_storage()` implementation under a separately
approved history import. Native Windows uses protected owner+SYSTEM DACLs on local
NTFS; chmod is not privacy evidence. POSIX uses the existing owner/mode and flush
checks. SQLite uses native platform locking, `journal_mode=PERSIST` and
`synchronous=EXTRA`; it retains the precreated protected journal. If hot-journal
recovery removes a required file, later validation refuses collection rather than
recreating it with weaker permissions. SQLite/VFS/device durability guarantees
still apply; this is not a promise to survive a dishonest disk cache.

One store is bound to one logical account, `scope=all-classifications` and KMEM
reader extraction. All clients sharing those credentials must use that **same
physical store**, or remain paused. A different path is not another allowance.
This code cannot constrain a separate client that ignores the gate. No network or
multi-PC coordination is claimed.

`BEGIN IMMEDIATE` serializes admission. The primary attempt commits before auth;
each auth/initial/content/delta stage commits its reservation before that I/O.
`active` persists across process exit. Concurrent callers are refused; a crashed
reservation is never assumed unused or expired automatically. Admission examines
all successful, failed, imported and uncertain attempts. Cooldowns anchor to the
latest reservation/I/O time, including late auth/content activity, rather than
the start of a slow run. Successful data completion and failed/uncertain run
completion extend the anchor conservatively. SQLite lock waits are bounded at
two seconds to let short reader/writer transactions finish; they are not provider
retries. Busy failures do not trigger transport retries.

Successful data response bytes are retained privately, including unrecognized
fields and duplicates, before decoding/acceptance. Auth responses and non-200
error bodies/headers are not retained. Request reprs hide URLs, bodies and headers;
exception messages crossing the engine boundary are fixed codes only.

Opaque source IDs and source `lastUpdated` times identify updates; they are not
interpreted as lifecycle status. Exact replay is idempotent. A changed record at
the same/older timestamp, contradictory location fields or a changed MEM
association is a conflict: retain the accepted snapshot and require recovery.
Raw responses preserve even duplicate/older records. Absence never deletes an
ID; cancellations, expired/future effective times and schedules are not filtered.

All raw features remain in the private account catalog. Only explicit source
`icaoLocation=KMEM` or `location=MEM/KMEM` contributes to the MEM reader outbox.
Conflicts are not resolved using runway text/FIR/geometry. Unresolved location
records remain private and are counted in outbox provenance. Normalization reuses
`normalize_notam_snapshot.normalize`; its local partition is not misrepresented
as an upstream location query. Existing records keep their original retrieval
timestamps. Source text, representations and unknown fields remain unmodified.
Outbox attribution is neutral, coverage UNKNOWN, availability unassessed.

The accepted catalog, exact outbox bytes and cursor commit together. Failed
transport/decoding/validation/publication preflight rolls back acceptance while
retaining the consumed attempt and received response. Failed persistence returns
`PERSISTENCE_UNCERTAIN` if the failure cannot itself be recorded safely; do not
export or keep polling after that diagnostic. SQLite atomicity does not make a
lost COMMIT acknowledgement distinguishable from a committed write. Inspect that
case manually; the public website remains untouched in either case.

The delta cursor is the prior request's start, floored to seconds with one second
of **client replay overlap** (not a provider boundary rule). It never jumps to
the greatest source timestamp, response completion time or publication time.
Failed attempts do not advance it. If the replay lower bound falls outside 24
hours, stop with `DELTA_GAP`; do not query a shorter interval or claim recovery.

## SPA-52 bounded initial-content inspection (not a production decoder)

`scripts/nms_initial_decoder.py` adds independently useful, offline inspection
without activating collection or claiming production wire compatibility. Its
evidence-to-implementation mapping is deliberately narrow:

| Evidence class | Evidence | Implemented consequence |
| --- | --- | --- |
| Supplied OpenAPI 1.0.18 | The all-classification initial load is a compressed file containing AIXM in a SOAP envelope. | Compression/container magic is explicitly rejected because the documents do not identify an algorithm or archive/member layout. Raw XML inspection is a separately testable subset, not a claim about the actual compressed wire container. |
| Supplied OpenAPI 1.0.18 | Ordinary responses are JSON envelopes and `data.aixm` contains XML strings. | This corroborates AIXM 5.1, but is not treated as evidence that the initial-load binary is JSON or that its SOAP/member layout matches filtered responses. |
| Standards-derived synthetic profile | SOAP 1.1/1.2 envelope namespaces and AIXM 5.1/message `AIXMBasicMessage`/`hasMember` are exercised by labelled synthetic fixtures. No supplied WSDD/WSRD, XSD or approved initial-load sample is available. | Namespaces are checked exactly. Only one SOAP body, one `AIXMBasicMessage` and ordered, single-child AIXM `hasMember` elements are inspectable. This validates safety/inspection behavior, not provider-format compatibility. Unrecognized namespaces/structures are refused instead of searched by local tag name. |
| Supplied OpenAPI example, not an initial-load XML sample | The GeoJSON example defines source identifiers, timestamps and `notamTranslation` representations. | Those fields remain the existing GeoJSON normalizer contract. They are **not** projected onto opaque AIXM XML without an approved XML mapping. In particular, condition text is never relabelled `LOCAL_FORMAT`. |
| Explicit evidence gap | No document defines initial-load cutover continuity. | Production `decode_initial(body, stage)` safely inspects supported raw XML and then returns the fixed `BASELINE_CUTOVER_REQUIRED` failure. Retrieval time, clocks and notice timestamps are not substituted. |

The inspector accepts only UTF-8 XML (with an optional UTF-8 BOM and no
contradictory encoding declaration), so the DTD/entity safety scan and XML parser
operate on the same decoded character stream. Other encodings are rejected before
parsing. It accepts at most 64 MiB input and parses in 64 KiB chunks. It
bounds elements (250,000), depth (64), text (64 MiB), attributes (1,000,000) and
attribute characters (64 MiB). Aggregate retained member serialization is bounded
to 64 MiB during serialization, counting UTF-8 bytes including namespace
declarations repeated on separately serialized members. DTD/entity declarations are refused before parse;
external schemas/references are never loaded. ZIP, gzip, bzip2 and xz signatures,
non-XML, malformed/truncated XML, ambiguous SOAP bodies and unsupported namespaces
have fixed diagnostics that contain no source bytes, URL, token or parser text.
There is no archive extraction or filesystem path handling because no archive
format is justified or supported. Import and construction perform no I/O.

`InspectedInitial` exposes source order, duplicate member evidence, namespaces
and bounded XML serialization for offline review. The collector still retains the
complete original content bytes in its private response ledger. XML 1.0 parsing
normalizes entity references and line endings, so member serialization is not
described as byte-identical extraction. Unknown elements/attributes stay in the
opaque member serialization; no lifecycle or operational meaning is assigned.

`assemble_synthetic(...)` is an explicit test seam. Synthetic tests supply both
a labelled GeoJSON mapping and synthetic continuity timestamp to exercise mock
transport → existing collector → existing normalizer → private outbox. That seam
does not derive either value from XML and is not a production policy. A minimal
collector exception change preserves only the trusted fixed
`BASELINE_CUTOVER_REQUIRED` code; every other decoder exception remains
`INVALID_RESPONSE`. Failed inspection/cutover keeps the accepted outbox, baseline
and cursor unchanged while preserving attempt, call and received-response evidence.

Native Windows focused command:

```powershell
python -m unittest -v tests.test_nms_initial_decoder tests.test_nms_refresh
```

Native Windows 11 (build 26200), PowerShell 7.7.0 and Python 3.13.6 validation
on November 14, 2026: focused decoder/collector suite **31 passed, 0 failed,
0 skipped** in 4.197 seconds; complete Python suite **123 run, 121 passed,
0 failed, 2 POSIX-only skips** in 8.730 seconds with parent socket/DNS audit
blocking (network-relevant child tests install the same block); relevant Node
snapshot/schema suite **25 passed, 0 failed, 0 skipped** in 0.332 seconds.
All transport, content, credentials, cutover and XML fixtures were synthetic.
Focused correction validation on November 15, 2026: **33 passed, 0 failed,
0 skipped** in 4.261 seconds with parent socket/DNS audit blocking.

Remaining production gates are exact: the compression/container algorithm and
member layout; an approved initial-load example; authoritative SOAP/AIXM WSDD,
WSRD or XSD; mappings for record identity, source timestamps, source information,
unknown fields and separately identifiable provider text representations; an
XML-defined `LOCAL_FORMAT` source; and continuity/cutover evidence. Until those
are supplied and reviewed, the production seam intentionally does not assemble a
`DecodedInitial`, establish a baseline or advance a delta cursor.

## SPA-56 offline streaming inspection of preserved Initial Load evidence

`scripts/inspect_initial_load_stream.py` is a separate forensic inspector for the
verified production specimen shape: one gzip member containing UTF-8 SOAP 1.1,
a WFS 2.0 FeatureCollection, and one AIXM Basic Message per WFS member. It has no
collector, decoder, credential, HTTP, SQLite, baseline, cursor, outbox, public
file, scheduler, or deployment integration. `nms_initial_decoder.decode_initial`
remains unchanged and fail-closed with `BASELINE_CUTOVER_REQUIRED`.

The inspector requires an explicit absolute protected evidence directory, exact
approved SHA-256, and byte count. It verifies the receipt and native private
permissions, hashes the artifact before parsing, streams the same open handle,
and hashes it again afterward. File identity, size, last-write metadata, receipt
bytes and file identity, directory identity, and ACLs are rechecked to detect
mutation or replacement. Duplicate receipt keys and incomplete capture-state
receipts are refused. It never creates or edits evidence.

Gzip CRC/size validation, a single-member rule, no trailing bytes, and explicit
compressed/decompressed limits precede acceptance. Each decompression operation
can return at most 64 KiB; `unconsumed_tail` is drained through the same fixed
window before more input is read. Decompressed bytes are scanned across chunk
boundaries for DTD and entity declarations before XML events are processed. Only
UTF-8 is accepted. Schema locations and XLinks are counted as inert attributes
and are never opened or resolved. SOAP/WFS/AIXM namespaces and structure are
checked exactly; malformed, unsupported, unsafe, and limit failures use fixed
diagnostics that cannot contain source material.

The namespace-aware Expat event parser has parameter entities disabled and an
external-entity refusal handler. A pre-parser lexical bound limits a start tag
before Expat can retain an oversized attribute, while character callbacks enforce
per-scalar, per-member and aggregate text limits incrementally. Byte, element,
depth, namespace, QName, attribute, WFS-member, feature, reference and identity
limits are also explicit. No XML tree or notice body is assembled. Only current
member/feature state plus bounded aggregate identity and reference indexes remain.
Source text, identifiers, coordinates, reference values, internal hashes,
credentials, private paths and unexpected structural names are absent from reports.

Reports contain aggregate feature/cardinality distributions, whitelisted
classification and translation labels, time lexical shapes, repeated-identity
structure, and resolved/unresolved relationship counts. They do not assign
lifecycle meaning, classification-enum equivalence, airport ownership, baseline
coverage, or delta cutover. `baseline_established=false`, `watermark=null`, and
`diagnostic=BASELINE_CUTOVER_REQUIRED` are invariant.

Synthetic tests cover gzip corruption/concatenation/trailing data, split DTD and
entity attacks, non-UTF-8 declarations, malformed XML, inert schemas/XLinks,
resource limits, evidence mutation, fixed diagnostics, output privacy, and bounded
memory across many members. The genuine private specimen test is opt-in through
`SPATCHIN_IL_SPECIMEN_DIR`; normal CI never requires or copies private evidence:

```powershell
python -m unittest -v tests.test_initial_load_stream
$env:SPATCHIN_IL_SPECIMEN_DIR = '<protected attempt directory>'
python -m unittest -v tests.test_initial_load_stream.PrivateSpecimenTests
```

The specimen-backed assertions describe only the approved SPA-56 artifact. They
are not provider-wide invariants and do not authorize another request or baseline.

## SPA-58 offline C070 airport association candidate

`scripts/associate_initial_load_airports.py` adds a bounded, read-only association
pass over the verified Initial Load container. It reuses the SPA-56 evidence,
receipt, permission, mutation, gzip and XML safety checks and streams one WFS
member at a time. It neither loads the decompressed document as a tree nor changes
the saved specimen. There is no collector, credential, network, baseline, cursor,
polling, public-file, dashboard, scheduler, version or deployment integration.

Two source-supported signals are accepted. `event:NOTAM/event:location` may match
an IATA or ICAO identifier only when that exact identifier is present in the
reviewed C070 registry. An `aixm:AirportHeliport` designator may also match only
that registry, and only when the feature has an `event:theEvent` relationship to
the Event containing the notice. No `K` prefix is invented. Runway,
RunwayDirection, text, geometry and name inference are deliberately excluded;
structured runway relationships remain SPA-59 scope.

If the location and Event-linked airport feature sets are both nonempty and
disjoint, the notice is reported as conflicting and is not assigned. Multiple
explicit Event-linked airports are supported and preserved, although none occurs
for the C070 subset in this specimen. Duplicate evidence and duplicate Event
identifiers are counted. A caller-supplied record sink can retain exact extracted
NOTAM scalar fields, Event identifiers, timestamps, translation representations,
association evidence and accepted airports in approved private storage. The CLI
uses no sink and prints only aggregate counts and reviewed public C070 codes.

Read-only validation of the approved November 16 artifact (43,073,137 compressed
bytes; 362,833,367 decompressed bytes) measured:

- 72,675 NOTAMs inspected;
- 8,298 notices associated with at least one reviewed C070 airport;
- all 130 C070 airports represented;
- 64,377 notices unmatched or unresolved for the C070 registry;
- zero conflicting notices, zero multi-airport notices and zero duplicate Event
  identifiers;
- 3,848 accepted notices independently supported by both the exact NOTAM location
  and an Event-linked AirportHeliport designator.

These are artifact-specific association counts, not completeness or operational
applicability claims. The remaining 64,377 notices principally name locations
outside the 130-airport registry. The candidate does not define lifecycle,
refresh/cutover continuity, durable private record storage, normalization into a
dashboard snapshot, or public publication. Those require separate review before
any refreshable feed; `baseline_established=false`, `watermark=null`, and
`diagnostic=BASELINE_CUTOVER_REQUIRED` remain invariant.

Synthetic validation is the default. The genuine specimen assertion is opt-in:

```powershell
python -m unittest -v tests.test_initial_load_airport_associations
$env:SPATCHIN_IL_SPECIMEN_DIR = '<protected attempt directory>'
python -m unittest -v tests.test_initial_load_airport_associations.PrivateSpecimenTests
```

## SPA-55 private baseline candidate and offline delta reconciliation

SPA-61 corrects the Initial Load identity used by this candidate. The bounded
streaming association pass now preserves the enclosing
`AIXMBasicMessage/@gml:id` as `source_message_id`; Event `gml:id` and
`gml:identifier` values remain separate source evidence. Each WFS member must
contain one uniquely identified Basic Message and exactly one NOTAM owned by one
of either one or two Event features. Missing or repeated message IDs, missing or
multiple NOTAMs, ambiguous ownership, and unsupported Event cardinality fail
closed. The candidate catalog and compatibility probe use `source_message_id`
for exact comparison with GeoJSON `notam.id`; delta reconciliation, replay,
cancellation preservation, conflict handling, baseline state, and watermark
behavior are unchanged.

`scripts/nms_baseline_candidate.py` connects the SPA-58 streaming record sink to
the existing `nms_refresh.Store` model without adding a collector, scheduler,
cache, public writer or production decoder. `InitialCandidateSink` receives one
Initial Load record at a time and retains bounded private candidate state. It
preserves exact AIXM Event identifiers, NOTAM scalar values and lexical timestamps,
FNSE classification/update values, translation representations, C070 associations
and unresolved records. Candidate size and record count have explicit limits.

The candidate remains `baseline_established=false`, `watermark=null`, coverage
`UNKNOWN`, and `BASELINE_CUTOVER_REQUIRED`. Transactional Store acceptance writes
only `offline_candidate_b64` and `offline_candidate_status` into the existing
private state document. It does not replace `published_b64`, mutate the accepted
catalog, reserve a request, or change baseline/watermark state.

Synthetic global GeoJSON deltas reconcile by exact source identity only. Replayed
same-version records are idempotent. A changed same-or-older `lastUpdated`, or a
newer record that moves between explicit C070 airports, is a conflict and leaves
the input candidate unchanged. New unmatched IDs are retained as unresolved;
records absent from a delta are never deleted. Cancellation/replacement fields are
preserved as uninterpreted source signals and never remove a notice. The proposed
next cursor retains the existing whole-second one-second replay overlap but is not
stored as a watermark.

### Actual Initial Load / saved GeoJSON compatibility

The privacy-safe comparison used the verified 72,675-record November 16 Initial
Load and the previously saved 21,024-record DOMESTIC GeoJSON capture. It emitted
only aggregate equality counts. The captures are from different acquisition times:

The final streaming adapter pass produced a 79,764,193-byte in-memory private
candidate: 8,298 associated records, 64,377 preserved unresolved records, zero
identity conflicts, and classification plus last-update metadata on every
associated record. The pass did not persist records and reverified that the
protected source evidence was unchanged.

| Mapping | Result | Behavior |
| --- | ---: | --- |
| AIXM `AIXMBasicMessage/@gml:id` → GeoJSON `notam.id` | 19,824 exact matches | SPA-61 preserves this message identity and uses it as the candidate key. |
| AIXM `gml:identifier` → GeoJSON `notam.id` | 0 exact matches | No translation or identity join is invented. |
| AIXM `gml:id`/all Event aliases → GeoJSON `notam.id` | 0 exact matches | Aliases are preserved privately, not treated as delta IDs. |
| Unique exact number/text/issued/effective interval tuple | 0 matches | The non-contemporaneous saved sets do not prove cross-format continuity. |
| Notice text and named issued/effective fields | Present in both schemas | Preserve exact lexical values; equality across the saved sets is unproven. |
| Initial FNSE classification / GeoJSON classification | Present in both schemas | Raw codes are retained; enum equivalence is not inferred. |
| AIXM / GeoJSON translation representations | Both expose type plus simple/formatted text | Preserve source representation; equivalence is not assumed. |
| Cancellation/update semantics | Different source structures, no overlapping identity evidence | Preserve only; never infer deletion or operational state. |

SPA-60 therefore established the cross-format identity mapping for overlapping
saved records, and SPA-61 implements that correction. The non-contemporaneous
private evidence still does **not** establish Initial Load cutover inclusion,
delta ordering/completeness, or lifecycle semantics. A contemporaneous,
supervised Initial Load plus overlapping global delta (or authoritative provider
cutover documentation) remains required before live activation.

### Cutover and activation gates

| Gate | Current result |
| --- | --- |
| Initial inclusion through capture start | Unproven; capture start is only the conservative proposed first-delta lower bound. |
| Delta identity and ordering continuity | Unproven by the non-overlapping saved evidence. |
| All-classification/account scope | Initial Load scope observed; delta inclusion/ordering still unproven. |
| First delta within 24-hour lookback | Enforced; after 24 hours returns `DELTA_GAP`. |
| Account-wide budgets | Existing Store remains authoritative: one bulk/24h and one data/delta/3min, plus external-activity attestation. |
| Baseline/watermark activation | Not authorized; always remains false/null. |

`dashboard_projection(...)` defines a private preview for at most 30 reviewed C070
airports. It keeps original wording, representations, source attribution, UTC
timestamps, UNKNOWN coverage and age warnings. It writes no public file and marks
automatic updates false. Existing dashboard and runway text matching are unchanged.
Public conversion, live collection and activation each require separate review.

## SPA-52 classification-wide GeoJSON candidate (offline only)

`scripts/nms_geojson_baseline.py` implements a second, independent evidence path
for five saved classification-only responses. The supplied OpenAPI 1.0.18 defines
`GET /nmsapi/v1/notams`, header `nmsResponseFormat: GEOJSON`, and request labels
`INTERNATIONAL`, `MILITARY`, `LOCAL_MILITARY`, `DOMESTIC`, and `FDC`. It also says
classification-only retrieval can lead to temporary compressed content, but the
supplied material does not define that packaging. Consequently this code accepts
only already-saved, direct UTF-8 JSON bytes. ZIP, gzip, bzip2, xz and unknown
signatures are reported without extraction or format guessing.

This is not an acquisition client. It contains no URL opener, credentials,
environment reads, HTTP, retry, redirect, scheduler, live-capture path, provider
rate gate, public-file writer, or collector-state write. Five full classification
pulls would consume provider/account allowance whose exact treatment remains
unknown; offline combination never authorizes or performs those pulls.

Each input is bounded before JSON decoding (64 MiB by default), and the decoded
tree is bounded by feature count, depth, and aggregate value count. Validation
requires `status=Success`, no errors, and an inline `data.geojson` array. The
inspector retains the exact original bytes privately in its returned dataset and
reports only classification, SHA-256, byte size, content signature, parseability,
structure/counts, duplicate/missing-ID counts, timestamp range, explicit
`LOCAL_FORMAT`/`ICAO`/no-local counts, cancellation-field count, unexpected field
names and same-time conflict count. Reports contain no raw records or source IDs.
The CLI reads only explicit local paths and is inspection-only.

A candidate requires exactly one validated dataset for every request label.
Classification provenance is the request label; a payload value matching a
different documented request label is a conflict. An undocumented abbreviation
such as `DOM` is preserved verbatim and is never silently translated to
`DOMESTIC`. Original features, unknown fields, Unicode, escaped text, duplicate
translations and unknown translation types remain in private source evidence.

Candidate identity is exact `notam.id`. Exact duplicate features are idempotent;
changed records use parsed UTC `lastUpdated`, with the newest retained and
older evidence accounted. Different content with the same ID and timestamp is an
explicit conflict. Output order is deterministic by ID. Aggregate candidate JSON
serialization is charged incrementally, including envelope punctuation and each
feature's UTF-8 representation, before the combined payload is retained; the
default limit is 256 MiB and tests use reduced limits.

`CandidateBaseline.normalize_partition(...)` is the narrow integration seam to
the existing normalizer/private snapshot schema. A caller must provide a reviewed
airport/location partition and retrieval provenance; a classification-wide set is
never described as location-scoped automatically. Only an explicit
`LOCAL_FORMAT.simpleText` is a local display representation. ICAO translations
remain separately typed; `LOCAL_FORMAT.formattedText`, unknown types, and absent
local text do not become a fallback, while their original source data remains in
`original_feature` and the retained datasets.

The result is deliberately named and marked a **candidate**. It has no
`coverage_since`, never constructs `DecodedInitial`, never changes SQLite,
baseline, watermark, catalog, accepted outbox, public snapshot or UI, and carries
`baseline_established=false`, `watermark=null`, and the fixed diagnostic
`BASELINE_CUTOVER_REQUIRED`. The existing `DELTA_GAP`, accounting, v0.9, SOAP
inspector and collection behavior are unchanged. Completeness, lifecycle,
cancellation meaning, and a cutover-to-delta continuity point remain unresolved.

Offline focused validation command:

```powershell
python -m unittest -v tests.test_nms_geojson_baseline tests.test_nms_initial_decoder tests.test_nms_refresh
```

The next authorized action is review of this parser against separately approved,
sanitized saved response evidence and authoritative cutover semantics. It is not a
live pull. Only after that review could a separate change propose an accounted
acquisition/acceptance policy.

Native Windows validation on November 15, 2026 used Python 3.13 with a parent
audit hook refusing all `socket.*` events: focused GeoJSON/SOAP/collector suite
**52 passed**; complete Python suite **144 run, 142 passed, 2 platform skips**.
The relevant Node reader/snapshot/schema suite ran with network permission
ungranted and **20 passed**. All candidate inputs were documented synthetic test
examples; no provider networking, saved production record, credential, baseline,
publication, deployment, or v0.9 change was used.

## Contract details not implemented by guessing

1. The documents describe compressed content but do not specify a compression
   algorithm, archive/member schema or AIXM/SOAP-to-reader mapping. The bounded
   inspector above rejects unknown containers and preserves opaque raw-XML evidence;
   it is not presented as a complete production decoder. Synthetic tests provide
   their mapping explicitly and are not verified initial-load wire evidence.
2. No documented response field establishes the IL file's exact snapshot cutover
   relative to delta history. A reviewed decoder must return `DecodedInitial`
   with a justified `coverage_since` lower bound, within the delta lookback. Local
   download time or maximum record timestamp is not such evidence. Without it,
   baseline acceptance stops; no hidden timestamp assumption enables collection.
3. The HTTP adapter and explicit history importer described below have offline
   native-Windows tests. They still require runtime/import review and separate
   execution authorization. The adapter is not constructed or called by the engine
   implicitly; a caller must inject it and explicit in-memory credentials.
4. The exact completeness/retention and lifecycle semantics are not established
   by response structure. Neither 100 records nor an empty delta changes UNKNOWN.

These are concrete activation gates, not a requirement to contact the provider.
Resolve them from supplied material, separately approved sanitized examples or
an explicitly reviewed policy/adapter; do not invent a live experiment.

## Concrete activation runbook — future approval required; not executed here

1. Review this source-only draft and native-Windows evidence. Keep the existing
   static snapshot published. The importer is separate and requires its own approval;
   no collection launcher or schedule ships here.
2. Designate this PC as the sole collector and obtain confirmation that every
   legacy/manual caller sharing the account remains paused or uses this gate.
   Bind a stable logical account such as `mem-budget` to one fixed local NTFS
   directory outside all repositories. Never create a second store to bypass a
   cooldown, a lost ledger, a pending reservation or the consumed SPA-26 exception.
3. Under **separate accounting-import approval**, use the explicit review/digest
   workflow below. The importer creates the fresh directory and both files with
   `platform_storage`, then initializes `SCHEMA` exactly once. Import all known account attempts (including failed/uncertain
   and the prior one-time capture), their conservative reservation/last-I/O UTC,
   outcome and scope. `other-data` participates in the three-minute gate; do not
   mislabel every location query as a documented bulk pull. Unknown scope/history
   needs operator reconciliation, not an empty ledger. Preserve the source receipts.
4. The state row must contain schema/account/history_verified/history_complete_through,
   scope `all-classifications`, airport `KMEM`, active/recovery, baseline/watermark,
   catalog, published_b64 and exact attempt_count/call_count/response_count. Use the
   existing approved publication as the initial outbox bytes, but **not** as an IL
   baseline: the old location-filtered capture does not establish one. Initial
   baseline=false, watermark=null; preserve imported history. The synthetic test
   helper demonstrates the schema only and must never be used on production.
5. Validate every ACL, SQLite integrity/journal setting, imported row count and
   UTC clock. Obtain a reviewed real transport and initial decoder/cutover policy.
   Supply credentials only to that future local runtime through a hidden prompt
   or approved process secret mechanism. Do not put values in commands, files,
   logs, issue/PR text or database state. Do not reuse the archived inspector.
6. After explicit request authorization and eligibility review, the single-call
   integration shape is:

   ```python
   collect(Store(approved_private_path, account=approved_logical_account),
           mode="bulk", credentials=hidden_prompt_result,
           transport=reviewed_one_call_transport, clock=verified_utc_clock,
           decode_initial=reviewed_initial_decoder)
   ```

   These names are integration dependencies, not supplied live commands. Inspect
   the returned fixed diagnostic and private responses/outbox. No retries or
   schedule activation follows implicitly. Follow later authorized delta calls
   with `mode="delta"`, using the same store and gate.
7. `Store.snapshot()` returns only the accepted private handoff. Review selected
   fields/legal notices and SHA256 before any separate data-only publication.
   Never publish the database/journal/raw responses or automatically promote an
   outbox after a failed/uncertain operation. A public deployment bridge remains
   a separate explicit action; no hosting or new infrastructure is needed.
8. Restart recovery: accepted stores resume with existing cursor and cooldowns.
   Pending/crashed attempts freeze collection. Verify the prior process is gone,
   reconcile all attempted stages and actual uncertainty interval, retain them as
   accounted, and only under explicit operator approval close the pending marker.
   Do not delete rows, rewind last-I/O time, reset counters or infer unused calls.
   A gap/conflict/corrupt store requires review and, if justified and budget-eligible,
   a separately approved new baseline—not a shorter guessed delta or ledger reset.
9. Only after runtime/request-budget/outbox behavior is accepted may the owner
   separately authorize a single-PC schedule. No Task Scheduler entry, workflow,
   daemon, auto-Git action or recurring collection is created by this PR.

## Offline native-Windows verification

Use the existing native Python and installed Chrome/Playwright dependencies; no
downloads or paid services. Run the complete Python suite with socket/DNS auditing
blocked, and the complete JavaScript/browser suite with external page routes
blocked. `tests/test_nms_refresh.py` creates **only synthetic temporary account
stores**, injects synthetic credentials/data and mock transport, and exercises
real Windows ACLs, SQLite transactions, process exit/restart, two-process races,
elapsed cooldown boundaries, response replay, conflicts/gaps, failure rollback,
private outbox failure and credential-safe diagnostics. Child process tests also
block sockets. This does not validate an unimplemented live content decoder or
the production ledger/import, and does not authorize any provider request.


## HTTP adapter integration (not activated)

`nms_http.HTTPAdapter(timeout=30, max_bytes=64*1024*1024)` is a callable matching
`transport(Request, limit)`. Construction/import never creates a connection.
Only a subsequent explicit call does. Inject this callable into `collect`; it does
not read environment credentials, install a launcher or bypass engine accounting.
The initial decoder and justified baseline cutover are still required and are not
implemented in this integration.

The adapter validates the entire prepared stage/method/URL/query before opening a
connection. The exact production authority is required. Auth, IL (including its
documented classification suffix), classification-only GeoJSON, delta and content
requests have separate shapes. Pagination, extra query keys, header injection,
auth at the wrong endpoint, absolute cloud URLs, cross-host URLs and encoded
content-path traversal are refused. No environment proxy is used. Only explicit
auth/content-type/response-format/accept headers can pass validation.

It uses `ssl.create_default_context()` with hostname/certificate verification,
`http.client.HTTPSConnection`, a positive timeout at most 30 seconds, a bounded
response read loop and an independent local response-byte budget. These are client
resource bounds, not provider caps. Elapsed time is checked between operations;
socket timeouts bound blocking network operations. Normal OS DNS resolver timing
is not claimed as a hard cancellable wall-clock deadline. No worker thread is
left to issue an unaccounted late request, and no redirect/retry is performed.

All redirects are refused without following Location or reading their bodies.
Other non-200 responses return only status and empty headers/body to the engine.
Successful responses return exact bytes with no retained headers. Fixed adapter
codes distinguish invalid requests, timeout, TLS/network/protocol failure,
redirect refusal and excessive size. Upstream messages/headers/bodies, credentials
and tokens never enter those diagnostics. The merged engine records its existing
safe failure code and retains consumed accounting/snapshot bytes; it does not retry.
Real TLS exchange has not been tested; fake HTTPS connections assert the normal
verification configuration with actual socket/DNS access blocked.

## Explicit history manifest and dry-run/write usage

This is a separately approved future operator action. **Do not run a production
import as part of this implementation review.** No target directory is inferred.
An existing target (even an interrupted import) is always refused. Do not choose
another target to bypass history; inspect/reconcile the first artifact instead.

The following is a **synthetic schema example**, not production history. Replace
all evidence, identities, counts and timestamps from reviewed records; never copy
these invented example times into an actual account import. Paths must be absolute.
Hashes are lowercase SHA256 and must match exact existing file bytes.

```json
{
  "schema_version": 1,
  "account": {
    "logical_id": "SYNTHETIC-ACCOUNT",
    "identity_reference": "SYNTHETIC operator account-binding record (not OAuth credentials)",
    "identity_confirmed": true,
    "all_clients_quiesced": true
  },
  "history": {
    "inventory_complete": true,
    "complete_through_utc": "2026-01-02T11:30:00Z",
    "declaration_reference": "SYNTHETIC review of every account client/known attempt"
  },
  "attempts": [{
    "id": "SYNTHETIC-ATTEMPT",
    "kind": "other-data",
    "reserved_utc": "2026-01-02T11:00:00Z",
    "last_io_utc": "2026-01-02T11:01:00Z",
    "last_io_is_upper_bound": false,
    "outcome": "succeeded",
    "known_call_count": 2,
    "receipt": {"path": "C:/NmsReview/SYNTHETIC-receipt.json", "sha256": "<exact SHA256>"},
    "calls": [
      {"stage": "auth", "at_utc": "2026-01-02T11:00:00Z", "certainty": "observed"},
      {"stage": "other-data", "at_utc": "2026-01-02T11:01:00Z", "certainty": "reserved"}
    ]
  }],
  "uncertainties": [],
  "prior_snapshot": {
    "path": "C:/NmsReview/SYNTHETIC-prior-snapshot.json",
    "bytes": 123,
    "sha256": "<exact SHA256>",
    "approved_for_display": true,
    "origin_attempt_id": "SYNTHETIC-ATTEMPT"
  }
}
```

`kind` is bulk/delta/other-data; outcome is succeeded/failed/uncertain. Explicit
known call counts must match all listed calls, including retries/reservations;
repeated stages are imported with distinct ordinal keys, not deduplicated.
Recognized repository SPA-26 receipts are checked against their defined auth/GET
counters. Other receipt formats are preserved by hash/reference and require
operator semantic review; their field names are not guessed into accounting.
The importer never edits, moves or overwrites original receipts. It retains the
exact manifest privately and preserves the prior accepted display snapshot bytes.

`inventory_complete` attests that the operator enumerated all known attempts and
all uncertainties; it does not erase unknown outcomes. Missing identity/history,
unknown scopes, missing/invalid timestamps, contradictory time ranges, duplicate
attempt IDs, wrong counters, missing origin evidence and hash changes reject the
import with specific fixed diagnostics. Empty history cannot silently accompany
an existing account snapshot whose origin attempt has not been supplied.

For explicitly **bounded uncertain** attempts, set outcome=uncertain and
last_io_is_upper_bound=true, provide the known reservation and latest possible I/O
UTC from evidence, and add one uncertainty entry:
`{"attempt_id":"SYNTHETIC-ATTEMPT","code":"TIMING_UNCERTAIN"}`.
Codes also include OUTCOME_UNKNOWN and ADDITIONAL_CALLS_UNKNOWN. Unknown individual
call times may be represented explicitly by `at_utc:null, certainty:"unknown-time"`
only for such attempts. Their counters are retained, with UNVERIFIED_TIME in the
private call row?not a fabricated timestamp. The report identifies untimed calls.
These imports end HELD_UNCERTAINTY, history_verified=false, and cannot collect.
There is no uncertainty-resolution, reset or automatic release command here.
Unbounded uncertainty or an incomplete attempt inventory is rejected, not guessed.

After separate operator approval, PowerShell usage is:

```powershell
# Read-only: no target is created, no SQLite connection is opened.
py -B scripts/import_nms_history.py --manifest 'C:/NmsReview/reviewed-history.json' --target 'C:/NmsPrivate/approved-account'

# Only after reviewing the full report and separately authorizing this import:
py -B scripts/import_nms_history.py --manifest 'C:/NmsReview/reviewed-history.json' --target 'C:/NmsPrivate/approved-account' --write --approve '<approval_digest from the reviewed dry run>'
```

The digest binds manifest bytes, referenced snapshot/receipt hashes and the exact
target. The write invocation revalidates and prints its review before any write.
Changed input or target requires another review; it is never silently approved.
Reports show planned attempt/call counts, timestamps, uncertainty/hold status,
minimum cooldown boundaries and snapshot hash/size, never snapshot/receipt bodies.
Those boundaries are computed lower limits, not authorization for a provider call.
No credentials belong in this manifest or either command.

The writer requires a fresh directory outside repositories and creates protected
owner+SYSTEM files on native Windows NTFS (existing POSIX protections elsewhere).
SQLite uses the merged SCHEMA, PERSIST rollback journal and synchronous=EXTRA.
After counter/integrity/ACL/readback checks and a second input-hash validation,
readiness is atomically persisted through the reused private-file replacement.
`baseline=false`, `watermark=null`, and catalog empty are mandatory: the old MEM
publication is an accepted display snapshot, not an all-classification baseline.

An import-status.json PENDING marker gates the engine even if SQLite state has
already been populated. Early interruption leaves this marker and partial files
for inspection; there is no auto-cleanup/retry that might discard accounting.
Only a fully validated READY marker permits normal Store use, and its digest must
match the state row. A lost acknowledgement while publishing READY can mean the
import finished; IMPORT_FINALIZATION_UNCERTAIN requires inspection, never another
import over that path. Original receipts remain unchanged in either case.

Remaining activation steps are unchanged in substance: review this draft and the
actual history/evidence, authorize only the history import first, resolve any held
uncertainty without discarding counters, implement/review the initial archive/AIXM
decoder and justified cutover, then separately authorize a controlled collection
call with the HTTPAdapter injected. No initial decoder, scheduler, Git publisher,
provider call or new service is added by this integration.
