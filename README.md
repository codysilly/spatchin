# Spatchin

**Public dashboard:** https://www.spatchin.com/

The owner directed the working v0.9 dashboard back to the public homepage on November 24, 2026. The holding page has been retired. A prominent warning above the dashboard states exactly: **WORK IN PROGRESS. Under development and not yet validated.**

The dashboard is an unvalidated supplemental information aid, **not for real-world flight planning, navigation, runway status decisions, or flight operations**. Source, staleness, missing-data, forecast uncertainty, and NOTAM-coverage warnings remain in their original UI context.

GitHub Pages publishes `index.html`, the existing root JavaScript/CSS/branding, and the existing `data/*.json` snapshots. No direct FAA, AWC, or atis.info request is made by the browser; collectors, budgets and schedules are unchanged. The `dashboard/` duplicate remains available for local compatibility but is excluded from public Jekyll publishing with `preview/` and `staging/`. Keep the version at v0.9 until the owner authorizes a version change.

**Private staging retirement:** The old Cloudflare Access and Worker configuration for `dev.spatchin.com` is no longer required. Its removal must be completed in the owner's Cloudflare account; a GitHub PR does **not** delete Workers, Access applications, domains, or billing resources. Do not remove Access protection from an active Worker merely to make the old route public. See Linear for retirement tracking. Previously saved secrets must not be printed or committed.

## Future iPad app

On November 24, 2026, the owner added a **long-term 13-inch iPad app goal**. The first proposed delivery path is an iPad-optimized, installable PWA that reuses the existing dashboard and same-origin published aviation snapshots. This remains planning work: it does not change the current MVP priority, activate an iPad release, add provider requests, incur costs, or increase the v0.9 version.

See [iPad architecture and phased roadmap](docs/IPAD_ROADMAP.md) and [Linear SPA-82](https://linear.app/codesilly/issue/SPA-82/plan-13-inch-ipad-experience). The plan covers portrait/landscape/resizable layouts, touch controls, safe offline behavior, actual iPad testing and optional native distribution.

## Contributor map and project boundaries

Spatchin is a browser-based runway-awareness prototype, **not an operational decision or NOTAM interpretation service**. The current application version remains **v0.9**; do not change the version without owner approval. The WIP dashboard is public at the repository root. Public source visibility and public deployment are separate facts.

| Area | Purpose | Publication and safety boundary |
| --- | --- | --- |
| [`dashboard/`](dashboard/) | Legacy local-compatible copy of the airport dashboard | Excluded from Pages; the public dashboard is the root `index.html` |
| [`preview/`](preview/) | Synthetic/offline UI and NOTAM reader harnesses | Excluded from public Pages; fixtures are not real provider coverage |
| [`staging/`](staging/) | Retained authenticated-development hosting implementation | Excluded from Pages; associated Cloudflare retirement is tracked separately |
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

Data-source retrieval times, browser checks, stale/last-good handling and coverage labels are distinct concepts. Consult [dashboard reader guidance](docs/DASHBOARD.md) and [NOTAM snapshot contract](docs/NOTAM_SNAPSHOTS.md) for the exact implementation behavior. A Git commit, a successful test, a deployed page and verified external-data coverage are **different claims**.

### Safe local verification

Start from a clean, isolated issue branch, inspect the current source and applicable instructions, and preserve unrelated local modifications. Do not assume a working directory or test dependencies are available merely because a machine was configured previously. Confirm the execution environment and tools before reporting results.

The repository's [synthetic reader guide](preview/README.md) documents a network-blocking Python unittest harness, Node syntax checks and Chromium-based browser tests. Its Python harness blocks socket access; browser tests are intended to reject external requests. Review the actual commands and test side effects before running them. The following is a **syntax-only** check of local JavaScript source, not a test of live data or browser behavior:

```sh
node --check app.js
node --check scan.js
node --check notam-reader.js
```

Run this only if those paths and Node are present in the checked-out revision. Other focused offline commands appear in [NOTAM_SNAPSHOTS.md](docs/NOTAM_SNAPSHOTS.md). **Do not** invoke `scripts/update_atis.py`, `scripts/update_metar.py`, workflow dispatches, provider collectors, production deployments or Cloudflare operations as part of a routine offline test. Report **NOT RUN** when a checkout, dependency or executable test environment is unavailable; historical CI success is not a substitute for a current run.

### Review and release gate

1. Track one scoped issue in Linear, inspect the latest owner decisions, and work on an isolated issue-linked branch. Preserve any other agent's unfinished work.
2. Open a **draft** pull request with changed files, exact validation commands/results, commit SHA, outstanding acceptance criteria and any required visual review. Merge autonomously only when all applicable gates in AGENTS.md pass.
3. Confirm that code tests, browser/visual checks and source provenance support the specific claim being made. A PR's mergeability metadata alone does not prove its behavior.
4. Follow the authority levels and merge gates in [AGENTS.md](AGENTS.md). The owner granted standing authority on November 26, 2026 for routine automatic GitHub Pages deployments from validated merges within approved scope. Other production releases, publication architecture changes, provider requests, credentials, budgets, protected staging and version changes retain their separate authorization requirements.
5. Inspect Pages, workflow and collector triggers before merge. Verify the actual Pages deployment after merge. A successful code review does not authorize other deployments or provider requests.

Never commit credentials, private FAA captures, tokens, private request ledgers or personal data. Keep raw-NOTAM reading separate from lifecycle, closure or other operational interpretation. A documentation change does **not** authorize any provider request or new publication scope.
