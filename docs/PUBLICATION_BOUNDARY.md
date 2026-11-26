# GitHub Pages publication boundary

Audit date: November 26, 2026. Scope: current tracked repository content and the deployed `www.spatchin.com` Pages site. This is a publication inventory, not authorization to change Pages configuration.

## Configured boundary

`_config.yml` excludes only `dashboard/`, `preview/`, and `staging/`. Jekyll also omits dot-prefixed repository paths by default. The root application, `assets/`, and `data/` are intentionally part of the public site.

The following tracked engineering material is therefore also within the current Pages source boundary:

- `scripts/`, including routine collectors, maintenance utilities, and offline NOTAM/NMS research code;
- `tests/`, including source tests and synthetic fixtures;
- `workers/`, including scheduler source, tests, manifests, and Wrangler configuration;
- `docs/` and `docs/reference/`, including development runbooks and reference fixtures;
- root package manifests and lockfiles.

Read-only deployed checks returned HTTP 200 for representative paths in each class: a NOTAM research Python module, a JSON test fixture, scheduler worker source, a Markdown document, and the root npm lockfile. Public source access is not the same as an enabled collector or permission to execute provider requests.

## Sensitive-content review

A filename-only scan of tracked files checked common private-key, cloud-key, GitHub-token, OpenAI-key, and assigned-secret patterns without printing candidate values. It found one credential-shaped `client_secret` assignment in a synthetic history-import test. Direct context review classified it as test data, not an active secret. Existing secret-focused regression tests remain applicable. This scan is useful evidence but cannot prove that no sensitive content exists.

Untracked local archives, caches, review output, worktrees, and Python bytecode are outside Git and are not part of the Pages deployment. They must remain untracked.

## Decision boundary

No exclusion, Pages source, workflow, deployment, access-control, provider, or version setting changed in this audit. Reducing the source publication surface would alter production publication behavior and requires its applicable authorization. Track that change separately from documentation relocation so its compatibility and rollback can be reviewed explicitly.
