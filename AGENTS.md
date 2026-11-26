# Spatchin agent instructions

Owner-approved policy, effective 2026-11-24. Applies to ChatGPT, Codex and scheduled development agents. These instructions supersede earlier routine-approval restrictions, not platform requirements or unrelated safeguards. The latest explicit owner decision governs product requirements; verified GitHub state and test/deployment evidence govern implementation; Linear governs work and acceptance tracking.

## Authority

Level 1 — act without additional approval:
- Implement approved features and fixes; refactor and make reversible technical decisions.
- Create isolated branches/worktrees; commit, push, create and review PRs, resolve conflicts and merge validated PRs under the gates below.
- Run safe tests, builds and integration checks; install ordinary trusted dependencies.
- Update documentation, create/prioritize/update/close Linear issues, coordinate agents and reconcile records.
- Report routine work in development summaries.

Level 2 — act and report material changes:
- Significant architecture decisions, major dependency upgrades, database schema development/testing with synthetic data, safe backup changes, development workflows and automation within existing authority, significant plan departures, security vulnerabilities and substantial technical debt.
- Notification is not a request for permission.

Level 3 — obtain explicit owner authorization before:
- Costs, paid APIs, subscriptions, billable infrastructure, secrets, keys, credentials or protected tokens.
- Account login, OAuth consent, MFA, expanded permissions, access-control or security-policy changes, sensitive personal information.
- Destructive operations, permanent deletion, irreversible migrations.
- Production deployments or public releases; aviation-provider access, request budgets, polling frequency or provider-policy changes.
- Major changes to purpose, branding or core design; version increments; expansion of agent authority.

Do not circumvent a restriction using a different tool or environment. The authority to merge is not authority to deploy or consume provider budgets. Keep Spatchin at v0.9 until an owner-approved version change.

## Merge gates

Before a merge, verify all applicable conditions:
1. Approved scope and an isolated PR linked to its Linear issue.
2. Relevant tests, repository validation and applicable production builds pass. Verify actual application integration; synthetic prototypes alone are insufficient.
3. Applicable functional or visual verification passes. Agents can verify approved behavior using accessible previews or emitted desktop/narrow screenshots; escalate changes to core design, not routine acceptance.
4. Actual PR head matches the reviewed and tested commit; rerun affected checks after changes.
5. Required GitHub checks pass, outstanding review findings are resolved, and mergeability is verified.
6. Diff has no secrets, private information or unrelated changes.
7. No Level 3 category is implicated without explicit authorization.
8. Inspect Actions, Pages and other deployment/collector triggers. A merge must not initiate an unauthorized production deployment, provider request or billable operation. If it would, stop until authorized or a separately controlled deployment path exists.

Prefer squash for focused changes. Pin the expected head when supported. Never bypass branch protection or required checks. Never push feature changes directly to main. Verify the merge result, reconcile Linear, and continue eligible work. A merge does not establish deployment or operational acceptance.

## Engineering and coordination

Prioritize the shortest working path to the approved MVP. Do not expand scope without a demonstrated need. Inspect repository instructions, local changes, branch ownership, operating system, runtime, permissions and exact commit. Preserve unrelated changes, untracked files, archived branches and ledgers. Coordinate concurrent agents; finish existing work before creating another branch or issue. Use one focused issue where possible.

Test platform-dependent behavior on its target OS. Linux or mocked tests do not establish Windows compatibility. Review paths, locking, atomic replacement, permissions, subprocesses and environment-variable inheritance. Do not require WSL, Docker, new machines or paid infrastructure as automatic workarounds. Never weaken meaningful tests to make them pass. If execution is unavailable, record NOT RUN and the actual limitation. Use an existing authorized executor when verified; do not provision or expand access.

When the same external obstacle prevents meaningful progress for two consecutive development cycles, record both dates, evidence, unfinished work and the revisit trigger. Preserve the branch/PR and truthful issue status. Switch to an existing eligible unblocked issue. Revisit only on new evidence of resolution; do not repeat unchanged investigations.

Attach test claims to the exact commit, environment, commands and scope. Distinguish direct inspection from owner or other-agent reports; disclose failures/skips/untested paths. Never infer quota, credential readiness, deployment, coverage or successful tests from missing logs or a clean tree. Correct mistakes and their practical consequences. Handoffs identify goal, repository/worktree, known commit, authorized actions, required validation and expected result; do not request sensitive captures or secrets. Prefer one useful copyable handoff over repeated owner relay.

## Aviation and security safeguards

- Keep tests offline by default. Do not make live FAA, AWC, ATIS or other provider requests without specific authorization. Retain existing acquisition budget, reservations, request accounting, approved polling and freshness thresholds, and failure handling. Do not enable paused collection or automatic FAA retries.
- Before an authorized FAA request, verify collector, code, credential readiness, service limits and authoritative request accounting. Reserve attempts before network I/O; failed or uncertain attempts remain counted. Maintain one designated supervised collector; verify other clients remain paused. Do not infer account history from a missing local ledger or reset it to recover apparent quota.
- Keep secrets out of chat, source, command arguments, screenshots, logs and fixtures. Check credential presence only in the authorized execution process. Preserve authentication for operations that can cost money.
- Maintain the approved raw NOTAM reading MVP, SCAN, original provider representations, literal associations, source access and unknown/stale/missing warnings. Follow current owner-approved display behavior and source-specific terms. No unsupported lifecycle, reciprocal or closure interpretation; do not fabricate aviation data. Keep captures private unless specifically authorized for publication.
- Keep all runway ends visible, including closures and effective times when verified. Preserve approved calculations, wind thresholds, airport behavior (approved C070 catalog, maximum 30 selections, removable MEM default) and provenance. Use UTC for aviation timestamps, distinguish effective/retrieval/check times, and use America/Chicago with date for owner coordination. Distinguish synthetic data from observations. Spatchin is supplementary, not an operational authority.
- Keep public holding page and private dashboard separation. Do not publish private previews or modify deployment/security settings without authorization. Follow source attribution, legal notices and publication review requirements.

## Project management and scheduled work

Use GitHub, Linear and dated owner decisions as described above. Preserve completed history; do not delete issues. Keep descriptions and acceptance criteria aligned with current approved behavior and evidence. Distinguish preparation, implementation, validation, merge, deployment and publication. Close issues only when their actual acceptance criteria are met. Record material changes, test results, limitations and next action concisely.

The development/reconciliation task retains its existing cadence and reporting, including twice-daily audits, daily digest and two-cycle blocker failover. Audit-only repair does not grant unchecked code changes or merges; use the development merge gates. The separate METAR validation task remains strictly read-only: no provider requests, workflow dispatch, code/settings changes or Linear modifications.

This policy supplements Spatchin-AI-Working-Rules-v1; all unrelated rules remain applicable. Keep current project-source and repository copies aligned. Record substantive policy changes with date and owner authority. Do not expand authority without owner authorization.
