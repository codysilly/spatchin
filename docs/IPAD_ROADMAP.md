# 13-inch iPad roadmap

**Owner decision:** November 24, 2026. **State:** long-term product goal; plan only.
**Linear:** [SPA-82 parent](https://linear.app/codesilly/issue/SPA-82/plan-13-inch-ipad-experience) · [full roadmap](https://linear.app/codesilly/document/spatchin-13-inch-ipad-roadmap-b05a86dda3e6)

## Decision

Build a 13-inch iPad-friendly Spatchin, using the current web application and its published aviation snapshots. Target portrait, landscape and resizable iPadOS window layouts. First try a responsive, installable Progressive Web App (PWA). Evaluate a native/App Store app only if the PWA has a measured limitation. This goal does **not** authorize public release, new aviation-provider calls, paid Apple services, account/sync infrastructure, security changes, or a version bump.

Do not start the iPad work ahead of current NOTAM, collection reliability, source verification or publication safeguards.

## Architecture assessment — repository main on 2026-11-24

- The dashboard is HTML/CSS/JavaScript with browser-side readers and `data/*.json` snapshots published through existing controlled collection workflows. No new iPad collector or backend is needed.
- `index.html` contains the viewport tag and an Apple touch icon but no web app manifest or service-worker registration.
- `charcoal-dashboard.css` renders three columns at wide sizes, two below 1120 CSS px and one below 760 CSS px. A current 13-inch iPad Pro is approximately 1032 × 1376 CSS pixels in portrait and 1376 × 1032 in landscape, so the existing default is two/three columns. Actual card fit requires review, especially long METAR, TAF and NOTAM text.
- `app.js` implements Pointer Events (touch, pen, mouse) for card reorder and arrow-key reorder; airport selection/order use localStorage. No verified real-iPad behavior yet.
- The browser fetches same-origin snapshots. Reuse the 130-airport catalog, 30-airport display limit, removable MEM default, SCAN, TAF UTC forecast controls, ATIS, raw NOTAM reading and source links.
- The uploaded November 11 source ZIP predates the current repository; always inspect live main before implementation.

## Phases and acceptance

1. [SPA-83 — audit tablet layouts](https://linear.app/codesilly/issue/SPA-83/audit-13-inch-ipad-layouts): record screenshots, overflow, density, target sizes and navigation at about 1024–1032px portrait, 1366–1376px landscape and narrower resizable windows. Treat simulator results as simulated.
2. [SPA-84 — adaptive dashboard](https://linear.app/codesilly/issue/SPA-84/design-adaptive-tablet-dashboard): keep the desktop visual baseline while improving column behavior, cards, tables, expanded NOTAM content and UTC forecast controls. Owner decides any major change to approved design.
3. [SPA-85 — touch and accessibility](https://linear.app/codesilly/issue/SPA-85/improve-tablet-touch-controls): SCAN, slider/date entry, card reordering, keyboard focus, minimum practical tap areas, VoiceOver and scroll/drag behavior.
4. [SPA-87 — offline aviation cache policy](https://linear.app/codesilly/issue/SPA-87/define-offline-aviation-cache-policy): decide whether a shell-only cache is safest. If any snapshot caching is proposed, show offline/age/UTC/source/unknown coverage and never present stale aviation data as current. No provider side effects.
5. [SPA-86 — installable PWA](https://linear.app/codesilly/issue/SPA-86/make-spatchin-installable-on-ipad): manifest, correct icons, standalone navigation and updates; add a service worker only with the above safe cache policy. Do not imply cross-device storage sync.
6. [SPA-88 — real iPad verification](https://linear.app/codesilly/issue/SPA-88/test-ipad-safari-and-multitasking): Safari and installed app, portrait/landscape/Stage Manager, 1 and 30 cards, source text, all runway ends, touch and keyboard, offline/network changes. Record iPadOS version, exact commit and screenshots. Browser emulation alone cannot close this issue.
7. [SPA-89 — native distribution assessment](https://linear.app/codesilly/issue/SPA-89/assess-native-ipad-distribution): optional comparison of PWA, wrapper and native app; owner decision before paying, publishing or starting a native distribution path.

## Aviation and release gates

The iPad client must continue to read published snapshots; it must not make direct FAA, AWC or ATIS provider requests. All runway ends stay visible; retain original NOTAM text, original source links, UTC/Zulu times, collection/observation/freshness labels and explicit unknown coverage. Preserve the existing wind thresholds, no implied runway-open status, MEM default and 30-airport cap.

The app must keep its work-in-progress and operational-use warnings. Changes to current public behavior, production release, new credentials/security boundaries, acquisition policy or paid services require their applicable owner approvals. Keep version v0.9 until an authorized version change. Do not merge a docs PR to `main` if its automatic Pages deployment would violate the release gate; verify trigger behavior first.

## Verification status

**Planning only.** This roadmap documents inspected source code, not successful iPad Safari/device tests or a deployed PWA.

Apple reference: [Add web app to iPad Home Screen](https://support.apple.com/en-ie/guide/ipad/ipad8f1f7a29/27/ipados/27), [WebKit Safari features](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/).
