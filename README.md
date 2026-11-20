# Spatchin

The public website at https://www.spatchin.com/ displays the charcoal “Not cleared for takeoff… yet.” holding page.

**The development dashboard is not publicly published.** After the owner confirmed that prototype access must be restricted, GitHub Pages was configured to exclude `dashboard/` and the synthetic `preview/` folder from its Jekyll build. The working v0.9 dashboard remains in the repository for local development and offline testing. A signed-in preview requires a separate protected hosting arrangement; GitHub Pages does not authenticate visitors at a path.

The public repository itself, including the dashboard source, and any root-level published static files are still public. Do not store credentials or private captures in this repository or in published assets. The existing METAR and ATIS schedulers remain unchanged. SPA-74 adds a separate scheduled AWC TAF snapshot collector for the four verified stations. SPA-13 adds a UTC forecast-time selector and calculated runway wind components from the saved decoded TAF periods, with uncertainty labels. It does not publish the development dashboard.
