# Documentation map

Repository policy and contributor entry points remain at the root: [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md), and, when added, `CONTRIBUTING.md`. Runtime entry points such as `index.html`, `CNAME`, JavaScript, CSS, assets, and published snapshots also remain at the root or in their runtime directories.

## Product and interface

- [Dashboard behavior](DASHBOARD.md)
- [UI design](UI_DESIGN.md)
- [Branding](BRANDING.md)
- [SCAN](SCAN.md)
- [13-inch iPad roadmap](IPAD_ROADMAP.md)

## Data and acquisition

- [C070 registry](C070_REGISTRY.md) and [reference evidence](reference/README.md)
- [ATIS coverage](ATIS_COVERAGE.md)
- [C070 runways](C070_RUNWAYS.md)
- [NOTAM snapshots](NOTAM_SNAPSHOTS.md), [adapter](NOTAM_ADAPTER.md), [review](NOTAM_REVIEW.md), [refresh](NOTAM_REFRESH.md), [MEM capture](MEM_CAPTURE.md), and [publication conditions](NOTAM_PUBLICATION_CONDITIONS.md)
- [METAR watchdog](METAR_WATCHDOG.md)

## Infrastructure and governance

- [ATIS scheduler](CLOUDFLARE_ATIS_SCHEDULER.md), [METAR scheduler](CLOUDFLARE_METAR_SCHEDULER.md), and [TAF scheduler](CLOUDFLARE_TAF_SCHEDULER.md)
- [System register](SYSTEM_REGISTER.md)
- [GitHub Pages publication boundary](PUBLICATION_BOUNDARY.md)

Offline NOTAM/NMS research code and its command map live in [`scripts/notam/`](../scripts/notam/README.md). Routine collectors remain directly under [`scripts/`](../scripts/).
