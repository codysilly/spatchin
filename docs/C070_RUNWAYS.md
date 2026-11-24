# C070 FAA NASR runway expansion

SPA-81 uses the reviewed 130-airport C070 IATA registry for the weekly FAA NASR runway collector. It reads `APT_RWY_END.csv` from the same FAA 28-day ZIP already used by Spatchin. The collector makes no additional request per archive and does not contact FAA NMS.

A valid airport inventory includes all documented paired runway ends. A missing `TRUE_ALIGNMENT` stays `null` instead of receiving an inferred value; the dashboard displays the runway end and no wind component for an unknown true bearing. An invalid or incomplete airport inventory is reported as unavailable under `airport_coverage` and is not published as a partial list. Four existing verified airports (ORD, LAX, JFK, MEM) have fixed end-count regression guards: if one becomes invalid, the entire update is refused and the prior snapshot remains. Other missing or invalid airports are counted separately and must not be described as having verified runway coverage. Registry membership by itself is not runway evidence.

Publication is atomic, and unchanged data does not generate a new snapshot or commit. The `effective_date`, `source_url` and `heading_reference` fields retain the same meanings as the prior snapshot. Frontend validation accepts the old four-airport file and new coverage metadata.

Offline validation on macOS or Linux, from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_update_runways.py'
python3 -m unittest discover -s tests -p 'test_updater_airports.py'
node --check app.js
```

The workflow runs offline runway tests before the existing authorized weekly NASR collection. Do not manually dispatch a new provider request merely to validate this PR. After a scheduled run, inspect the actual returned C070 counts, missing headings, effective cycle, snapshot publication and Pages deployment. No offline synthetic test establishes actual 130-airport coverage. The dashboard remains v0.9, public WIP routing and 30-airport limit are unchanged.
