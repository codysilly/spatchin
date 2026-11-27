# Spatchin agent instructions

Owner-approved 2026-11-24; Pages amendment 2026-11-26; context-efficiency revision authorized 2026-11-27 ([SPA-123](https://linear.app/codesilly/issue/SPA-123)). Applies to ChatGPT, Codex and scheduled agents. Latest explicit owner decisions govern requirements; verified GitHub/test/deployment evidence governs implementation; Linear tracks work and acceptance. Earlier routine-approval restrictions are superseded, not unrelated safeguards or platform requirements.

## Authority

**Level 1 — act and summarize:** Approved features/fixes, refactoring, reversible decisions, isolated branches/worktrees, commits/pushes/PRs/reviews/conflict resolution and gated merges; safe tests/builds/integration checks; ordinary trusted dependencies; documentation, Linear issue management, agent coordination and reconciliation.

**Level 2 — act and report:** Significant architecture, major dependency upgrades, synthetic schema development/testing, safe backup changes, authorized development workflows/automation, significant plan departures, vulnerabilities and substantial technical debt. Notification is not permission-seeking.

**Level 3 — explicit owner authorization first:**
- Costs, paid APIs, subscriptions, billable infrastructure, secrets, keys, credentials, protected tokens, login, OAuth, MFA, expanded permissions, access-control/security-policy changes or sensitive personal information.
- Destructive operations, permanent deletion or irreversible migrations.
- Production deployment/public release (except automatic Pages below); aviation-provider access, request budgets, polling or provider-policy changes.
- Major purpose, branding or core-design changes; version increments; expanded agent authority.

**Pages exception (2026-11-26):** Routine automatic GitHub Pages deployments resulting from validated in-scope PR merges are authorized (including PRs #93–#96). All merge, test, security, trigger inspection and deployment verification gates apply. Publication architecture (Pages source, workflow permissions, environment protection, public allowlists), access, credentials, acquisition, budgets, costs and version still require separate authorization. Other production deployments (including Cloudflare Workers) remain Level 3. SPA-105 cutover is not authorized.

Never circumvent restrictions via another tool/environment. Merge authority is not unrestricted deployment or provider-budget authority. Keep v0.9 until owner-approved version change.

## Merge gates

Before merging, verify ALL applicable gates:
1. Approved scope; isolated PR linked to Linear.
2. Relevant tests, repository validation and applicable production builds pass against the actual integration, not just synthetic prototypes.
3. Applicable functional/visual checks pass (accessible previews or desktop/narrow screenshots); escalate core-design changes, not routine acceptance.
4. Actual PR head matches reviewed/tested commit; rerun affected checks after changes.
5. Required GitHub checks pass; reviews resolved; mergeability verified.
6. Diff contains no secrets, private information or unrelated changes.
7. Every implicated Level 3 operation is explicitly authorized.
8. Inspect Actions, Pages, collector and other triggers; stop if a merge would initiate unauthorized deployment, provider requests or billable operations, unless authorized or separately controlled.

Prefer squash for focused changes; pin expected head when supported. Never bypass protections/checks or push features directly to main. Verify merge and resulting Pages deployment when triggered, reconcile Linear and continue eligible work. Merge, deployment and operational acceptance are distinct.

## Engineering and context efficiency

- Use the shortest path to the approved MVP; justify scope expansion and new top-level paths. Inspect instructions, local changes, branch ownership, OS/runtime, permissions and exact commit; coordinate agents, finish existing work first, preserve unrelated changes, untracked files, archived branches and ledgers. Prefer one focused issue.
- Read relevant repository map and procedures in [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/README.md](docs/README.md) before relevant work. Root HTML/JS/CSS, assets and data form the published app; scripts/notam is offline research; workers contains schedulers; preview, staging and legacy dashboard are excluded from Pages.
- Test platform-dependent behavior on target OS; Linux/mocks do not establish Windows compatibility. Review paths, locking, atomic replacement, permissions, subprocesses and environment inheritance. Do not default to WSL, Docker, new machines or paid infrastructure. Use verified existing authorized executors; do not provision or expand access.
- Search specific symbols and read relevant excerpts, not entire repos or historical logs. Retain verbose output outside chat and inspect relevant sections. Give subagents only required context; avoid duplicate work and redundant checks. Keep updates concise. Never weaken meaningful tests, security, correctness, coverage or verification to save usage.
- Attach claims to exact commit, environment, commands and scope; separate direct inspection from owner/agent reports. Mark unavailable execution NOT RUN with cause; disclose failures/skips/untested paths. Never infer quota, credentials, deployment, coverage or test success from absent logs or a clean tree. Correct errors and consequences.
- Handoffs state goal, repo/worktree, commit, authorized actions, validation and expected result; no sensitive captures/secrets. Prefer one copyable handoff over repeated relay.

## Aviation and security safeguards

- Keep tests offline by default. Do not make live FAA, AWC, ATIS or other provider requests without specific authorization. Retain existing acquisition budget, reservations, request accounting, approved polling and freshness thresholds, and failure handling. Do not enable paused collection or automatic FAA retries.
- Before an authorized FAA request, verify collector, code, credential readiness, service limits and authoritative request accounting. Reserve attempts before network I/O; failed or uncertain attempts remain counted. Maintain one designated supervised collector; verify other clients remain paused. Do not infer account history from a missing local ledger or reset it to recover apparent quota.
- Keep secrets out of chat, source, command arguments, screenshots, logs and fixtures. Check credential presence only in the authorized execution process. Preserve authentication for operations that can cost money.
- Maintain the approved raw NOTAM reading MVP, SCAN, original provider representations, literal associations, source access and unknown/stale/missing warnings. Follow current owner-approved display behavior and source-specific terms. No unsupported lifecycle, reciprocal or closure interpretation; do not fabricate aviation data. Keep captures private unless specifically authorized for publication.
- Keep all runway ends visible, including closures and effective times when verified. Preserve approved calculations, wind thresholds, airport behavior (approved C070 catalog, maximum 30 selections, removable MEM default) and provenance. Use UTC for aviation timestamps, distinguish effective/retrieval/check times, and use America/Chicago with date for owner coordination. Distinguish synthetic data from observations. Spatchin is supplementary, not an operational authority.
- Keep public holding page and private dashboard separation. Do not publish private previews or modify deployment/security settings without authorization. Follow source attribution, legal notices and publication review requirements.

## Coordination and governance

Preserve Linear history; never delete issues. Keep acceptance criteria current and close only against actual evidence. Distinguish preparation, implementation, validation, merge, deployment and publication; report material changes, results, limitations and next action.

After two consecutive cycles blocked by the same external obstacle, record both dates, evidence, unfinished work and revisit trigger; preserve branch/PR and truthful issue status. Switch to existing eligible unblocked work. Revisit only with new resolution evidence.

Keep scheduled development/reconciliation cadence/reporting (twice-daily audits, daily digest, two-cycle failover). Audit-only repairs do not authorize unchecked code or merges. Separate METAR validation is read-only: no provider requests, dispatch, code/settings changes or Linear changes.

Spatchin-AI-Working-Rules-v1 and unrelated rules remain applicable. Align project-source/repository copies; record substantive policy changes with date and owner authority. Never expand authority without owner authorization. SPA-123 governance PR requires owner review before merge.
