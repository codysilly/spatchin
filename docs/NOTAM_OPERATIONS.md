# Spatchin v0.9 NOTAM operations

[SPA-18](https://linear.app/codesilly/issue/SPA-18/coordinate-refreshes-and-request-budgets) uses one Windows collector, the existing `FAA_NMS_PRODUCTION` ledger, and the current GitHub Pages source. Run these commands from the reviewed Spatchin checkout on the ledger owner's Windows account. Owner approval for each mutating operation is tracked separately. A printed digest identifies the operation to approve.

## 1. Read-only preflight

```powershell
$Python = (Get-Command python.exe -ErrorAction Stop).Source
$Ledger = Join-Path $env:LOCALAPPDATA 'Spatchin\private-faa\ledger'
$Nms = @('-E', '-s', '-B', 'scripts/notam/nms_operations.py', '--store', $Ledger, '--account', 'FAA_NMS_PRODUCTION')
$Task = 'Spatchin-NMS-Production'

git status --short --branch
git rev-parse HEAD
& $Python @Nms status
Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue | Select-Object TaskName, State
```

Compare the installed commit against the reviewed release. Review the clock, latest accounted attempt, three-minute interval, active reservation, recovery state, watermark, and other clients. Confirm directly that all other clients using this logical account remain paused and account for any activity outside this ledger. Report any unknown accounting to the owner. Keep credentials out of the outputs. The preflight does not check credential presence.

The `lookback_expires_utc` field is the 24-hour wire lookback deadline. Allow time for OAuth and the delta response before that boundary. If continuity expires, report `DELTA_GAP` and stop. The accepted cursor stays in place. A new Initial Load would require a separate decision.

## 2. Review and authorize one catch-up delta

```powershell
$Watermark = Read-Host 'Owner-reviewed continuity watermark in UTC'
$Delta = & $Python @Nms review-delta --expect-watermark $Watermark | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Catch-up review failed' }
$Delta | ConvertTo-Json -Depth 8
```

Send the owner the operation digest, watermark, expiry, accounting status and evidence that other account clients are paused. Ask for separate approval of the exact digest and the external-account attestation. Review can run again if ledger evidence changes. Authentication, the global request, and private acceptance are one operation. The request lower bound is the accepted cursor, and the next cursor is the actual reserved request start rounded down to the second, less one second.

## 3. Execute the approved catch-up

Use the existing authorized credential environment in this process. If owner-authorized credential readiness needs checking, `& $Python @Nms runtime-ready` reports presence without network I/O or credential values.

```powershell
$ApprovedDelta = Read-Host 'Owner-approved catch-up SHA-256'
if ($ApprovedDelta -cne $Delta.approval_sha256) { throw 'Digest differs from reviewed operation' }
& $Python @Nms catch-up --expect-watermark $Watermark --approve $ApprovedDelta --external-history-attested
if ($LASTEXITCODE -ne 0) { throw 'Catch-up failed. Review status.' }
& $Python @Nms status
```

Expected result is `ACCEPTED_PRIVATE_NOT_PUBLISHED` and an advanced watermark. Check account counts and the last accepted delta. Transport failures remain accounted. A request may have reached the provider even if the client received no response.

### Review and recover a retained conflict offline

Use this path for the last failed supervised delta when its hold is `CONFLICT`, the exact response is retained, and initial publication has yet to start. Keep collectors paused. The failed attempt stays `FAILED_ACCOUNTED`. The original data-call reservation and the accepted cursor determine the wire lower bound and next cursor. Older ledgers record the reservation and accepted cursor without separately recording the wire URL or the response digest. Obtain the expected SHA-256 directly from the retained blob during diagnosis and compare it in the review. The digest identifies the locally retained bytes.

```powershell
$Evidence = @('--attempt', (Read-Host 'Reviewed attempt ID'), '--response-sha256',
    (Read-Host 'Reviewed retained response SHA-256'), '--expect-watermark',
    (Read-Host 'Reviewed accepted watermark UTC'))
$Decision = & $Python @Nms review-retained-delta @Evidence | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Retained response review failed' }
$Decision | ConvertTo-Json -Depth 8
```

`OWNER_DECISION_REQUIRED` identifies an exact pair of different GeoJSON features at the same revision time and with no C070 association. When the proposed treatment is to preserve both originals privately without choosing an authoritative variant, add the reviewed pair digest and re-run the review. Other unresolved errors stop recovery.

```powershell
$Evidence += @('--preserve-unresolved-pair', $Decision.unresolved_pair_sha256)
$Recovery = & $Python @Nms review-retained-delta @Evidence | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $Recovery.status -ne 'REVIEW_ONLY') { throw 'Recovery candidate unavailable' }
$Recovery | ConvertTo-Json -Depth 8
$ApprovedRecovery = Read-Host 'Owner-approved retained response recovery SHA-256'
if ($ApprovedRecovery -cne $Recovery.approval_sha256) { throw 'Digest differs from reviewed operation' }
& $Python @Nms recover-retained-delta @Evidence --approve $ApprovedRecovery
if ($LASTEXITCODE -ne 0) { throw 'Recovery failed. Review status.' }
& $Python @Nms status
```

If execution was interrupted, the same command and approval either complete the transaction or report `ALREADY_RECOVERED`. Follow the SQLite journal procedure in section 9 if a hot journal blocks read-only status. Check the original response retrieval time, the recovered watermark and revised lookback deadline, and the unchanged accounting before continuing with section 4. Offline acceptance and publication require distinct approvals.

## 4. Review the exact publication candidate

```powershell
$Candidate = & $Python @Nms review-publication | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Candidate review failed' }
$Candidate | ConvertTo-Json -Depth 8
& $Python @Nms serve-review --sha256 $Candidate.manifest.sha256
```

Open the printed loopback URL in a private browser window on the collector. Keep the URL within the local session and close the browser and server when done. Review all 130 entries, the airport and literal runway lists, complete LOCAL_FORMAT where supplied, missing-text disclosure, SCAN, source label, retrieval UTC, UNKNOWN coverage and freshness, including desktop and narrow layouts. Exercise a failed same-origin refresh in the browser and confirm the last accepted reader remains visible. Review source terms and any current legal notices before publication.

Check the staged copy independently with Windows file size and SHA-256.

```powershell
$Copy = & $Python @Nms stage-review --sha256 $Candidate.manifest.sha256 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Private staging failed' }
if ((Get-Item -LiteralPath $Copy.path).Length -ne $Candidate.manifest.bytes) { throw 'Byte count differs' }
if ((Get-FileHash -LiteralPath $Copy.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Candidate.manifest.sha256) { throw 'Digest differs' }
```

Send the owner the operation digest, manifest, 130-airport count, retrieval time, review conclusions and source-terms confirmation. Obtain explicit permission to release the specified bytes and update the existing Pages source. Keep specimens, private snapshots, and local review captures in protected storage.

## 5. Publish the initial candidate

```powershell
$ApprovedPublication = Read-Host 'Owner-approved initial publication SHA-256'
if ($ApprovedPublication -cne $Candidate.approval_sha256) { throw 'Digest differs from reviewed operation' }
& $Python @Nms publish-initial --approve $ApprovedPublication
if ($LASTEXITCODE -ne 0) { throw 'Publication pending or failed. Review status.' }
```

The publisher compares the current public and repository bytes to the reviewed legacy snapshot before an initial push. It creates a commit in private scratch containing only `data/notams.json` over the fetched `main` tree. A normal fast-forward push preserves unrelated files and refuses a concurrent branch advance. Follow the repository's existing branch policy. A rejected push or delayed deployment can be recovered with the same approval and exact bytes. The helper checks an existing byte match before creating a commit.

## 6. Verify deployment and browser delivery

```powershell
& $Python @Nms verify-publication
gh run list --repo codysilly/spatchin --workflow 'pages-build-deployment' --limit 10
Start-Process 'https://www.spatchin.com/'
```

Check for `PUBLIC_DIGEST_VERIFIED` and a successful Pages deployment of the reported Git commit or a descendant carrying the identical snapshot. Check the live browser display against the protected review and record the public retrieval time. A browser reload or background check shows the existing file's retrieval time. The browser checks the same-origin snapshot with HTTP cache revalidation; its network request does not invoke the collector.

## 7. Authorize recurring operation

Set the acquisition interval and Pages publication cadence to **one elapsed hour**, with **STALE at two hours** from retrieval. At steady state, this allows up to 24 authentication and delta pairs and 24 NOTAM source commits per 24 hours, subject to the existing account-wide request ledger, three-minute provider minimum interval, and 24-hour lookback. A local scheduler tick runs every 15 minutes to absorb scheduling drift. Early ticks make no provider or Pages requests. The stale label concerns snapshot age and leaves coverage UNKNOWN. Review the interval, freshness, account budgets, recurring publication, credential inheritance, runtime identity, Git auth, and local/private retention with the owner before activation.

```powershell
$Release = (git rev-parse HEAD).Trim()
$Standing = & $Python @Nms review-standing --release-commit $Release --interval-hours 1 --freshness-hours 2 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Standing review failed' }
$Standing | ConvertTo-Json -Depth 8
```

Use a clean, pinned checkout and the same Windows identity that owns the ledger. Task Scheduler password logon can run after sign-out and reboot if this account has batch-logon rights, access to the protected NTFS store, and an authorized provider environment and Git credential helper in its noninteractive session. S4U and an interactive terminal's process-local variables cannot establish this. The assignment did not test the designated account's unattended credentials, task registration, reboot, sign-out or reconnection. Validate these in the authorized activation window. Leave the task disabled if a different principal, credential storage or permissions would be needed. Keep the pinned checkout available and obtain a new standing digest for upgrades. [Windows task logon methods](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)

Each published candidate adds a potential Git revision, including when the contents are unchanged and new retrieval evidence advances. Use the candidate review's raw and compressed byte counts to estimate retention. At one hour, annual raw snapshot volume is about `8,760 × manifest.bytes`; estimate full compressed blobs with `8,760 × compressed_snapshot_bytes` and measure actual Git pack growth with `git count-objects -vH` over time. Git packing can reduce the latter. Compare with the recommended 1 GB Pages source limit, 1 GB site limit, 10 builds per hour and 100 GB per month of Pages bandwidth. Include existing weather traffic. This operator refuses snapshots beyond 50 MiB. Track disk usage as private versions and provider responses accumulate. An architecture change, history rewrite, or retention-policy change requires separate authorization. [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) · [GitHub large-file guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

## 8. Install disabled, then activate

Run this section after the owner has authorized the schedule and its credential handling. Use the collector owner's existing Windows logon. The credential input is local Task Scheduler registration, and the task's command contains no credential values.

```powershell
$ApprovedStanding = Read-Host 'Owner-approved recurring operation SHA-256'
if ($ApprovedStanding -cne $Standing.approval_sha256) { throw 'Digest differs from reviewed operation' }
$Config = & $Python @Nms task-config --release-commit $Release --interval-hours 1 --freshness-hours 2 --approve $ApprovedStanding | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Task configuration failed' }
if (Get-ScheduledTask -TaskName $Config.task_name -ErrorAction SilentlyContinue) { throw 'Task already exists' }
$TaskAction = New-ScheduledTaskAction -Execute $Config.executable -Argument $Config.arguments -WorkingDirectory $Config.working_directory
$Trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) -RepetitionInterval (New-TimeSpan -Minutes $Config.scheduler_tick_minutes)
$Settings = New-ScheduledTaskSettingsSet -Disable -StartWhenAvailable -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$Owner = [Security.Principal.WindowsIdentity]::GetCurrent()
$Logon = Get-Credential -UserName $Owner.Name -Message 'Use the existing Windows collector account'
if (([Security.Principal.NTAccount]$Logon.UserName).Translate([Security.Principal.SecurityIdentifier]) -ne $Owner.User) { throw 'Task identity differs from ledger owner' }
try {
    Register-ScheduledTask -TaskName $Config.task_name -Action $TaskAction -Trigger $Trigger -Settings $Settings -User $Logon.UserName -Password ($Logon.GetNetworkCredential().Password) -RunLevel Limited | Out-Null
} finally {
    Remove-Variable Logon -ErrorAction SilentlyContinue
}
Get-ScheduledTask -TaskName $Task | Select-Object TaskName, State, @{Name='LogonType';Expression={$_.Principal.LogonType}}
```

Verify `Disabled`, password logon, the exact executable/working directory, the approved digest, and one task before enabling. Task Scheduler can skip ticks when offline. On reconnect it checks continuity and runs a single eligible cycle. Provider calls have no immediate retry. After acceptance, the publisher verifies the exact bytes; unresolved delivery prevents another acquisition.

```powershell
Enable-ScheduledTask -TaskName $Task
Get-ScheduledTaskInfo -TaskName $Task | Select-Object LastRunTime, LastTaskResult, NextRunTime
```

## 9. Status, stop, and recovery

```powershell
& $Python @Nms status
Get-ScheduledTask -TaskName $Task | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $Task | Select-Object LastRunTime, LastTaskResult, NextRunTime
Disable-ScheduledTask -TaskName $Task
```

Disable prevents new starts. Let a running task settle and inspect its status. Use `Stop-ScheduledTask -TaskName $Task` only if an immediate stop is necessary, and then inspect the durable reservation. If the task cannot start in its noninteractive environment, validate the exact principal and required credential presence under the authorized session. For network outages check Pages and continuity before resuming.

- **Initial publication pending**. Re-run `& $Python @Nms publish-initial --approve $ApprovedPublication` with the original digest. A moved branch is fetched again. Identical repository bytes skip the push and proceed to deployment verification.
- **Recurring publication pending after acceptance**. Run `& $Python @Nms recover-publication --approve $ApprovedStanding` for the existing pending cycle. It uses the accepted state and makes zero provider requests. If Pages reports failure for a source commit already present, investigate and rerun the existing authorized Pages deployment before repeating verification. Preserve the last confirmed digest.
- **Interrupted acquisition or failed cycle without an accepted delta**. Disable the task, confirm no collector runs, and use the commands below after separate approval of the recovery digest and external account attestation. The interrupted attempt remains accounted. A clock rollback, conflicting provider revision, or other unresolved ledger evidence is a hold for owner review.

```powershell
$Recovery = & $Python @Nms review-interruption | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Interruption review failed' }
$Recovery | ConvertTo-Json -Depth 8
$ApprovedRecovery = Read-Host 'Owner-approved interruption recovery SHA-256'
if ($ApprovedRecovery -cne $Recovery.approval_sha256) { throw 'Digest differs from reviewed operation' }
& $Python @Nms account-interruption --approve $ApprovedRecovery --external-history-attested
& $Python @Nms status
```

If a hot SQLite rollback journal prevents a read-only open after a crash, confirm the protected path and process ownership, then run `& $Python @Nms recover-journal --confirm-sqlite-recovery` only with owner authorization. SQLite resolves its own transaction. Keep the ledger, journal, and attempts intact. The continuation window still governs every new delta.

## 10. Operational acceptance

Record the approved code commit, reservation/call outcomes, accepted watermark, contents review, exact initial manifest, successful Pages deployment, public bytes and dashboard checks. Observe a scheduled hourly cycle through acquisition and deployment. Verify the same Windows runtime can resume across sign-out, reboot and an interrupted network connection without duplicate provider attempts or loss of accepted state. Verify the live browser's source, retrieval time, coverage, freshness and SCAN. Keep SPA-18 In Progress until these checks have actual evidence.
