# Cloudflare METAR scheduler

The `spatchin-metar-scheduler` Worker replaces only the timing source for the
existing METAR collection workflow. Every ten minutes, Cloudflare invokes the
Worker, which makes one authenticated `workflow_dispatch` request for
`.github/workflows/metar-update.yml` on `main`. GitHub Actions still runs the
Python collector, commits changed `data/metars.json`, and publishes GitHub
Pages. The Worker does not retrieve weather data.

Cloudflare is the production scheduler. The six legacy GitHub Actions `schedule`
entries were removed during the November 19, 2026 cutover. The GitHub workflow
retains `workflow_dispatch`, and its `spatchin-metar-update` concurrency group
prevents overlapping collectors.

## Read-only local validation

The Worker has no runtime dependencies. Wrangler is installed locally as a
development dependency, and Node 18 or newer is required. These commands do
not deploy a Worker, create a secret, activate a Cron Trigger, or contact the
GitHub dispatch or AWC endpoints:

```sh
cd workers/spatchin-metar-scheduler
npm ci
npm test
npm run check
npm run deploy:dry-run
```

The tests replace `fetch` with local mocks and make no AWC or GitHub requests.
The dry-run builds and validates the deployment bundle locally without
uploading it. npm scripts resolve the repository's pinned Wrangler dependency;
no global Wrangler installation is required. Do not use
`wrangler dev --test-scheduled` with a real secret unless an intentional GitHub
dispatch is separately approved.

## Owner-controlled credential preparation

Create a fine-grained GitHub personal access token yourself; never paste it into
chat, source files, Wrangler configuration, shell history, or logs. Restrict the
token to the `codysilly/spatchin` repository and grant repository permission
**Actions: Read and write**, which GitHub requires for the workflow dispatch
endpoint. Choose the shortest practical expiration, record its owner and expiry
in the owner's credential inventory, and rotate it before expiry. An expired or
revoked token produces an authentication-failure log until replaced.
GitHub documents this under
[Create a workflow dispatch event](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).

Creating the token changes GitHub account state and requires the owner's
participation and approval. Merely preparing the token does not authorize any
Cloudflare command. In particular, `wrangler secret put` is not a read-only
credential setup step: Cloudflare creates and immediately deploys a new Worker
version when the secret is changed.

## Approved production activation

Stop after the dry-run until the owner explicitly approves production
activation. In an approved maintenance window, authenticate the local Wrangler
CLI to the intended Cloudflare account and run the following commands
interactively:

```sh
cd workers/spatchin-metar-scheduler
npm exec -- wrangler secret put GITHUB_TOKEN
npm run deploy
```

Both commands can change Cloudflare production state and require explicit owner
approval. The first command securely prompts for the token, creates a new
Worker version, and deploys it immediately. The second deploys the reviewed
source and configuration, including the production Cron Trigger. Do not enter
the token through a command-line argument, file, chat, or unattended job.

After the approved activation, confirm that the deployment summary shows the
Worker name `spatchin-metar-scheduler` and cron `*/10 * * * *`. Cron Triggers
use UTC. Do not add a route or custom domain: this Worker needs only a
Cron Trigger and outbound HTTPS. It is independent of any other Cloudflare
Worker, DNS record, storage binding, or Codrasil resource.

At the expected invocation rate (about 4,320 scheduled invocations per 30-day
month), the Worker fits comfortably within the Cloudflare Workers Free plan's
documented 100,000-request daily allowance and 50-subrequest limit as of
implementation. It uses one outbound subrequest per invocation and only a small
amount of CPU time; waiting on GitHub does not count as CPU time. Cloudflare
limits and pricing can change, so verify the current plan before deployment. No
paid service is required by this design. See Cloudflare's current
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
and [Cron Trigger documentation](https://developers.cloudflare.com/workers/configuration/cron-triggers/).

## Logs and failure handling

Each invocation makes one attempt with a ten-second timeout and no automatic
retry. Structured logs include the attempt number, UTC timestamp, HTTP status,
outcome, workflow, and ref. Failures are classified as missing credential,
authentication failure, rate limit, network timeout/failure, or unexpected
response. GitHub request IDs and safe rate-limit metadata are recorded when
available. Response bodies and authorization values are never logged.

HTTP 204 means only that GitHub accepted the dispatch. It does not establish
that a workflow run started, the collector succeeded, observations changed, or
GitHub Pages published a new file.

### Per-airport METAR retention diagnostics

The GitHub Actions **Update METAR Data** job logs one line for each airport
whose saved observation is retained rather than replaced. The line shows the
ICAO code, reason, saved and upstream observation times in UTC, candidate count,
and validation-rejection counts. Reasons are:

- `missing_upstream`: no record for that airport in the successfully parsed
  response. This does not prove the station failed to issue a METAR.
- `rejected_upstream`: the response included airport records, but none
  passed validation. Rejection counts identify missing raw text, invalid
  observation times or wind speeds, future observations, or reports outside
  the seven-day acceptance window.
- `older_upstream`: the newest accepted upstream report predates the saved
  observation.
- `unchanged_upstream`: the accepted upstream report is identical to the
  saved observation.

When there is no saved observation, the log uses `unavailable` rather than
`retained`. If a network request fails or the response has an invalid shape,
no `missing_upstream` assertion is made. Diagnostics appear in the workflow
job logs even when the public snapshot is unchanged; they are NOT written to
`data/metars.json` and do not create extra commits or Pages deployments.

## Post-deployment verification

Verify each layer separately over several scheduled intervals:

1. **Cloudflare invoked the Worker.** In the Cloudflare dashboard, open the
   Worker, inspect its Cron Trigger and observability logs, and find
   `github_workflow_dispatch` entries at approximately ten-minute intervals.
   Cron execution is best-effort and is not guaranteed at an exact second.
2. **GitHub accepted the dispatch.** Confirm the corresponding Worker entry has
   `outcome: "accepted"` and `http_status: 204`.
3. **GitHub started the workflow.** In the repository's Actions tab, open
   **Update METAR Data** and confirm a `workflow_dispatch` run began after the
   Cloudflare timestamp. Record the run URL or ID for correlation.
4. **The collector completed.** Open that run and confirm the retrieval and
   commit steps completed successfully. A successful no-change run may create
   no commit.
5. **Observations were published when available.** If AWC supplied a newer
   valid report, confirm `data/metars.json` on `main` contains its original
   observation timestamp and the workflow commit. Do not call AWC manually for
   this check.
6. **The public site received the snapshot.** After GitHub Pages publication,
   compare `https://www.spatchin.com/data/metars.json` with the `main` snapshot
   and confirm the browser refreshes it on its existing two-minute interval.

Cutover decision (2026-11-19): The owner verified the METAR data on the public
website and expressly waived the requirement to observe multiple scheduled
runs. The first Cloudflare invocation at 13:20:30Z received GitHub HTTP 204;
the dispatched METAR workflow and GitHub Pages deployment completed successfully.
The separate cutover PR removes the six legacy GitHub schedules and keeps
`workflow_dispatch` active. Keep the existing hourly ChatGPT METAR validation
task unchanged.
