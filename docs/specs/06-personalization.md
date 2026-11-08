# Phase 6 — Personalization and reliability

Status: implementation specification. Backlog P6.1–P6.6.
Depends on stable keys/jobs in [Phase 2](02-playback-api.md), local tablet state in
[Phase 3](03-tablet-ui.md), authentication in [Phase 4](04-secure-connectivity.md)
and backend control framework P5.1. Alexa itself is not a persistence dependency.

## 1. Objective and user-facing outcomes

Share favorites across household devices, show recent movie requests, recover
cleanly from Fire TV/network problems and provide useful health information
without waking the TV. Optional Home Assistant consumes the same backend API
without becoming required infrastructure.

## 2. Current-state analysis

Only the catalog is persistent today; MovieService saves posters directly into
movies.json. Playback lock/cooldown and ADB connection caches are process-local.
/health is deliberately only liveness. There are no favorites, recents, readiness
or reconnection backoff. Phase 3 introduces browser-local preferences; Phase 2
adds transient request status. Preserve those compatibility paths and avoid
confusing requests with watched/completed movies.

## 3. Functional requirements

- Read/add/remove household favorites by stable movie key.
- Persist at most 50 distinct recent movie launch requests, newest first, with
  last command-sent timestamp and bounded lifetime (90 days).
- Record recents only for delivered launch commands; do not count admission,
  failures, controls or uncertain delivery as watched.
- Import local tablet favorites explicitly with a preview and no silent overwrite.
- Preserve /health semantics; add readiness and detailed authenticated diagnostics.
- Improve reconnection with bounded backoff and safe retry classification.
- Permit optional HA play/control/status calls using a separately scoped credential.
- All personalization failures must leave already-loaded movie launching usable.

## 4. Nonfunctional requirements

Use a small versioned JSON file, no database unless measured concurrency/size
invalidates the one-process design. One worker owns writes. Cap personal state
at 1 MiB; write operations should complete under 100 ms p95 on local disk with the
50-row history fixture. If disk stalls, preference operations must not hold
PlaybackService command locks. State endpoints have a 2-second response budget;
a filesystem operation that exceeds it is reported unavailable without retrying
the movie command. Python cannot safely cancel an arbitrary blocked fsync: use
a bounded state writer queue/worker, never spawn a thread per write, and retain
at most one pending snapshot plus coalesced history events.

Movie delivery is independent of state write success. Acknowledge favorite updates
only after durable atomic write; do not claim persistence while queued. No polling
health endpoint may wake the TV or send shell commands.

A timed-out preference response may still commit later if its disk write was
already underway. Keep that transaction reserved until the writer finishes; the
client must reread revision and desired state before retrying. Do not report a
timed-out write as definitely unapplied or issue a concurrent replacement write.
Document and test this ambiguity independently of movie-command idempotency.

## 5. Detailed technical design

### State repository and atomic writes

Introduce StateService with a short in-memory mutex, revision counter and one
serialized writer. Never hold its mutex while doing ADB or disk I/O. Commands
publish a bounded post-delivery history event after releasing playback admission;
failure to persist emits a health warning, not command failure/replay. Coalesce
history updates by movie key; record newest timestamp and request ID. Favorites
are explicit durable transactions; cap in-flight mutations and reject busy writes
with 503 state_busy and Retry-After rather than silently dropping them.

Read/modify/write operates on a versioned snapshot with expected revision. Writer
copies snapshot under lock, writes same-directory temp file, flushes/fsyncs,
atomically replaces state.json, fsyncs directory where supported, then publishes
new committed revision. Preserve a known-good backup after successful validation;
never overwrite it with corrupt input. Clean abandoned temp files only inside the
configured state directory after verifying paths. Fail closed for unknown schema
versions without destructive rewriting.

On startup validate current state; if corrupt, quarantine with a timestamp and
attempt valid backup. If neither is valid, use empty in-memory state with
personalization_degraded=true, do not overwrite evidence automatically. Launch
continues. Permission/disk-full/write failure keeps the previous committed state.
Remote preference reads return 503 state_unavailable if recovery is incomplete;
tablet uses cached local state. Provide an operator restore command/runbook.

Use DATA_DIR outside source/release tree, owned by existing service user, mode
0700 directory / 0600 state files. Neither deployment hard reset nor catalog
refresh can erase it. No modification of ADB key permissions or identity.

### Favorites and local import

Favorites remain an unordered set displayed in catalog order; PUT/DELETE per key
are naturally idempotent. Validate known key on add; removing a stale key is allowed.
Use ETag revision and If-Match to prevent multi-iPad lost updates; missing If-Match
-> 428 precondition_required, stale -> 412 revision_conflict. Retrying a desired
PUT/DELETE requires reread and explicit client reconciliation, never overwrite
a newer snapshot blindly.

Import UI displays current household and local favorites, proposes union,
and asks caregiver confirmation. Submit a bounded import with current revision;
server validates keys and unions sets atomically. Unknown keys are returned as
skipped. Do not import local recent requests into server history automatically;
browser timestamps and status evidence are not authoritative. Retain local state
as a backup through migration. No secret or provider ID travels in import JSON.

After enabling shared mode, display server favorites when available and cached
last-good favorites when offline. Local favorite mutations may be saved as
explicit pending preferences only; no silent playback queue. On reconnect show
conflict/merge preview before applying pending changes. Never silently overwrite
household state with one tablet's cached set.

### Recent movies semantics

Store one row per movie: movie_key, last_request_id, command_sent_at and source
(lan/alexa/home_assistant). The UI may label "Recent movies" with accessible help
"Movies requested on Fire TV; watching is not verified." Analytics must not call
these completed watches. Deduplicate repeated job ID, and replace existing movie
row only when the incoming delivery timestamp is newer. UTC ordering with stable
key tie-break; no assumption about playback length or end position.

Legacy valid IDs in the catalog can map to a key for history recording without
changing legacy launch admission. Unknown legacy IDs remain launchable but create
no persisted personal row and never leak their IDs through APIs.

### Liveness, readiness and reconnection

Keep GET /health -> 200 {"status":"ok"}, no-store, no dependency calls. Add
GET /ready for local operators: 200 when catalog validates and dispatcher can
admit work; 503 for invalid catalog/dispatcher failure/shutdown. A busy dispatcher
is ready; ADB offline or a degraded optional state file is not a reason to restart
the web service. Startup can still fail for current mandatory TMDB configuration;
P6.4 makes poster enrichment optional/offline-safe when catalog artwork/fallback
exists, with tests preserving configured enrichment behavior.

Authenticated GET /api/health (health:read scope) provides separate components:
catalog, dispatcher, personalization, ADB connection evidence, last error and
capabilities. No credentials, private IP or shell text. Remote publishing of this
path requires explicit proxy allowlist change and health:read; Alexa does not
receive health:read by default.

Default diagnostics are cached/passive. A caregiver-approved explicit connectivity
check may verify the ADB transport with a bounded non-shell host query, never wake/
Home/play. Do not run probes on every poll. Mark connectivity stale after
60 seconds without observation; stale becomes unknown, not disconnected. A
transport connection alone does not imply Disney+ foreground or playback.

Reconnection policy for new API/control: maximum one reconnect before any shell
send; after send ambiguity -> unknown, no automatic resend. Exponential cooldown
for connection failures 1, 2, 4, 8, 16, 30 seconds with up to 20% jitter, reset
after a successful transport/command. After three consecutive connection failures
open a circuit for 30 seconds; next deliberate user request may half-open one
connection attempt after that interval. Other requests get 503 device_backoff
with Retry-After before admission. Authorization failure opens a separate
needs_authorization state until caregiver intervention/explicit check; do not
repeatedly reconnect in a loop or kill the shared ADB server.

Legacy path keeps existing status/JSON behavior and one-retry policy until approved
retirement; it shares device invalidation and command serialization but is not
silently changed to new backoff 503 semantics. Warn in diagnostics that legacy
calls can still attempt a connection during new-API backoff. No automatic daemon
restart, key regeneration or endless worker loop to "heal" authorization.

### Optional Home Assistant

Provide example HA REST commands for play and control, plus a low-frequency REST
sensor for authenticated status or health (at most every 60 seconds). Use separate
home_assistant principal and scopes; prefer LAN bearer calls with token stored in
HA secrets.yaml. Remote HA additionally needs Access headers. HA sends stable keys,
unique command idempotency keys and JSON. No HA integration may open ADB, resolve
Disney IDs or bypass backend admission. If the chosen HA REST templating cannot
generate a unique per-action key, add a small HA script/helper counter rather
than reusing one constant key.

This is an optional consumer configuration, not a new mandatory service, custom
HA component or source of catalog truth. HA status sensors show last request/
delivery and unknown playback, never falsely report playing/paused.

## 6. API contracts and JSON examples

All local APIs require Phase 4 session/CSRF or scoped bearer; remote aliases always
bearer. Personal data responses no-store. Read scope preferences:read; mutations
preferences:write. Alexa token gets neither unless explicitly needed later.

GET /api/preferences -> 200, ETag: "prefs-7":

```json
{
  "schema_version":1,
  "revision":7,
  "favorite_keys":["luca","moana"],
  "recent_movies":[
    {"movie_key":"luca","last_request_id":"65b80b5f-4a08-4c26-8d92-f2bb90f9b890",
     "command_sent_at":"2026-11-07T15:00:01Z","source":"lan"}
  ],
  "history_semantics":"launch_command_sent"
}
```

PUT /api/favorites/luca, empty JSON object, If-Match: "prefs-7" -> 200 updated
preferences and ETag. DELETE same path uses no body but the same revision and CSRF
rules; return 200 updated preferences even if already absent. Favorite key in path
is validated; no provider IDs. POST /api/preferences/import:

```json
{"favorite_keys":["luca","wall-e"],"mode":"union"}
```

Requires If-Match, maximum 200 keys and 16 KiB body (explicit exception to 4 KiB
command cap); 200 returns preferences plus skipped_keys. No replace mode.
POST/PUT unknown fields -> 400; unknown add key -> 404; 428 missing revision;
412 conflict; 503 state_unavailable/state_busy on storage failures. Remote write
paths remain unpublished by default; add exact allowlist entries only if a remote
consumer is approved. Local UI does not need remote publication.

GET /api/health example:

```json
{
  "status":"degraded",
  "components":{
    "catalog":"ok",
    "dispatcher":"ok",
    "personalization":"readonly",
    "adb":{"connection":"unknown","last_checked_at":null,"retry_after_seconds":0}
  },
  "playback":{"state":"unknown","evidence":"none"}
}
```

Health 200 means the diagnostic response was served, not that components are all
healthy. /ready uses 503 for its defined critical readiness failures. No automatic
TV wake/launch follows from any GET.

## 7. Data models and migration requirements

```json
{
  "schema_version":1,
  "revision":7,
  "favorite_keys":["luca","moana"],
  "recent_movies":[
    {"movie_key":"luca","last_request_id":"65b80b5f-4a08-4c26-8d92-f2bb90f9b890",
     "command_sent_at":"2026-11-07T15:00:01Z","source":"lan"}
  ]
}
```

No file initially is a valid empty new installation; corrupt existing file is a
distinct degraded state. Version every future schema and provide dry-run backup/
restore migration rather than silently resetting. Do not move favorites into
movies.json or rewrite the Phase 2 key manifest. Retain removed keys in storage
until explicit cleanup; filter them from normal UI. Limit/prune history on writes
and reads without causing a disk write on every poll. No historical Phase 1 watch
data exists to backfill. ADB/status jobs remain volatile.

## 8. File-by-file implementation changes

| File | Future change |
|---|---|
| services/state_service.py | Validation, revisions, bounded writer, atomic files/recovery |
| services/playback_service.py | Post-delivery event hook, no coupling of disk failures to command result |
| services/movie_service.py | Optional poster enrichment and legacy ID-to-key history lookup |
| services/firetv_service.py | Connection evidence, safe pre-send reconnect, stale-state handling |
| services/health_service.py | Readiness/component snapshots and backoff/circuit state |
| app.py | Preferences/favorites/import, ready and authenticated health routes |
| config.py, .env.example | DATA_DIR, limits/backoff defaults; no real paths/credentials |
| static/tablet.js, templates/index.html | Household mode, explicit import/merge, cached fallback |
| tools/migrate_state.py | Explicit schema migration/restore dry run |
| ops/home-assistant/zmoviemagic.yaml.example | Optional REST commands/sensors and secret references |
| docs/state-recovery.md | Backup/quarantine/restore/rollback instructions |
| tests/test_state.py, test_preferences_api.py, test_health.py, test_reconnection.py | Persistence, contracts, evidence and fake-clock circuit tests |
| tests/ui/tablet.spec.js | Import, conflict and offline shared-state behavior |

## 9. Dependencies and prerequisites

P6.1 precedes persistence consumers; P6.2 precedes tablet import. P6.4 depends on
Phase 2 classification and P5.1 controls, not on Lambda deployment. Confirm host
local filesystem supports atomic rename/fsync and state directory permissions.
One Gunicorn worker remains mandatory. No HA installation is required for M6.

## 10. Security and failure handling

Personal data stays on household host with bounded retention. Do not record voice
transcripts, child identity, completed-watch inference or provider IDs. Separate
HA credentials from Alexa and allow revocation independently. File paths come
from trusted configuration, never request fields; reject symlink/path surprises
when opening state and temporary files. No downloaded backup URLs.

Corrupt/read-only/disk-full state results in visible caregiver notice and degraded
diagnostics; launches continue and are never retried because history failed.
State writer backlog is bounded and diagnostics expose dropped/coalesced history
counts. No health poll may send a key event. Do not reset a production device or
revoke ADB keys to improve reconnection.

## 11. Automated testing requirements

Use tmp_path, fake clocks, deterministic jitter and simulated file failures.
Test missing/corrupt/unknown-version state, valid backup, quarantine, write/replace/
fsync failure, readonly/disk-full, stalled writer, queue bounds and concurrent
read/modify/write. Demonstrate favorites are acknowledged only after commit,
conflicts cannot lose updates and no ADB lock waits for state I/O.

Test delivery-only history, dedupe, stale/out-of-order timestamps, 50-row/90-day
pruning, known/unknown legacy IDs, no recents from control/failed/unknown jobs.
API tests cover scopes, CSRF, revision errors, import caps/unknown keys and no-store.
UI tests cover consent/merge and offline fallback without command replay.

Health tests fail if device/shell is contacted. Test stale evidence, circuit and
half-open admission, auth intervention, no retry after send, and legacy compatibility.
HA example contract tests use mocked HTTP and fixture keys, not real HA or TV.

## 12. Measurable acceptance criteria

- Favorites survive service restart and appear identically on two authorized iPads.
- Concurrent conflicting updates return 412, with no lost committed preference.
- Crash/failure injection leaves either previous or new valid snapshot, never
  truncated state. Corruption recovery is visible and does not block launch.
- Failed/uncertain/queued commands add zero recent rows; duplicate delivery events
  create one newest row per movie.
- Health/readiness polling sends zero ADB key events and does not wake the TV.
- Repeated connection failures obey configured delays; one half-open attempt only.
- State corruption, WAN outage and HA absence leave the local launch path usable.
- No database/broker is added without a new evidence-based design review.

## 13. Deployment, verification and rollback

After approval create protected DATA_DIR and back up code/catalog and any state.
Deploy state repository with household mode off; verify dry-run validation and
/health plus /ready. Enable persistence hooks, then explicit caregiver import on
one iPad; check a second iPad, conflicts, approved TV delivery and restore rehearsal.
Enable HA only as a separate optional approved configuration change.

Rollback shared UI to Phase 3 local mode while retaining local backup; restore
previous app and matching state schema from a reviewed backup if required. Never
overwrite newer household changes without showing the diff and obtaining approval.
Keep state files outside Git/deployment reset and leave authorized ADB key intact.
Disable HA consumers independently; they must not be needed for core operation.

## 14. Out of scope and unresolved decisions

No multiple profiles/accounts, recommender, full watch analytics, position resume,
cloud synchronization, multi-host writes or durable playback jobs. A database is
justified only if multiple writers/hosts or measured data/concurrency exceeds the
documented JSON limits. Confirm desired household retention, whether recents need
a caregiver clear action (a future explicitly scoped API), actual disk behavior,
and whether HA is installed. Playback confirmation remains unknown until a
separate observer design supplies evidence; this phase does not introduce one.
