# Shared scheduler implementation

SPA-104 consolidates the ATIS, METAR, and TAF Cloudflare scheduler implementation without consolidating their deployments.

`workers/shared/github-workflow-scheduler.js` owns the common GitHub workflow-dispatch request, timeout, error classification, safe logging, credential redaction, and scheduled-event handler. Each Worker retains a small `src/index.js` that supplies only its fixed workflow filename and User-Agent. `workers/shared/scheduler-contract.js` applies the same offline behavioral contract to every Worker.

The following remain independent and unchanged:

| Worker | Cron (UTC) | GitHub workflow | User-Agent |
| --- | --- | --- | --- |
| `spatchin-atis-scheduler` | `0 * * * *` | `atis-update.yml` | `spatchin-atis-scheduler` |
| `spatchin-metar-scheduler` | `*/10 * * * *` | `metar-update.yml` | `spatchin-metar-scheduler` |
| `spatchin-taf-scheduler` | `8-58/10 * * * *` | `taf-update.yml` | `spatchin-taf-scheduler` |

Each Worker keeps its own `wrangler.toml`, package and lockfile, Cloudflare Worker name, cron trigger, `GITHUB_TOKEN` binding, deployment command, logs, and rollback path. A change to shared code must pass tests and a Wrangler dry-run for all three packages. Do not use the shared module to merge credentials, schedules, dispatch targets, deployment resources, or failure state.

This refactor does not deploy Workers, dispatch GitHub workflows, contact aviation providers, change acquisition timing, change provider budgets, or modify v0.9.
