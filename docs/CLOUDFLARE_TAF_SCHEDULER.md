# Cloudflare TAF scheduler

Status: prepared for owner-authorized activation. Not deployed by a repository merge.

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

## Supervised cutover

Existing GitHub cron entries remain as a temporary fallback. During the
overlap, GitHub may run both triggers (the existing concurrency group
serializes collectors, not deduplicates them). Do not leave both schedulers
active indefinitely. Observe several Cloudflare cycles, correlate accepted
HTTP 204 logs with GitHub workflow_dispatch runs and successful collector
steps, and verify returned/missing C070 station counts and the published
snapshot/deployment. A no-change run can succeed without a commit.

Then remove only the six GitHub schedule entries in a separate reviewed PR,
preserving workflow_dispatch and the concurrency group. If a cutover fails,
restore GitHub schedules and verify them before disabling the Cloudflare cron.
Do not disable both timing sources at once. Keep the METAR validation task
read-only. No version bump.
