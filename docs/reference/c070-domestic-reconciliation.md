# C070 DOMESTIC offline reconciliation

`scripts/reconcile_c070_domestic.py` is a bounded, local-only review tool for
one already-saved NMS DOMESTIC GeoJSON capture. It does not fetch, authenticate,
schedule, publish, mutate the public snapshot, or make operational inferences.

Supply the capture's actual UTC retrieval timestamp and four **new paths outside
the checkout**: a safe summary, concise report, reader-compatible candidate, and
full private evidence file. The tool refuses existing files and repository output
paths. It prints no source records.

```powershell
python -B scripts/reconcile_c070_domestic.py `
  --capture C:\private\saved-domestic.json `
  --retrieved-utc 2026-11-16T12:00:00Z `
  --summary C:\private\spa19-summary.json `
  --report C:\private\spa19-report.txt `
  --candidate C:\private\spa19-candidate.json `
  --evidence C:\private\spa19-evidence.json
```

The summary has all 130 ICAO airport counts, mutually exclusive excluded-record
categories, duplicate-ID counts, missing field counts, normalization failures,
zero-match airports, and input accounting. The candidate has only display fields
and supplied text representations; its evidence file retains the original capture
and source-index associations. Both remain private pending owner review.

Association requires the two supplied identifiers to make one exact registry
IATA/ICAO pair (in either source order). The tool never derives identifiers,
interprets lifecycle/cancellations, filters by time, or invents runway links.
Every airport remains `UNKNOWN`, including empty collections. A count difference
from the earlier 3,084 candidate figure is reported rather than adjusted.
