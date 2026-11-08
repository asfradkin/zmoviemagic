# Phase 3 tablet implementation and verification

Local implementation under the user's separate Phase 3 request, 2026-11-07.
Production rollout and live-TV verification are not authorized by this work.

## Scope and discrepancies addressed

The checkout already implemented Phase 2, including catalog migration, shared
command admission, status, idempotency and a default-off tablet API flag. The
tablet specification is Phase 3. Its remaining local UI work is implemented:

- Replace the flag-on 85px grid, ellipsized titles and hover movement with native
  poster/title buttons, wrapping titles, visible focus, separate favorite buttons
  and a persistent request panel. At 768px there are four columns with posters
  over 150px wide; smaller layouts use two or one. Controls have 56px targets and
  at least 12px separation. Reduced motion is supported without moving targets.
- Show Favorites first when populated, then Recent requests, otherwise All
  movies. Section navigation remains available during a request. Favorites use
  catalog order; recents use delivery time. Removed keys remain in stored data
  but are hidden until they reappear.
- Keep one-activation play as the default. Caregiver settings offer persisted
  confirmation and an explicitly confirmed local preference reset. Confirmation
  starts on Cancel and cancellation sends nothing.
- Disable launch actions immediately using guarded handlers and `aria-disabled`
  to retain focus. Display sending, accepted, delivered, failed and uncertain
  feedback. `command_sent` never claims actual playback. Known device failures
  use fixed caregiver messages instead of displaying arbitrary server content.
- Bound command feedback/polling to 20 seconds (first poll 500ms, then 1 second),
  pause polling when hidden, and refresh catalog/known pending status on resume.
  Catalog refresh is bounded to 10 seconds. Failed/malformed refreshes preserve
  the loaded catalog and local preferences. Images use existing local fallback
  artwork, with the error handler removed before substitution.
- Retain one opaque idempotency key and movie payload per attempt in optional
  sessionStorage, before POST. Accepted IDs survive reload only for GET recovery
  within the existing 15-minute window. Missing admission IDs produce Check TV
  guidance; the client never repeats POST to find an ID. This conservative
  recovery also avoids replay across a backend restart or expired key window.
  Check request only queries a known ID. Try again requires explicit confirmation
  that a new request can restart the movie, and generates a fresh key.
- Honor Retry-After for busy/cooldown without auto-launching. Reject malformed
  admission/status schemas and query only locally constructed status URLs.
  Feature-detect AbortController and Web Crypto. LAN browsers without Web Crypto
  use timestamp/counter/random request keys; credentials are never stored.
- Store only validated application keys, delivery timestamps and settings in
  `zmm.tablet.v1`: at most 200 unique favorites and 12 distinct recent requests.
  Only verified `command_sent` job status adds a recent entry. Denied/quota/corrupt
  localStorage falls back to memory with one caregiver notice.

## Changed files and boundaries

| Files | Change |
|---|---|
| `templates/index.html` | Flag-on semantic layout, settings, escaped public initial catalog, versioned assets |
| `static/tablet.css` | Responsive grid, wrapping, target size, contrast, focus and reduced motion |
| `static/tablet.js` | Client state, preference validation/storage, navigation, confirmation, bounded recovery |
| `tests/tablet.test.cjs` | Controller, storage, retention, schema and recovery unit tests |
| `tests/ui/render_fixture.py`, `tests/ui/tablet.spec.cjs` | Real-template rendering and intercepted browser fixtures |
| `tests/test_api_v2.py` | Escaping, private-ID exclusion, asset availability and flag rollback regression |
| `package.json`, `package-lock.json`, `.gitignore` | Pinned development-only browser dependency and ignored test output |
| Planning documents and this checklist | Current local status and remaining release gates |

No backend routes, services, catalog fields, provider IDs, Disney+ deep links,
ADB identity, command templates, worker settings or production configuration
changed. The existing `TABLET_API_ENABLED` flag still defaults false. The
flag-off rendered grid and legacy route retain their existing behavior. Phase
4 authentication, Phase 5 voice/control and Phase 6 shared state remain deferred.

## Observed automated results

Baseline: 13 JavaScript tests passed. The sandbox Python baseline had 112 passes
and one failure because Windows denied the isolated loopback socket connection.
With that restriction lifted, the unchanged baseline passed all 113 tests.

Final commands and results:

```text
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider
114 passed in 4.73s

node --test tests/tablet.test.cjs tests/ui/tablet.spec.cjs
33 passed, 0 failed, 0 skipped (16.42 seconds)
```

The client total consists of 19 unit tests and 14 Chromium browser scenarios.
Browser tests cover Enter/Space and native touch, ten rapid activations producing
one POST, favorite isolation, scroll/touchcancel/context-menu events, unavailable
buttons, confirmation cancel, focus retention, persistent live-region feedback,
safe HTML handling, unauthorized devices, auth failure, missing request IDs,
reload-only GET recovery, uncertain retries, denied/corrupt storage, missing
images, failed catalog refresh, catalog removal/reappearance, reset cancellation,
cooldown timing, hidden/resume behavior and a delayed response past 20 seconds.

Measured activation feedback stayed under 100ms in the fixture. Automated checks
verified 56px control targets, grid spacing, complete titles, text contrast at
least 4.5:1 and control boundaries at least 3:1 for visible fixture controls.
Viewport checks ran at 768x1024, 1024x768, 384x512 and 320x600; a separate 200%
text-enlargement check found no horizontal overflow. A 384px viewport also models
the reflow width of a 768px view at 200% zoom; this does not replace Safari zoom
testing. Portrait and narrow screenshots were visually inspected; all viewport
screenshots are generated locally in ignored `test-results/` when requested.

The browser tests use bundled Playwright 1.62.1 and an existing cached Chromium
executable. All page requests are intercepted; posters outside the fixture origin
are aborted. The Python renderer imports Jinja directly, not the application,
and uses synthetic catalog data. No real TMDB, Fire TV, AWS or production service
was contacted. No dependencies were installed during this task. The pinned
lockfile uses package versions and integrity metadata from the bundled runtime;
`npm ci` itself was not run here.

## Reproducing checks

Use the intended Python with Flask/Jinja/pytest installed. In this checkout it is
`.venv/python.exe`, not necessarily `.venv/Scripts/python.exe`. The browser fixture
uses it by default; set `ZMM_TEST_PYTHON` to another appropriate interpreter.

```powershell
$env:TEMP = Join-Path (Get-Location) '.venv\pytest-temp'
$env:TMP = $env:TEMP
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider
node --test tests/tablet.test.cjs
# On a development host with Node 20+ and npm, install test dependencies once:
npm ci
npx playwright install chromium
npm run test:ui
```

Alternatively reuse installed Playwright via `NODE_PATH` and an existing browser
via `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. The observed Windows run used:

```powershell
$env:NODE_PATH = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = "$env:LOCALAPPDATA\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
$env:ZMM_UI_SCREENSHOTS = '1'
node --test tests/tablet.test.cjs tests/ui/tablet.spec.cjs
```

The Windows sandbox blocked Chromium startup and the loopback test. The passing
full runs used reviewed execution outside those restrictions, with the same
mocked/intercepted dependencies. Initial blocked or failing attempts are not
counted as passing runs.

## Device record and manual acceptance gates

User reports an approximately three-year-old iPad running the latest iPadOS and
Safari. Zach does not use VoiceOver or switch access in regular use. Exact model,
OS/browser build and usable screen dimensions remain unverified; no minimum
Safari version is asserted. Do not mark the following checks complete from
Chromium or synthetic events:

| Manual check on the household iPad | Result |
|---|---|
| Record model, exact iPadOS/Safari version and dimensions | Pending |
| Portrait/landscape, complete titles, comfortable target sizes, 200% zoom | Pending |
| Deliberate tap launches once; rapid taps, scroll, long press and cancellation are safe | Pending |
| Favorites, navigation, confirmation, cancellation and preference reset are understandable | Pending |
| Offline, poster outage, busy, failed/uncertain feedback and explicit recovery | Pending |
| Safari suspend/resume, reload, storage denial and cached legacy page compatibility | Pending |
| Keyboard focus and optional VoiceOver/switch smoke checks | Pending |
| Zach/caregiver usability observation and confirmation-mode preference | Pending |
| Actual wake/Home/deep-link and human-observed TV picture | Pending; separate live-device approval required |

The major remaining risk is target-Safari/device interaction and usability.
Synthetic touch cancellation and browser semantics do not establish physical
touch, long-press or assistive-technology behavior. Request state is in RAM and
optional browser storage, not a durable queue. Storage denial or cleared browser
data can lose local favorites or recovery evidence. A request timeout cannot
cancel an already delivered backend command; the UI always warns before an
uncertain repeat.

## Release and rollback

Deployment, enabling the production flag, service restarts and live-device tests
require separate explicit approval. Follow the Phase 2 runbook's deployment
trigger inspection, artifact backup and one-worker constraints. Publish matching
assets before enabling the new template. New HTML remains `no-cache`; CSS and JS
URLs use version `3` to avoid reusing older client assets.

For the existing legacy UI, disable `TABLET_API_ENABLED` under approved production
change control. Both APIs and `/play/<video_id>` remain available. To restore a
previous flag-on implementation, restore its matching template and client assets
together. Preserve browser preferences, catalog and ADB identity; do not replay
pending/unknown commands. There is no catalog migration in this phase.

No commit, push, deploy, production service restart, DNS/tunnel change or live-TV
verification was performed.
