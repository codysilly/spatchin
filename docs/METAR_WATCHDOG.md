# Exception-only METAR incident watchdog

Spatchin's Cloudflare Worker (spatchin-metar-scheduler) invokes the existing GitHub Actions Update METAR Data workflow via workflow_dispatch every ten minutes. The collector stays unchanged. After successful collection and commit/push, GitHub Actions sends a heartbeat to an independent Better Stack monitor. The heartbeat is **inactive** until the owner configures the repository secret. It therefore detects silence even when Cloudflare or GitHub never starts another workflow.

## Alert rules

| Problem | Trigger |
|---|---|
| No completed collection | Better Stack misses its expected heartbeat; configure a 10-minute period and 30-minute grace (approximately 40 minutes after the previous ping) |
| Collector or workflow fails | No success heartbeat. Enable GitHub Actions failure emails as a supplementary channel |
| Widespread stale observations | At least 50% of published METAR entries (and at least two entries) have original obsTime older than 90 minutes, on **two consecutive completed collections**. Send Better Stack's explicit /fail heartbeat |
| Publication lag | When the public JSON is retrievable, its updated_utc trails the repository snapshot by **more than 20 minutes**, and the repository snapshot is at least five minutes old. Send /fail |
| Public endpoint inaccessible | UNKNOWN, not a proven publication failure. A separate HTTP uptime monitor can detect outright endpoint downtime |

The existing dashboard continues to warn at 65 minutes for any individual observation; that does not page the owner. Stale percentage is measured among **published observations**, not missing catalog entries. The offline watchdog keeps a saturating 0/1/2 streak in .github/metar-watchdog-state.json, so separate GitHub runner jobs can establish consecutive failures without making a commit every ten minutes. This state is committed only when it changes. No state is written on healthy initial runs.

The watchdog makes **no aviation-provider API requests** and does not dispatch workflows. It reads data/metars.json, optionally compares with https://www.spatchin.com/data/metars.json, and sends a single HTTP heartbeat to Better Stack after the collector and push step have succeeded. With no heartbeat secret, it makes **zero outbound monitoring requests**. If the heartbeat provider is unreachable, the METAR collector remains successful; a previously activated Better Stack monitor will independently alert for missing heartbeats. An unchanged METAR snapshot does not prevent a success heartbeat.

## Activate without paid services (owner-controlled)

1. Register or sign in to Better Stack's Free plan. As documented in November 2026, it includes up to ten monitors/heartbeats and email alerts. Do not upgrade or enter a payment method.
2. Create a Heartbeat named **Spatchin METAR collection**, expected every **10 minutes** with a **30-minute grace**. Enable email notification to the intended inbox. If configurable, disable repeat alerts or set reminders no more frequently than once per six hours.
3. Copy Better Stack's secret heartbeat URL to **GitHub → codysilly/spatchin → Settings → Secrets and variables → Actions → New repository secret**. Set the name **SPATCHIN_METAR_HEARTBEAT_URL**. Enter the secret only in GitHub's secure form, not chat, a source file, a terminal argument, or the issue/PR.
4. GitHub personal **Settings → Notifications → System → Actions**: enable Email and Only notify for failed workflows. Verify the repository is watched if required. GitHub workflow notification delivery may depend on the triggering account; the Better Stack heartbeat is the independent silence detector.
5. Optional but recommended: add a separate Free Better Stack **HTTP uptime monitor** for https://www.spatchin.com/data/metars.json. This detects an inaccessible endpoint; an HTTP 200 alone does not prove data freshness.

Only Better Stack's documented HTTPS heartbeat endpoint on incidents.betterstack.com or uptime.betterstack.com is accepted. The URL is treated as a credential; it is never logged or included in source. A failed or inaccessible public snapshot is logged as UNKNOWN; do not infer a root cause from it.

## Verify before retiring the hourly ChatGPT task

- Confirm at least three successful Cloudflare-triggered workflow_dispatch runs and corresponding success heartbeats in Better Stack.
- Verify a controlled, synthetic failure test on the **Better Stack monitor** delivers the intended email, then restore a healthy heartbeat. Do not trigger a new AWC collection to test alert delivery.
- Confirm the two-check stale threshold, publication lag detection, and secret redaction tests pass. Keep GitHub's Cloudflare scheduler and collector active.
- Once notification delivery has been verified, disable the existing ChatGPT task **Spatchin METAR validation** (ID 6afde6bf48848191841a30b5e53443ab) to free its slot.

The first heartbeat moves a newly created Better Stack monitor from Pending into active monitoring. A created monitor with no successful initial ping is **not yet** proof of an operational alert path.

## Testing

From the repository root, run:

    python -m unittest tests.test_metar_watchdog

Test scenarios are fully offline and use synthetic observations; they do not contact AWC, the public site, or Better Stack.

References:
- https://betterstack.com/docs/uptime/cron-and-heartbeat-monitor/
- https://betterstack.com/pricing
- https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications
