# Cloudflare TAF scheduler

The common dispatch implementation and preserved independent settings are documented in [SHARED_SCHEDULERS.md](SHARED_SCHEDULERS.md).

Status: owner reports Worker activation; SPA-80 cutover removes the fallback GitHub TAF cron. Cloudflare is the sole scheduled TAF dispatch source after this change.

The isolated `spatchin-taf-scheduler` Worker uses the existing METAR timing architecture.
One UTC Cron Trigger, `8-58/10 * * * *`, runs at minutes 08, 18, 28, 38, 48 and 58.
It sends one authenticated POST to GitHub's `taf-update.yml/dispatches` endpoint on
`main`. GitHub Actions still collects the C070 TAFs and publishes the existing
`data/tafs.json` snapshot. The Worker never contacts AWC, FAA or atis.info.
METAR and ATIS schedulers are untouched. No public route, workers.dev endpoint,
preview URL, storage or new provider credential is required.

## Validation before activation

Use Node.js 22 or newer and the checked-in lockfile.

```sh
cd workers/spatchin-taf-scheduler
npm ci
npm run check
npm test
npm run deploy:dry-run
```

All dispatch tests use mocked fetch. The dry-run does not deploy. Check the
Cloudflare account is on the Free plan and has capacity for one more Cron
Trigger. This design adds 144 scheduled invocations per day and one outbound
GitHub subrequest per invocation. Do not upgrade the plan or accept charges.
See https://developers.cloudflare.com/workers/platform/limits/ and
https://developers.cloudflare.com/workers/configuration/cron-triggers/.

## Owner-authorized activation

Use the owner's authenticated Wrangler session in the intended Cloudflare account.
Confirm the Worker name is exactly `spatchin-taf-scheduler`. Do not change any
existing METAR, ATIS or dashboard Worker, DNS, or access configuration.

Use a securely held fine-grained GitHub token restricted to
`codysilly/spatchin` with repository Actions: Read and write. If a new token is
needed, the owner creates it outside chat and records its expiration. Do not
revoke or rotate a token used by an existing scheduler. Never expose any token
in chat, logs, command arguments, configuration files or shell history.

```sh
npm exec -- wrangler secret put GITHUB_TOKEN
npm run deploy
```

The secret command prompts interactively and may create and deploy a Worker
version. If Wrangler asks to create the missing Worker, verify the name before
accepting. The deploy command activates the reviewed cron configuration.
Do not run a separate live test invocation; observe the normal cron.
The Worker fails before network access if its credential is missing. Each
invocation has one attempt and a 10-second timeout. HTTP 204 means accepted,
not completed. Logs redact credentials and omit response bodies.

## Cutover record — November 24, 2026

The owner reports that `spatchin-taf-scheduler` version
`2a7da5fd-0e5f-4c4b-82f1-26abe6f5351e` is deployed with the
`8-58/10 * * * *` UTC cron and the existing GitHub Actions token.
GitHub [TAF run 45435578402](https://github.com/codysilly/spatchin/actions/runs/45435578402)
started at 16:18:27Z via `workflow_dispatch`, succeeded, and published
129 valid C070 station reports (KNQA absent) in commit
`ab0c45685f644b5cb4fda09bafe1c65fe9b7131a`.
[Pages deployment 45435651256](https://github.com/codysilly/spatchin/actions/runs/45435651256)
succeeded. These are GitHub observations; a Cloudflare HTTP 204 log was not
directly inspected. The owner explicitly accepted the remaining cycle evidence
as successful and authorized cutover without further observation.

The GitHub workflow now retains only `workflow_dispatch`, with its original
`spatchin-taf-update` concurrency group and collector steps. The Cloudflare
Worker remains the only scheduled dispatcher. No direct provider call was made
for this cutover.

If Cloudflare timing or dispatch fails, restore the six original GitHub cron
entries from version history in a reviewed rollback PR, verify scheduled GitHub
execution and data publication, then disable the Cloudflare cron to avoid dual
acquisition. Do not disable both timing sources. Keep METAR and ATIS schedulers,
the METAR validation task, the C070 source, and v0.9 unchanged.
