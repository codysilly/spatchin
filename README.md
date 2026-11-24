# Spatchin

**Public dashboard:** https://www.spatchin.com/

The owner directed the working v0.9 dashboard back to the public homepage on November 24, 2026. The holding page has been retired. A prominent warning above the dashboard states exactly: **WORK IN PROGRESS. Under development and not yet validated.**

The dashboard is an unvalidated supplemental information aid, **not for real-world flight planning, navigation, runway status decisions, or flight operations**. Source, staleness, missing-data, forecast uncertainty, and NOTAM-coverage warnings remain in their original UI context.

GitHub Pages publishes `index.html`, the existing root JavaScript/CSS/branding, and the existing `data/*.json` snapshots. No direct FAA, AWC, or atis.info request is made by the browser; collectors, budgets and schedules are unchanged. The `dashboard/` duplicate remains available for local compatibility but is excluded from public Jekyll publishing with `preview/` and `staging/`. Keep the version at v0.9 until the owner authorizes a version change.

**Private staging retirement:** The old Cloudflare Access and Worker configuration for `dev.spatchin.com` is no longer required. Its removal must be completed in the owner's Cloudflare account; a GitHub PR does **not** delete Workers, Access applications, domains, or billing resources. Do not remove Access protection from an active Worker merely to make the old route public. See Linear for retirement tracking. Previously saved secrets must not be printed or committed.

## Future iPad app

On November 24, 2026, the owner added a **long-term 13-inch iPad app goal**. The first proposed delivery path is an iPad-optimized, installable PWA that reuses the existing dashboard and same-origin published aviation snapshots. This remains planning work: it does not change the current MVP priority, activate an iPad release, add provider requests, incur costs, or increase the v0.9 version.

See [iPad architecture and phased roadmap](docs/IPAD_ROADMAP.md) and [Linear SPA-82](https://linear.app/codesilly/issue/SPA-82/plan-13-inch-ipad-experience). The plan covers portrait/landscape/resizable layouts, touch controls, safe offline behavior, actual iPad testing and optional native distribution.
