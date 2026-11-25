# Spatchin System Register

Owner approved 2026-11-25. Tracking: SPA-99. This is a development reference, not an operational aviation product or a current health report. Spatchin v0.9 remains unvalidated and not for flight operations.

## Systems

Use the Linear team multi-select label group System. Use the exact names below. Apply all materially affected systems, including on historical issues. Do not change acceptance or status solely to classify an issue. Preserve other labels. Classify new issues and reconcile missing labels during the existing audit. No label alone proves implementation.

| System | Requirements / scope | Dependencies | Validation evidence |
| --- | --- | --- | --- |
| METAR | Current observations, source, issue time, missing/stale indicators; 65-minute freshness threshold | Airport catalog, Refresh, Data integrity | Published snapshot timestamps and expected eligible station coverage; raw report and parser fixtures; browser display and wind input tests |
| TAF | Forecast text, change groups, validity and expiry, UTC timeline | Airport catalog, Refresh, Wind | Published forecast coverage, validity/change-group fixtures, expiry and timeline tests; check approved freshness policy |
| ATIS | Independent arrival/departure reports, runway configuration, issue time, distinguish unconfigured from unavailable | Airport catalog, Refresh | Evidence of configured station coverage, report timestamps, separate arrival/departure fixtures and UI tests; verify current scheduler and freshness policy |
| NOTAM | Approved raw-notice MVP, identity, effective time, coverage and SCAN; preserve original text; no unsupported operational interpretation | Airport catalog, Data integrity, Security, Refresh, SCAN | Authorized existing capture evidence kept private, schema/identity tests, coverage and snapshot publication evidence, budget and reservation safeguards; no new provider calls for status checks |
| RVR | Runway visual range, source and missing/stale states; five-minute stale target | Runways, Airport catalog, Refresh | Existing authorized source evidence, runway association, freshness and missing-data tests; inventory gaps do not prove nonimplementation |
| Runways | All runway ends visible, identifiers, headings and dimensions; no unsupported closure inference | Airport catalog, Data integrity | FAA NASR cycle and coverage evidence, reciprocal joins and runway-end completeness, UI tests |
| Wind | Headwind, tailwind and crosswind; gusts, direction reference, established color thresholds | METAR, TAF, Runways | Independent calculation fixtures including reciprocal runway, variable/missing wind, gusts and threshold boundaries; trace inputs |
| Airport diagrams | Find and open correct airport diagrams with revision/effective dates | Airport catalog, Data integrity | Correct airport mapping, revision and link checks, absent diagram behavior |
| Airport catalog | Approved C070 list, IATA display, ICAO mapping, removable MEM default, 30 airports total | Data integrity, UI | Catalog uniqueness and identifier mapping, selection limits and default behavior, provider-specific eligibility |
| Flight planning | Future route and enroute weather visualization; no operational use | Airport catalog, Wind, Data integrity | Offline route/time/weather-overlay fixtures and uncertainty checks before any future release |
| UI | Compact dashboard, readable source and freshness indicators, approved layout and device behavior | Aviation systems, SCAN | Browser/visual checks on applicable target devices, accessibility and regression tests |
| SCAN | Global multi-keyword search, highlighting, counts, case toggle and navigation | UI, displayed content | Search fixtures and browser tests for navigation, persistence and empty results |
| Refresh | Acquisition, publication and browser updates; controlled manual refresh and shared cache | Infrastructure, Security, data systems | Existing scheduler/job evidence, publication timestamp and browser refresh checks; budget and failure-path tests |
| Data integrity | Source traceability, freshness, completeness, UTC semantics and failure indicators | All data systems | Schema, coverage, missing/stale and provenance tests; distinguish retrieval, effective and browser-check times |
| Infrastructure | Hosting, workflows, deployment and runtime | Security, Refresh, Development | Exact revision, workflow outcome, deployed revision evidence, configuration and recovery checks |
| Security | Access, credential handling, request accounting, cost and publication safeguards | Infrastructure, Refresh | Offline guard tests and authorized configuration evidence; never expose private data or secrets |
| Recovery | Independent backups and restoration | Infrastructure, Security | Backup timestamp, completeness and isolated restore verification; never equate a source ZIP with verified full recovery |
| Development | Test evidence, review, documentation, automation and reconciliation | All systems | Issue-linked exact-commit tests, PR review and merge/deployment evidence; report NOT RUN when unavailable |

Requirements above describe scope, not new implementation or collection authority. For exact current policies, consult the owner-approved decisions and applicable repository documentation. Do not change provider limits, schedules, credentials, publication rules, or version from this register.

## On-demand status report

Requests such as "METAR status", "NOTAM status", and "Spatchin system status" mean inspect current accessible evidence, read-only. No provider requests, dispatches, changes, or new paid services. Read Linear, GitHub repository and existing workflow/published artifact evidence where accessible. Include time of assessment, operational state (operational, degraded, failed, not implemented, unverified), development state (planned, in development, in validation, blocked, complete), latest verified update and source, coverage, changes since last 24 hours, defects/blockers, related issue/PR links, and next action. Report uncertainty and missing evidence; code, tests, merges, publication and actual data health are separate. Operational status describes software behavior only, not suitability for flight operations. Use unverified if evidence is inadequate, not implemented only with evidence of absence. For aggregate status use one row per system; drill down on request. For systems without a runtime, report relevant validation/maintenance condition and avoid implying live service.

## Scheduled development and reconciliation

Use system labels on affected issues and identify systems in existing cycle reports, daily digest and reconciliation reports. Keep cadence, notification rules, authority levels, merge gates and METAR read-only watch unchanged. Include evidence and next action. No new scheduled task. Keep private evidence and engineering status page private; existing SPA-57 is the future page tracking issue. Do not store live status, secrets, private captures or request ledgers in this public repository.
