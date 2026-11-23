# Spatchin

The public website at https://www.spatchin.com/ displays the charcoal “Not cleared for takeoff… yet.” holding page.

**The development dashboard is not publicly published.** After the owner confirmed that prototype access must be restricted, GitHub Pages was configured to exclude `dashboard/` and the synthetic `preview/` folder from its Jekyll build. The working v0.9 dashboard remains in the repository for local development and offline testing. A signed-in preview requires a separate protected hosting arrangement; GitHub Pages does not authenticate visitors at a path.

The public repository itself, including the dashboard source, and any root-level published static files are still public. Do not store credentials or private captures in this repository or in published assets. The existing METAR and ATIS schedulers remain unchanged. SPA-74 adds a separate scheduled AWC TAF snapshot collector for the four verified stations. SPA-13 adds a UTC forecast-time selector and calculated runway wind components from the saved decoded TAF periods, with uncertainty labels. It does not publish the development dashboard.

Private staging: see [staging/README.md](staging/README.md). The `dev.spatchin.com` setup is prepared but must not go live until Cloudflare Access, exact-email allowlists, DNS and anonymous/authorized browser tests are verified.


## Contributor map and project boundaries

Spatchin is a browser-based runway-awareness prototype, **not an operational decision or NOTAM interpretation service**. The current application version remains **v0.9**; do not change the version without owner approval. The dashboard is developed in the repository but excluded from the public GitHub Pages build. Public source visibility is not private dashboard access.

| Area | Purpose | Publication and safety boundary |
| --- | --- | --- |
| [`dashboard/`](dashboard/) | In-development airport dashboard, runway-end display, SCAN and local snapshot readers | Excluded from public Pages; do not publish without explicit approval |
| [`preview/`](preview/) | Synthetic/offline UI and NOTAM reader harnesses | Excluded from public Pages; fixtures are not real provider coverage |
| [`staging/`](staging/) | Prepared authenticated development-hosting implementation | Not a live private preview; see [staging instructions](staging/README.md) |
| [`data/`](data/) | Checked-in published static snapshots | Publication is separate from provider acquisition and from dashboard deployment |
| [`scripts/`](scripts/) | Data acquisition and maintenance utilities | **Some scripts contact live aviation providers**; inspect before execution |
| [`tests/`](tests/) | Offline/synthetic checks and browser regressions | Choose explicit safe commands; some suites require Chromium |
| [`.github/workflows/`](.github/workflows/) | Scheduled/manual collectors, tests and publication workflows | Reading workflows is safe; dispatching, rerunning or changing them requires authorization |

### Airport selection and source provenance

The approved C070 selection catalog contains **130 IATA codes**. A dashboard may display **30 airports total**, with **MEM as a removable initial example**. Selection eligibility is not a promise of available live weather, ATIS, runway metadata or NOTAM coverage. Preserve all available runway ends and distinguish unknown data from verified zero. Do not invent ICAO mappings or fill missing observations with guesses.

| Data | Current repository behavior | Important limitation |
| --- | --- | --- |
| METAR | Published `data/metars.json` observations, refreshed by an external automation/workflow path | An updated commit does not prove every C070 station has a fresh observation |
| ATIS | Published `data/atis.json` snapshot; [ATIS update workflow](.github/workflows/atis-update.yml) currently retains six fallback schedules and manual dispatch | Provider reports may be partial; independent arrival/departure preservation is tracked in [SPA-70](https://linear.app/codesilly/issue/SPA-70) |
| TAF | Saved decoded forecast periods and a UTC runway-wind timeline where coverage exists | Forecast-derived values have uncertainty and do not establish all-airport coverage |
| Runways | Published runway inventory; MEM's eight ends use **approximate chart-derived bearings** pending authoritative NASR verification | Never represent approximate bearings as surveyed or verified |
| NOTAM | A reviewed, fixed published snapshot is read locally; raw LOCAL_FORMAT text is displayed without operational interpretation | No authorized automatic FAA NMS polling, completeness inference or zero-notice assertion |

Data-source retrieval times, browser checks, stale/last-good handling and coverage labels are distinct concepts. Consult [dashboard reader guidance](DASHBOARD.md) and [NOTAM snapshot contract](NOTAM_SNAPSHOTS.md) for the exact implementation behavior. A Git commit, a successful test, a deployed page and verified external-data coverage are **different claims**.

### Safe local verification

Start from a clean, isolated issue branch, inspect the current source and applicable instructions, and preserve unrelated local modifications. Do not assume a working directory or test dependencies are available merely because a machine was configured previously. Confirm the execution environment and tools before reporting results.

The repository's [synthetic reader guide](preview/README.md) documents a network-blocking Python unittest harness, Node syntax checks and Chromium-based browser tests. Its Python harness blocks socket access; browser tests are intended to reject external requests. Review the actual commands and test side effects before running them. The following is a **syntax-only** check of local JavaScript source, not a test of live data or browser behavior:

```sh
node --check app.js
node --check scan.js
node --check notam-reader.js
```

Run this only if those paths and Node are present in the checked-out revision. Other focused offline commands appear in [NOTAM_SNAPSHOTS.md](NOTAM_SNAPSHOTS.md). **Do not** invoke `scripts/update_atis.py`, `scripts/update_metar.py`, workflow dispatches, provider collectors, production deployments or Cloudflare operations as part of a routine offline test. Report **NOT RUN** when a checkout, dependency or executable test environment is unavailable; historical CI success is not a substitute for a current run.

### Review and release gate

1. Track one scoped issue in Linear, inspect the latest owner decisions, and work on an isolated issue-linked branch. Preserve any other agent's unfinished work.
2. Open a **draft** pull request with changed files, exact validation commands/results, commit SHA, outstanding acceptance criteria and any required visual review. Do not merge automatically.
3. Confirm that code tests, browser/visual checks and source provenance support the specific claim being made. A PR's mergeability metadata alone does not prove its behavior.
4. Obtain explicit owner authorization before merging, publishing the development dashboard, enabling or changing live aviation-provider requests, altering credentials or budgets, deploying protected staging, or changing the version.
5. Keep the public holding page and protected-preview design separate. Before any approved private deployment, verify Cloudflare Access, exact-email authorization, anonymous denial, DNS and browser behavior as described in [staging/README.md](staging/README.md).

Never commit credentials, private FAA captures, tokens, private request ledgers or personal data. Keep raw-NOTAM reading separate from lifecycle, closure or other operational interpretation. A documentation change does **not** authorize any external request or publication.
