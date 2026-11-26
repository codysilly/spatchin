# Contributing to Spatchin

Read [AGENTS.md](AGENTS.md) before working in this repository. It defines authority, merge gates, aviation safeguards, and release restrictions. The [README contributor map](README.md#contributor-map-and-project-boundaries) describes runtime and publication boundaries; [docs/README.md](docs/README.md) routes topic-specific documentation. This file adds the working procedure without duplicating those sources.

## Start and scope

1. Confirm the current owner-approved Linear issue, acceptance criteria, repository instructions, exact `main` revision, local changes, and active worktrees or branches.
2. Use one focused issue branch or isolated worktree. Preserve unrelated tracked and untracked material.
3. Record what the change replaces, whether superseded code or documentation was removed, and why anything obsolete-looking must remain.
4. Keep mechanical formatting in a separate commit and record its SHA in `.git-blame-ignore-revs` when the change establishes or expands a formatting baseline.

Do not run a collector merely because its script is in `scripts/`. Routine tests are offline; live aviation-provider requests, workflow dispatches, acquisition-policy changes, production releases, security changes, costs, credentials, and version changes retain the authorization requirements in `AGENTS.md`.

## Verify

Choose checks that exercise the affected behavior. Inspect commands before running them and report the exact commit, operating system, command, result, failures, skips, and untested paths. The established quality entry points are:

```sh
npm run format:check
npm run lint
npm run test:node
npm run test:browser
```

The browser suite requires Chromium and a Python HTTP server. `PYTHON` may select an explicit interpreter and `CHROMIUM_PATH` may select an installed browser. Follow [preview/README.md](preview/README.md) for the network-blocked Python harness and [docs/reference/VALIDATION.md](docs/reference/VALIDATION.md) for current validation context. A historical pass, clean working tree, mergeable PR, successful deployment, and healthy aviation data are separate claims.

## Pull requests and merge

Open an issue-linked PR that identifies changed systems, replacement/removal decisions, exact validation evidence, and remaining acceptance work. Before merge, apply every gate in `AGENTS.md`, including exact-head CI/review checks and inspection of Pages, collector, deployment, and billing triggers. Routine automatic GitHub Pages deployment following a validated in-scope merge is authorized under the November 26, 2026 standing authority in AGENTS.md. Never merge if doing so would initiate another production deployment, provider request, or other restricted operation that lacks its required authorization.

After an authorized merge, verify the resulting commit and applicable deployment without making provider requests, then reconcile Linear with evidence. Documentation, preparation, implementation, validation, merge, deployment, and operational acceptance remain distinct states.
