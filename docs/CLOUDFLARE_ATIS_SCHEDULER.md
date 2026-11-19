# Cloudflare ATIS scheduler

The `spatchin-atis-scheduler` Worker is a separate timing source for the existing
ATIS collection workflow. At minute zero of every UTC hour, Cloudflare invokes
the Worker, which makes one authenticated `workflow_dispatch` request for
`.github/workflows/atis-update.yml` on `main`. GitHub Actions continues to run
`scripts/update_atis.py`, commit changed `data/atis.json`, and publish GitHub
Pages. The Worker never contacts atis.info or processes aviation data.

The existing GitHub Actions schedules intentionally remain enabled during
preparation and initial operation. The workflow's `spatchin-atis-update`
concurrency group prevents overlapping collectors. Remove those schedules only
in a separate reviewed cutover after repeated end-to-end Cloudflare success;
preserve `workflow_dispatch` so the Worker can continue dispatching the job.

## Offline validation

Node 18 or newer is required. From the Worker directory, run:

```sh
cd workers/spatchin-atis-scheduler
npm ci
npm test
npm run check
npm run deploy:dry-run
```

Tests replace `fetch` with local mocks and make no GitHub or atis.info requests.
The dry run builds locally and does not upload, deploy, create a secret, or
activate a Cron Trigger. Do not run a scheduled development invocation with a
real credential unless an actual GitHub dispatch is separately approved.

## Credential and deployment (owner authorization required)

Create a fine-grained GitHub personal access token outside chat and restrict it
to `codysilly/spatchin` with **Actions: Read and write** repository permission.
Use the shortest practical expiration and track its owner and expiry. Never put
the token in source, `wrangler.toml`, command arguments, files, or logs.

Deployment and secret changes alter Cloudflare production state. After explicit
owner approval, authenticate Wrangler to the intended account and run these
commands interactively:

```sh
cd workers/spatchin-atis-scheduler
npm exec -- wrangler secret put GITHUB_TOKEN
npm run deploy
```

`wrangler secret put` securely prompts for the token and may immediately deploy
a Worker version. `npm run deploy` deploys the reviewed Worker and activates the
`0 * * * *` UTC Cron Trigger. Confirm the deployment summary names only
`spatchin-atis-scheduler`. It needs no route, domain, storage binding, provider
credential, or access to atis.info.

## Diagnostics and verification

Each invocation makes exactly one GitHub request with a ten-second timeout and
no automatic retry. Structured logs contain the UTC timestamp, workflow, ref,
attempt number, outcome, HTTP status, and safe request/rate-limit metadata.
They never include response bodies or credentials. HTTP 204 means GitHub
accepted a dispatch; it does not prove that the workflow or collector succeeded.

After deployment, retain the GitHub schedules while verifying several hourly
cycles:

1. Confirm Cloudflare lists `0 * * * *` in UTC for `spatchin-atis-scheduler`.
2. At minute zero, find one Worker log with `outcome: "accepted"` and
   `http_status: 204`.
3. In GitHub Actions, correlate it with one **Update ATIS Data** run whose event
   is `workflow_dispatch` and whose branch is `main`.
4. Confirm the offline tests, Python collector, and commit step complete. A
   no-change run may produce no commit.
5. When the existing collector finds newer valid data, verify `data/atis.json`
   updates through the normal workflow. Do not make a manual provider request.

## Separate cutover and rollback

Only after repeated successful hourly cycles, use the prepared cutover change
to remove the six `schedule` entries from `.github/workflows/atis-update.yml`.
Keep `workflow_dispatch`. Review and merge that change separately so the old
timer remains available throughout preparation and verification.

For rollback after cutover, first restore the six GitHub schedule entries in a
reviewed workflow change. Once GitHub scheduling is confirmed, disable the
Cloudflare Cron Trigger or roll back/delete only `spatchin-atis-scheduler` in
the Cloudflare dashboard. Do not disable both timing sources at once. Revoking
the GitHub token stops Worker dispatches but is not a substitute for restoring
the GitHub schedule. The Python collector and published data require no rollback
because this Worker does not modify them.
