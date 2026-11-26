# Separate data publication investigation

**Linear:** SPA-105. **Evidence date:** November 26, 2026. **Scope:** investigation and offline proof only. No Pages setting, workflow, collector, schedule, provider request, credential, staging resource, version, or production file changed.

## Recommendation

If a cutover is later authorized, keep the existing `www.spatchin.com/data/*.json` URLs and publish one explicitly allowlisted GitHub Pages artifact containing both the application shell and the complete data set. Build and validate the artifact before a dedicated deployment job. Do not publish data from `raw.githubusercontent.com`, do not deploy a Worker for this purpose, and do not split the application and JSON across origins.

This preserves same-origin browser behavior and makes the deployed unit inspectable while excluding repository engineering material. It does **not** make each collector transaction atomic with the others: the artifact must be assembled from a deliberately selected set of snapshot commits, with freshness and schema gates, before one deployment. A production design must retain the existing independent collector schedules, request budgets, failure behavior, and last-good snapshots.

## Current evidence

The current Pages source is the repository branch and Jekyll exclusion file described in [PUBLICATION_BOUNDARY.md](PUBLICATION_BOUNDARY.md). Every merged data commit can cause a full Pages build even when only one snapshot changed. The ten most recent successful Pages runs inspected on November 26 took 40–76 seconds from run creation to completion; these are observed workflow durations, not a latency guarantee. Read-only response-header checks at 13:47 UTC returned `Cache-Control: max-age=600` for both `/` and `/data/metars.json`, with the same `Last-Modified` deployment time. A completed deployment therefore does not prove that every edge or browser immediately serves the new snapshot. The browser already adds a timestamp query and requests `no-store`, but production acceptance should still compare the expected manifest digest and retrieval timestamp through the public URL.

GitHub documents custom Pages workflows as checkout/build, `upload-pages-artifact`, then `deploy-pages`, with `pages: write`, `id-token: write`, and a deployment environment. The Pages artifact is one gzip/tar payload with no links; the officially supported site size is 1 GB. The upload action's default retention is only one day, so its deployment artifact is not a sufficient backup. See [GitHub custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), and [`upload-pages-artifact`](https://github.com/actions/upload-pages-artifact).

## Alternatives

| Approach | Same origin | Publication surface | Atomicity and recovery | Assessment |
| --- | --- | --- | --- | --- |
| Current `main` branch/Jekyll | Yes | Broad; current exclusions still expose engineering files | Git history supports reconstruction, but each data commit rebuilds the broad site and rollback is another branch commit/deployment | Keep until an authorized replacement passes production validation |
| Dedicated Pages source branch | Yes | Can be narrow if generated, but stores generated publication history in another mutable branch | One branch revision per release; rollback requires a deliberate branch update and deployment | No-cost, but adds branch synchronization and protection complexity without the artifact build/deploy separation |
| Allowlisted Pages artifact | Yes | Exact runtime allowlist | One validated artifact per deployment; prior release can be rebuilt and redeployed from a pinned commit/manifest | Preferred; native Pages path and clearest boundary |
| GitHub Release asset or raw repository URL | No | Narrow | Independent file replacement, CORS/cache/origin differences, and browser URL changes | Reject for production JSON delivery |
| Third-party object storage/CDN | Usually no without additional configuration | Narrow | Provider-specific versioning and rollback | Not justified for the MVP; may add cost, credentials, access, and policy work |
| Cloudflare Worker/Pages proxy | Can appear same-origin after DNS/routing changes | Narrow | Programmable, but adds runtime, deployment, security, and possible cost boundaries | Out of scope and explicitly not deployed by this investigation |

## Explicit allowlist

[`config/pages-publication-allowlist.json`](../config/pages-publication-allowlist.json) contains only the root HTML, runtime JavaScript/CSS, required branding assets, `CNAME`, and the five published JSON snapshots. The proof deliberately excludes documentation, tests, scripts, workers, package manifests, lockfiles, workflow files, research tools, unused branding sources, local archives, caches, screenshots, and staging/preview/dashboard trees.

The allowlist is deny-by-default: a newly required runtime asset causes a test or build failure until it is consciously reviewed and added. Data files must parse as JSON. Every copied file receives a byte count and SHA-256 digest in a release manifest. The generated `.nojekyll` marker makes the proof independent of Jekyll processing; whether to retain it in production is part of the cutover review.

## Offline proof and rollback

The proof script never performs network I/O:

```sh
node scripts/publication/pages-artifact-poc.mjs build . /tmp/spatchin-releases release-one
node scripts/publication/pages-artifact-poc.mjs activate /tmp/spatchin-releases release-one
node scripts/publication/pages-artifact-poc.mjs rollback /tmp/spatchin-releases
node --test tests/pages-artifact-poc.test.mjs
```

`build` creates a new immutable release directory, copies only allowlisted files, validates JSON, and verifies the manifest. `activate` verifies every digest before atomically replacing a small local active-release pointer. The test builds two releases, activates both in order, rolls back, and verifies that the prior release becomes active. This models release selection and proves the rollback inputs; it does not claim GitHub Pages itself uses this pointer or that a production rollback has occurred.

For a future Pages implementation, rollback should build the allowlist from the previously accepted Git commit and recorded manifest, upload it as a new artifact, deploy it through the protected `github-pages` environment, and verify public digests/freshness. Do not rewrite data history or reuse an unverified expired artifact.

## Freshness, failure, backup, and cutover gates

Before any authorized cutover:

1. Define a release manifest that records source commit(s), each snapshot retrieval time, schema result, digest, and expected public URL. Reject mixed or stale inputs according to existing source-specific policy; do not invent one cross-source freshness threshold.
2. Keep collectors independent. A collector failure retains its last-good checked-in snapshot and must not block unrelated acquisition; the publication build decides whether the complete set is safe to deploy.
3. Serialize Pages deployments so an older artifact cannot finish after a newer one. Validate actual Pages deployment ordering and whole-site visibility rather than assuming atomic behavior from the artifact format.
4. Preserve Git as the primary reproducible source and maintain the independent backup/restore evidence tracked by SPA-96. Set artifact retention deliberately if artifacts are also used as short-term recovery inputs; the one-day default is inadequate.
5. Exercise failed build, failed deployment, stale input, corrupt JSON, digest mismatch, superseded run, and prior-release redeploy paths in a non-production environment. Record detection and recovery time.
6. Compare the public manifest and all five same-origin JSON responses after deployment, accounting for the observed ten-minute cache header. Keep the prior accepted release ready until that verification completes.
7. Review custom-domain preservation, Pages environment protection, permissions, concurrency, Actions usage, and exact action pins. Confirm no collector or provider workflow is dispatched by the publication workflow.

Changing the Pages source, workflow permissions, environment protection, public allowlist, or production deployment path is a production/publication and security-boundary decision requiring the applicable owner authorization. This investigation recommends a path but does not authorize or perform the cutover.
