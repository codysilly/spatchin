# Private Spatchin development site

Status: **prepared, not deployed**. Do not claim `dev.spatchin.com` is active until real Access and browser checks pass.

The public `www.spatchin.com` remains a holding page on GitHub Pages. Its `_config.yml` excludes `dashboard/`, `preview/`, and `staging/` from publication. The separate Cloudflare Worker is intended to serve the current v0.9 dashboard at `https://dev.spatchin.com/` to approved accounts only.

## Security design

- Worker custom domain `dev.spatchin.com`; `workers_dev = false` and `preview_urls = false` prevent alternate public Worker addresses.
- Worker-level Cloudflare Access must cover **All traffic**, not just previews. Configure exact-email Allow rules; do not use Everyone, Bypass, or an entire email domain.
- The Worker independently verifies the signed Access JWT against the configured team's rotating JWKS, issuer and application audience. It also checks an exact-email allowlist. Missing configuration, invalid signature, or unlisted email returns 403.
- `run_worker_first = true` prevents the static asset router from bypassing the JWT gate. `build.mjs` copies only explicitly allowlisted HTML, JS, CSS and approved branding.
- The Worker proxies only the five existing **public** JSON snapshots from `https://www.spatchin.com/data/`, after authentication. No direct FAA, AWC or atis.info API calls are made. The originals remain public.
- Root public source code and published data remain public because the GitHub repository is public. Private page access does not make the repository private.

Cloudflare reference: https://developers.cloudflare.com/workers/configuration/cloudflare-access/ and https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/.

## Required prerequisites

1. Confirm `spatchin.com` is an **active zone** in the owner's Cloudflare account. Cloudflare Worker custom domains require an active Cloudflare zone. Do not change public DNS or nameservers without a separate review.
2. Use the Cloudflare Workers Free and Cloudflare One Free plans where available. Do **not** start a paid plan, add payment details, or approve recurring charges without the owner's authorization.
3. Choose the exact authorized email addresses. These must appear in both the Cloudflare Access policy and Worker allowlist.
4. Keep credentials, Access tokens, email login codes and secret values out of GitHub, ChatGPT, and screenshots.

## Windows PowerShell setup

From the owner's synced, clean Windows checkout:

```powershell
Set-Location "$HOME\Projects\spatchin"
git status --short
# Preserve any uncommitted work before switching branches or pulling.
git switch main
git pull --ff-only
Set-Location staging
npm.cmd install
npm.cmd test
npm.cmd run build
npx.cmd wrangler login
npx.cmd wrangler deploy
```

**The first deployment must be fail-closed.** Without the three configuration secrets below, the Worker returns HTTP 403 for every request. This allows Cloudflare Access to be configured before any dashboard page can load.

In Cloudflare: Workers & Pages > **spatchin-private-dev** > **Access** > **Protect this Worker behind Access** > **All traffic**. Configure an explicit Allow policy for only the authorized email addresses. Review it in Zero Trust > Access > Applications and remove broad Allow/Bypass rules.

Set the secrets using the interactive terminal prompt (do not put their values in command arguments):

```powershell
npx.cmd wrangler secret put TEAM_DOMAIN
npx.cmd wrangler secret put POLICY_AUD
npx.cmd wrangler secret put ALLOWED_EMAILS
```

- `TEAM_DOMAIN`: full Cloudflare Access issuer URL, such as `https://example.cloudflareaccess.com`.
- `POLICY_AUD`: that Access application's Audience Tag from the Zero Trust application settings.
- `ALLOWED_EMAILS`: comma-separated exact authorized emails.

Recheck the Worker Access policy and deployment settings after entering the secrets.

## Verification before marking SPA-72 Done

1. Incognito desktop and iPhone sessions must require Access and must not receive HTML, JS, CSS, logos or `/data/*.json` without authorization.
2. Login using an **unlisted** email must be rejected.
3. Login using an approved email must show Spatchin v0.9 with MEM, SCAN, runway ends and snapshot-backed weather and NOTAM display.
4. Test `/data/metars.json` through the private domain: it must use the currently published public snapshot without sending any FAA/provider requests.
5. Confirm no publicly reachable `.workers.dev` or preview/version address. Confirm `https://www.spatchin.com/dashboard/` and `/preview/` remain unpublished.
6. Check logout, expired session, and revocation. Confirm `https://www.spatchin.com/` is still the holding page.

**There is no automatic deployment workflow.** Manual, signed-in Cloudflare setup is required before any deployment. The isolated staging code and CI checks do not modify production.
