# Phase 3 — Accessible tablet interface

Status: implementation specification. Backlog P3.1–P3.4.
Depends on [Phase 2](02-playback-api.md); shared state follows in Phase 6.

## 1. Objective and user-facing outcomes

Let Zach choose a familiar movie from recognizable large pictures with one
deliberate activation. Keep feedback understandable, favorites easy to reach,
and recovery possible without a remote, page reload or technical knowledge.

## 2. Current-state analysis

The current Jinja grid uses 85px minimum poster columns, small ellipsized titles,
clickable divs, hover transforms and a three-second toast. It announces "Playing"
before fetch completes, has no request lockout, and does not expose useful
semantics to keyboard/VoiceOver users. There is no fallback image error handler,
favorites, history or offline state. Existing iPads must keep launching during
the migration; preserve the Phase 2 legacy compatibility route.

## 3. Functional requirements

- Home shows Favorites first when populated, Recent requests second, All movies
  always reachable. Initial empty state shows All movies with no setup requirement.
- Play is one tap/VoiceOver activation by default. A caregiver may enable a
  two-step confirmation mode, persisted locally; do not force it on the primary user.
- Poster and title form one native button with an unambiguous accessible name.
- Favorite toggle is a separate adjacent button, never nested inside Play.
- Keep selection visible and provide persistent queued, sent, failed and uncertain
  feedback. Announce command delivery as "Request sent to Fire TV", not "Playing".
- Recover from no network, missing posters, malformed responses, busy/cooldown,
  unknown delivery, empty catalog and unavailable movies.
- Refresh catalog/status when page resumes without submitting commands.
- Preserve usable navigation and artwork during transient internet failures.

## 4. Nonfunctional requirements

Use Jinja plus plain JS/CSS; no SPA rewrite. Target actual household iPad Safari
first, portrait and landscape, with keyboard, switch access and VoiceOver.
Until its OS is recorded, use conservative APIs and feature detection; avoid
requiring service workers, pointer events, localStorage or crypto.randomUUID.

Aim at WCAG 2.2 AA: 4.5:1 normal text contrast, 3:1 large text/control boundaries,
visible focus, zoom/reflow at 200%, reduced-motion support and semantic status.
Use at least 56x56 CSS px targets with 12px separation. Poster minimum width
150px at tablet widths; at 768px layout use at most four columns, retaining readable
titles. Support narrower views with two or one columns as space permits.

Under fixture conditions, feedback appears within 100 ms of activation. No
indefinite spinner; no feedback conveyed only by color. Render useful shell and
local fallback art without a remote poster request completing.

## 5. Detailed technical design

### Layout and interaction

Keep header short, with large labeled Favorites / Recent / All navigation
buttons and one persistent status panel near the top. Avoid hidden swipes,
carousels, drag gestures or modal navigation. Show complete titles with wrapping.
Poster buttons use visually hidden action text as needed: "Play Luca on Fire TV".
Images inside named buttons have empty alt to avoid repeated speech; standalone
fallback text still identifies the title. Use a same-origin fallback image on
load error and remove the error handler to avoid loops.

One pointer/touch gesture must map to one click handler. Do not attach both
touchstart and click launch handlers. Scrolling, long press, favorite toggles and
touch cancellation never launch. Default native click semantics preserve keyboard
and assistive technology activation. Remove hover scaling that can shift targets.

After activation disable all launch buttons immediately; navigation and favorites
remain usable. Keep focus on the selected element using aria-disabled plus guarded
handlers if native disabled would lose focus on the target browser. Make controls
visibly disabled, with a text reason. Rate limit repeat announcements.

Caregiver settings contain confirmation mode and local preference reset behind an
explicit labeled entry, not a gesture. Confirmation names the movie with large
Play and Cancel buttons, initial focus on heading/Cancel; cancel issues no request.
Settings are convenience controls, not an authentication mechanism.

### Client state machine

idle -> submitting -> queued -> command_sent | failed | unknown.
Busy/cooldown admission returns to idle only after Retry-After; submitting/queued
also block other movie launches. Announce "Sending Luca to Fire TV" initially,
"Request accepted" while queued, "Request sent to Fire TV. Check the screen" on
delivery. Never display a success movie overlay as proof of playback.

Generate one random opaque Idempotency-Key per deliberate play attempt, retaining
it in sessionStorage while pending if supported. Use feature-detected Web Crypto
or a supported equivalent; uniqueness is required, secrecy is not. Do not create
a fresh key on fetch retry. Admission uncertainty offers "Check request" using
the same key/payload within the current boot/retention window. It must not offer
automatic resubmission across a restart or expired key window.

Poll the returned status URL on the same origin; reject other origins/paths.
Use 500 ms initially, then 1 second, at most 20 seconds. Pause polling when hidden
and query on resume; never interpret a stale request as current playback. On
20-second timeout, retain an uncertainty panel and explicit "Check TV / Try again"
guidance. A deliberate new request needs a new key and confirmation that it can
restart a movie. If status returns 404 after restart/expiry, do not replay.

Feature-detect AbortController; aborting browser fetch does not cancel backend
delivery. Handle non-JSON/HTML, non-2xx and unexpected schemas without exposing
raw responses. Phase 4 session expiry (401/403) allows an explicit local-session
refresh; never automatic command replay after authentication.

### Favorites and recent requests before Phase 6

Store versioned application keys under zmm.tablet.v1 in localStorage:
favorite_keys, recent_requests (maximum 12 distinct movie keys) and settings.
Only command_sent adds a recent entry, labeled "Recent requests"; failed/queued/
unknown never counts as watched. Local preference writes never block playback.
Catch denied storage/quota/corrupt JSON and fall back to in-memory state with one
caregiver notice. No provider IDs or credentials in storage.

Favorites are local to this browser in Phase 3. Sort by original catalog order;
recents by command-delivery time. Filter removed catalog keys from display while
retaining local data for a future reappearance. Do not delete state on catalog
fetch failure. New users see no empty tabs demanding configuration.

On reload pending keys may be checked, never resubmitted. If no saved request_id
exists because admission response was lost, let the user check TV rather than
guessing success. Phase 6 adds an explicit local-to-household import flow; do not
silently merge across iPads.

## 6. API contracts and JSON examples

Consume Phase 2 contracts unchanged. No new server routes in this phase.

```json
{
  "version":1,
  "favorite_keys":["luca","moana"],
  "recent_requests":[
    {"movie_key":"luca","command_sent_at":"2026-11-07T15:00:01Z"}
  ],
  "settings":{"confirm_before_play":false}
}
```

Example play request: POST /api/play, JSON {"movie_key":"luca"}, with a unique
Idempotency-Key. Treat 202 only as queued. Map errors to user language:

| Condition | User feedback / action |
|---|---|
| 429 busy/cooldown | "Please wait"; enable after Retry-After, never auto-launch |
| 404 movie missing / 409 unavailable | "This movie is unavailable"; refresh catalog |
| failed/device_unauthorized | "Fire TV needs help connecting"; caregiver instructions |
| network loss / unknown / expired request | "The request may have reached the TV. Check the screen." |
| no internet posters | Local artwork and readable titles; launch can still work |
| API/session unavailable | Persistent connection notice with explicit Retry |

## 7. Data models and migration requirements

Catalog authority remains backend stable keys. Local schema version 1 is bounded
and validated: keys match Phase 2 format, unique favorites at most 200, recents
12, timestamps parseable. Discard invalid fields, keep valid preferences.
Never migrate provider IDs from HTML into new local storage.

Phase 2 feature flag allows old template rollback. Phase 6 imports these local
keys with user confirmation. It must not overwrite existing household favorites
or duplicate recent entries without the documented merge preview.

## 8. File-by-file implementation changes

| File | Future change |
|---|---|
| templates/index.html | Semantic buttons, section navigation, persistent live region, settings, initial catalog |
| static/tablet.css | Larger grid/targets, focus, contrast, wrapping, reduced motion |
| static/tablet.js | Request state machine, bounded polling, storage, favorites/recents, recovery |
| static/poster-fallback.svg | Small local fallback asset without external dependency |
| app.py | Render rollout flag/catalog public projection; session bootstrap added in Phase 4 |
| tests/test_api.py | Template has no provider IDs in new mode; cache/mode compatibility |
| tests/ui/tablet.spec.js | Browser behavior, accessibility assertions, network fixtures |
| package.json / lockfile | Development-only browser test runner, e.g. pinned Playwright; no runtime frontend framework |
| docs/tablet-verification.md | Actual device/OS record and manual usability checklist |

## 9. Dependencies and prerequisites

P2.5 must be stable. Record actual iPad model, OS, screen dimensions and assistive
technology usage before choosing a supported minimum Safari version.
Introduce browser test dependencies only for development; choose versions that
support the development host. P3.1–P3.4 sequence is listed in PLANS. Phase 6 is not
required for local favorites; Phase 4 must preserve the same-origin client flow.

## 10. Security and failure handling

Render titles with Jinja escaping and JS textContent, never HTML concatenation.
Allow only approved poster schemes and local paths. Do not embed secrets or
provider IDs. No external analytics, tracking or third-party script dependency.
Respect Phase 2 same-origin and Phase 4 CSRF controls. UI disabling is not server
concurrency protection; the backend remains authoritative.

A broken script must not silently launch via an old GET link. Provide a plain
message and caregiver recovery; the original UI can be restored via rollout flag.
Do not cache command responses or queue offline launches. A full offline install
or service worker is out of scope.

## 11. Automated testing requirements

Test native click/keyboard activation, one request per gesture, double taps,
favorite propagation isolation, scroll/touchcancel, disabled unavailable rows,
confirmation cancel, focus retention and live-region updates. Stub fetch for
every error/state in the table, including malformed HTML and delayed responses.
Assert pending request survives navigation/reload only as a query, never a replay.

Test storage exceptions, invalid versions, bounded history, no recents on failed/
unknown, missing images and refresh while offline. Test local fallback art loads.
Use automated contrast/semantic checks where feasible, plus screenshot viewport
checks. Tests must not contact live backend, TV, TMDB or external posters.
Manual VoiceOver/switch/iPad checks remain necessary beyond automation.

## 12. Measurable acceptance criteria

- One deliberate activation from the default movie grid submits one request.
- Ten rapid activations while pending produce one accepted command attempt.
- Favoriting, scrolling and canceling cause zero launch requests.
- Every interactive target is at least 56px each dimension with 12px separation.
- Titles remain readable at 200% zoom and portrait/landscape on target iPad.
- Keyboard and VoiceOver can select, favorite and recover without pointer use.
- Queued/sent/failed/unknown feedback is visible and announced; no false "playing".
- Denied localStorage, poster outage or one failed catalog refresh cannot break
  the already loaded grid or create an unintended request.

## 13. Deployment, verification and rollback

Prepare client assets and backend feature flag, then obtain deployment approval.
Deploy assets before enabling the new template; force revalidation of HTML and
version static URLs. Verify both an existing cached legacy page and new Safari
page, with a human confirming TV behavior after approved launches. Exercise
offline, favorite and error recovery on the real iPad.

Rollback by disabling new UI flag and restoring matching assets/template. Keep
Phase 2 API/catalog compatibility in place. Do not clear browser preferences;
older UI may ignore them. No deployment or device action occurs during planning.

## 14. Out of scope and unresolved decisions

No streaming, remote desktop, playback scrubber, account login, profile chooser,
automatic queue, recommendation engine or required search input. Search may be
added only if catalog growth warrants it. Confirm caregiver preference on default
confirmation mode, section order and language after observing Zach's interaction.
Device-specific visual tuning and switch-access behavior require real usability
testing; generic WCAG checks cannot establish comfort or independence.
