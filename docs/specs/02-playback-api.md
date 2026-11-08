# Phase 2 — Playback API and catalog

Status: local implementation approved and completed; production/device release
verification remains pending. See [the runbook](../phase-2-runbook.md).
Backlog: P2.1–P2.6 in
[PLANS](../../PLANS.md). Terms here govern later phases.

## 1. Objective and user-facing outcomes

Expose a stable catalog and safe movie launch API while every existing iPad keeps
working. Clients select application keys, never Disney IDs. They can distinguish
accepted requests, delivered launch commands and unavailable playback evidence.

## 2. Current-state analysis

Flask serves a Jinja grid and synchronous `GET /play/<video_id>`. MovieService
loads 44 title/id/poster entries and fetches missing posters at startup. Playback
serializes with a process-local lock and cooldown. FireTVService wakes/Home/opens
Disney+, optionally reconnecting once. No catalog API, keys, aliases or status
exist. The legacy route deliberately accepts valid IDs absent from the catalog;
tests enforce that behavior and exact success messages. See [architecture](../architecture.md).

## 3. Functional requirements

- Add GET /api/movies, POST /api/play and GET /api/status.
- Preserve all existing catalog rows, order, IDs, titles, posters and extra fields.
- Resolve play requests only by immutable application key. Backend resolution of
  titles/aliases is prepared now and exposed to Alexa in P5.1.
- Preserve legacy path, response JSON/statuses, synchronous behavior and unknown
  valid ID pass-through. Both paths must share admission and command serialization.
- New UI uses stable keys and polls status; old cached pages remain valid.
- Never infer playback from ADB success, Home/wake, app foreground or connectivity.
- Record delivery only after inspecting shell output for known Android launch
  errors; arbitrary output absence alone cannot establish actual playback.

## 4. Nonfunctional requirements

Single worker/four threads remains supported. New request admission and status
must not wait for ADB; target p95 under 250 ms on the host with a 100-row fixture,
excluding browser/WAN time. Retain default two-second cooldown. Keep at most one
active/reserved command, 256 job records and 256 idempotency entries, with terminal
records retained for 15 minutes. Do not evict active jobs; reject admission if
necessary. Catalog response under 256 KiB for the current library. No new database,
framework or broker. All mutable API responses use Cache-Control: no-store.

## 5. Detailed technical design

### Catalog and resolution

Each entry adds `key` (lowercase ASCII, pattern
`^[a-z0-9]+(?:-[a-z0-9]+)*$`, at most 80 characters) and `aliases` (up to 20
nonempty strings of at most 100 characters). Keys are assigned once in a reviewed
manifest: `luca`, `moana`, `wall-e`, `frozen-2`, etc. These are examples,
not permission to rename existing data. Duplicate titles use explicit suffixes
approved in the manifest, not startup order. Keys survive title/provider changes.

Resolver normalizes Unicode NFKC, casefolding, punctuation/separators to spaces,
and whitespace collapsing. Explicit aliases handle spoken forms such as
"wall ee", "the greatest showman" and "frozen two". Roman/Arabic numeral matching
requires explicit aliases. Build normalized-name -> set-of-keys indexes. Exact
unique normalized title/alias resolves; zero matches is unknown; multiple matches
returns candidates. Never first-match or fuzzy-autoplay. Duplicate normalized
aliases across different entries are diagnosed, retained as ambiguous, and never
resolved silently. Duplicate keys are fatal validation errors.

New public projection: key, title, poster, aliases, available. A missing or invalid
provider ID yields available=false and cannot be launched by the new API. Legacy
library projection still uses title/id/poster. Poster URL policy permits HTTPS
and same-origin /static paths only; replace unsafe schemes with local fallback.

### Admission, execution and status

Add `submit_play(movie_key, principal, idempotency_key)` beside legacy `play(id)`.
Both use a single admission lock protecting active reservation and cooldown.
Do not hold that mutex during ADB calls. Legacy reserves synchronously and
executes on its request thread; new API reserves then signals one lazy worker
thread through a bounded one-item handoff. No second job queues behind an active
one. Busy/cooldown returns 429 immediately. A worker and legacy request cannot
both own the slot. Release in finally on every failure; failed attempts consume
cooldown at actual dispatch time, matching Phase 1.

Job states: queued -> dispatching -> command_sent | failed | unknown.
queued means accepted only; command_sent means ADB returned without recognized
launch error; failed means known rejection/non-delivery; unknown means timeout or
other ambiguous delivery. Terminal states never imply playing. Record UTC
timestamps for clients and monotonic time for expiry/cooldown. Include random
boot_id and UUID request_id; memory is not a durable queue.

The worker must catch exceptions at its loop boundary and release reservations.
Start lazily after process creation, never on module import or under Gunicorn
preload. On graceful shutdown stop admission, drain at most the configured
shutdown grace; on forced exit never replay. After restart no previous request
evidence exists; lookup of an old ID is 404 and playback is unknown.

For new-path execution add a 15-second absolute command budget across connection,
reconnect and shell transport operations, using the smaller of remaining budget
and configured inactivity timeout for every socket operation. Check remaining
budget while reading output, cap output at 64 KiB, and close owned connections
on expiry. Do not implement deadlines by abandoning a still-running worker thread
and freeing its slot: that could overlap a later command. If dispatch had begun,
budget expiry is unknown. Preserve existing legacy timeout behavior. Include
slow-trickle output and budget-exhaustion fixtures in FireTVService tests.

Existing FireTVService may repeat a broken-connection launch. Preserve that
behavior for legacy calls; new commands must distinguish setup failures before
shell send (one reconnect allowed) from failures after shell send (unknown,
no replay). Keep the exact wake/Home/deep-link launch template. Introduce a typed
internal outcome/exception classification without changing legacy JSON. Recognize
"Error:", "Exception" and "unable to resolve Intent" launch errors with tested
fixtures; record sanitized codes, never raw output in API responses.

### Idempotency and browser migration

Require Idempotency-Key (8–128 printable ASCII characters) on new mutating command
requests. Scope to authenticated principal in Phase 4; before then use one
`lan-household` namespace, shared by the old-free local API only. Store canonical
payload fingerprint, request record and original admission response atomically
with reservation. Same key/same payload returns the original 202 and request_id
without another command, even once terminal; different payload is 409. Invalid,
unauthenticated or unadmitted requests do not consume keys. Cap and expire the
map with job retention. A key is not protection across restarts or after expiry.

Migrate in three releases: backend accepts new catalog fields first; explicitly
migrate catalog after dry-run; then switch tablet fetches to POST. A rollout flag
`TABLET_API_ENABLED` defaults false until API and data validation pass. Never
fallback automatically to legacy GET after a failed/timed-out POST: it may already
have launched. Roll back the rendered client explicitly, leaving both routes live.
Change cache policy for new UI to no-cache so clients revalidate. Existing
300-second cached legacy pages remain functional.

## 6. API contracts and JSON examples

All examples use application keys. UTF-8 JSON, no CORS wildcard, strict body
objects and unknown-field rejection. Read-only endpoints accept GET only.
POST body cap 4 KiB; wrong content type 415; oversized body 413. Errors are JSON
even on validation failures. Before Phase 4, LAN firewall restriction is mandatory;
reject cross-site fetches and mismatched Origin when present, require JSON for POST.

GET /api/movies -> 200:

```json
{
  "schema_version": 2,
  "catalog_revision": "sha256:EXAMPLE",
  "movies": [
    {"key":"luca","title":"Luca","poster":"https://image.tmdb.org/t/p/w500/example.jpg","aliases":[],"available":true},
    {"key":"wall-e","title":"WALL·E","poster":"/static/poster-fallback.svg","aliases":["wall ee"],"available":true}
  ]
}
```

Revision hashes the canonical public catalog; it contains no private ID material.
Catalog reads have no TMDB/ADB calls.

POST /api/play with Idempotency-Key: tablet-EXAMPLE-001:

```json
{"movie_key":"luca"}
```

202 Accepted (including idempotent repeats):

```json
{
  "request_id":"65b80b5f-4a08-4c26-8d92-f2bb90f9b890",
  "movie_key":"luca",
  "command_state":"queued",
  "playback":{"state":"unknown","evidence":"none"},
  "status_url":"/api/status?request_id=65b80b5f-4a08-4c26-8d92-f2bb90f9b890"
}
```

Location uses the same relative status URL; remote aliases return public /api
URLs, never internal /remote paths. A client must poll to learn delivery.

GET /api/status?request_id=... -> 200:

```json
{
  "boot_id":"b82cf412-060d-44c1-ae70-ef9799358797",
  "request":{
    "request_id":"65b80b5f-4a08-4c26-8d92-f2bb90f9b890",
    "action":"play",
    "movie_key":"luca",
    "command_state":"command_sent",
    "accepted_at":"2026-11-07T15:00:00Z",
    "completed_at":"2026-11-07T15:00:01Z",
    "error":null
  },
  "device":{"connection":"unknown","last_checked_at":null},
  "playback":{"state":"unknown","evidence":"none"},
  "retry_after_seconds":0
}
```

Without request_id return the active or most recent request, or request:null.
Device connection values are unknown/connected/disconnected/unauthorized; reflect
last observed connection evidence only, with its timestamp. GET never probes or
wakes the device. Return capabilities object in P5.1. A nonexistent/expired request
ID is 404 request_not_found, with advice that delivery cannot be established.
Phase 4 per-principal queries must not disclose other principals' job details;
household LAN sessions share one household principal.

```json
{
  "error":{
    "code":"cooldown",
    "message":"Please wait before another movie request.",
    "retryable":true,
    "retry_after_seconds":2
  }
}
```

| HTTP | Code / meaning |
|---|---|
| 400 | invalid_request, invalid_movie_key, invalid_idempotency_key |
| 404 | movie_not_found or request_not_found |
| 409 | movie_unavailable or idempotency_conflict |
| 413 / 415 | request_too_large / unsupported_media_type |
| 429 | busy, cooldown or rate_limited; Retry-After rounded up, at least 1 second |
| 503 | catalog_unavailable or dispatcher_unavailable; no accepted job |
| 401 / 403 | Phase 4 authentication_required / forbidden, not device authorization |

Async device failures appear in job.error, not a late change to the original HTTP
response: device_unauthorized, device_unavailable, command_rejected,
delivery_unknown, internal_error. Never return an auth 403 for Fire TV trust failure
in the new API. Preserve old route's existing mapping and exact response, e.g.
200 {"status":"success","message":"Playing video luca-id"}; document that legacy
wording is historical and is not playback confirmation.

## 7. Data models and migration requirements

```json
[
  {
    "key":"luca",
    "title":"Luca",
    "id":"PRIVATE_EXISTING_DISNEY_ID",
    "poster":"https://image.tmdb.org/t/p/w500/example.jpg",
    "aliases":[]
  }
]
```

Implement explicit `tools/migrate_catalog.py --input ... --manifest ... --output ...
--dry-run`; apply requires an explicit `--apply` and creates a timestamped backup
before atomic replacement. Input/output path rules must prevent accidental
overwrite during dry run. Manifest maps existing private ID to reviewed key and
aliases; it contains no credentials, and is backend-only. Reject duplicate IDs
for manual review, do not drop rows. Preserve unknown fields and existing keys.
Already-migrated input produces identical semantic data. Use temp file in the same
directory, flush/fsync and replace; on failure original stays intact.

Compatibility reader accepts old rows for legacy UI. New API returns
503 catalog_unavailable until every row has a valid unique key; never serve a
partial silently rekeyed catalog. Keep a separate catalog validation status from
an empty-but-valid array. Do not replace a bad catalog with an empty saved file.
Poster refresh must preserve new fields. Readiness changes come in Phase 6.

## 8. File-by-file implementation changes

| File | Future change |
|---|---|
| services/movie_service.py | Validation result, keys/indexes, aliases, public projection; retain old lookup/library |
| services/playback_service.py | Admission, worker, jobs, idempotency, snapshots, shared legacy coordination |
| services/firetv_service.py | Typed delivery uncertainty, shell-output classification, safe new-path retries |
| app.py | Three routes, JSON errors, body/header rules, cache headers, client rollout flag |
| config.py | Bounded job TTL/count and rollout options; retain existing environment names |
| tools/migrate_catalog.py | Dry-run/backup/atomic explicit migration |
| docs/catalog-key-manifest.json | Reviewed future manifest, private provider mapping, no secrets |
| movies.json | Approved additive data migration only, preserving all rows |
| templates/index.html | Stable-key client, status polling, honest messages |
| tests/test_movies.py, test_playback.py, test_firetv.py, test_api.py | Contracts, migration, concurrency, error classification, legacy regression |
| tests/test_catalog_migration.py | New migration-specific tests |

## 9. Dependencies and prerequisites

Establish pytest baseline; inspect any changes since this specification. Review
all 44 key assignments and known aliases. Existing ADB/Disney+ authorization stays
unchanged. P2.1–P2.6 order is mandatory except independent test fixtures. No public
network exposure before Phase 4.

## 10. Security and failure handling

Validate key/ID before shell operations; do not accept client provider fields.
Logs use request ID/key/action/duration/code, not credentials or raw shell output.
Unexpected worker errors become sanitized internal_error and release reservation.
A client disconnect never cancels or resubmits a command. After uncertain delivery,
show "The request may have reached the TV. Check the screen before trying again."
Malformed catalog blocks new API admission but not the running legacy route's
syntactically valid pass-through. ADB authorization errors require caregiver action.
Status polling is bounded (500 ms initially, 1 second thereafter; stop after
20 seconds with uncertainty), and GET must never create a command.

## 11. Automated testing requirements

Preserve all existing tests including exact legacy JSON and unknown-ID launch.
Add old/new mixed catalog, collisions, Unicode, unavailable IDs, all-entry
preservation, dry-run/no-write, idempotent migration and injected write-failure
tests. Cover every HTTP status, provider leakage, malformed JSON, headers and limits.

Use barriers/fake clocks to prove concurrent old/new requests serialize, rejected
requests dispatch nothing, failures unlock, worker survives exceptions, idempotent
duplicates dispatch once and mismatched payload returns 409. Test queued/delivered/
failed/unknown transitions, TTL/caps, restart lookup loss, safe pre-send reconnect,
no new-path retry after send, and recognized Android shell failures.
Use fixtures only, no real TMDB/Fire TV. Test JS request flow with fetch stubs;
full browser accessibility coverage belongs to Phase 3.

## 12. Measurable acceptance criteria

- All 44 catalog rows retain original IDs/titles/posters and gain unique stable keys.
- Existing pytest tests remain green; new contract/migration/race tests pass.
- Twenty overlapping requests cause at most one accepted new dispatch while busy.
- Duplicate accepted payload/key produces one job and at most one new-path shell send.
- New API/HTML public data has no Disney IDs; legacy compatibility is explicitly exempt.
- p95 admission/status under 250 ms in the stated local fixture benchmark.
- No new response claims playing/paused; playback remains unknown without observation.
- Old cached and new iPad clients successfully select the same existing movie.

## 13. Deployment, verification and rollback

After separate approval: back up catalog/artifact; deploy compatibility reader and
new API with tablet flag off; run migration dry-run and review row/key diff; apply
approved migration; restart in the existing one-worker configuration; verify
/health, catalog and legacy UI; enable tablet flag only after API smoke tests.
Live TV tests require approval and a human to check picture/CEC.

On failure switch tablet flag off, restore previous code and catalog backup as a
matched pair, restart under approval, and verify legacy launch. Keep .env, HOME and
ADB keys unchanged. Jobs vanish on restart and must not be replayed. No automatic
legacy fallback or data rollback that overwrites later caregiver changes.

Add deprecation usage counters without recording private identifiers. Retire the
legacy route only through a later approved task after two releases, 30 days with
no legitimate calls, migrated iPads and a communicated retirement date. This
phase sets no actual removal date.

## 14. Out of scope and unresolved decisions

No confirmed playback observer, seek/progress tracking, multi-TV, accounts,
database, websocket, cloud queue or public API exposure. Pause/resume/stop and
HTTP title resolution are P5.1 extensions. Confirm key manifest, hardware latency,
safe shell-output patterns and the iPad's OS/browser version before release.
One-second polling and 15-minute RAM retention are initial defaults to validate,
not promises of durable job recovery.
