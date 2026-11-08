# Phase 2 implementation and release runbook

Local implementation: 2026-11-07. Production rollout is not performed or authorized.
The original Phase 1 baseline descriptions in the architecture and specification
are historical. Phase 3–6 features remain outside this implementation.

## Implemented behavior

- MovieService validates immutable keys and aliases, retains legacy projections,
  resolves unique normalized names and reports ambiguity. No HTTP title resolver
  or transport controls are exposed in Phase 2.
- `/api/movies`, `/api/play`, and `/api/status` share the existing Flask factory.
  API errors are JSON; responses use `no-store`; POST accepts only a bounded JSON
  object with `movie_key` and requires an idempotency header. Cross-site fetches
  and mismatched origins are rejected. LAN firewall restriction remains required;
  this phase does not provide remote authentication or authorize public exposure.
- One lazy background dispatcher shares a reservation and dispatch-time cooldown
  with synchronous legacy requests. Jobs and idempotency are bounded to 256 each
  by default, with 900-second terminal retention; full history rejects admission.
  The worker does not hold the admission mutex during ADB. The one-item handoff
  is not a durable queue and no second command queues behind an active command.
- The new FireTVService path applies a 15-second total budget and 64 KiB output
  cap, checks Android launch errors, and permits at most one retry before shell
  send. After a possibly partial send it returns uncertainty without replay.
  Legacy retry/timeout behavior and exact historical JSON remain compatible.
- Status reads never probe the TV. `command_sent` is delivery evidence only;
  playback stays `unknown`. Restart loses jobs and idempotency; no jobs replay.
- `TABLET_API_ENABLED` defaults false. The flag-off grid and cached legacy pages
  retain the old route. Flag-on HTML contains application keys, local poster
  fallback, accessible native buttons and a persistent status region. It polls
  after 500 ms and then every second, stopping after 20 seconds. It never falls
  back from POST to legacy GET. New HTML uses `no-cache`.
- Approved addition: optional sessionStorage remembers an accepted request ID for
  up to 15 minutes. Reload only reads status; it never resubmits. Terminal known
  outcomes clear the record; uncertainty retains it for later read-only checks.
  Storage denial/corruption cannot dispatch a command.

## Catalog review and local migration

The user approved all 44 assignments in [the review](catalog-key-review.md),
including `the-aristocats` and `the-aristocats-alternate`. Both existing rows and
titles are retained. Resolving their shared title returns two candidates.
The [manifest](catalog-key-manifest.json) is backend-only and contains provider
IDs. Do not serve it through Flask or distribute it to tablet/voice clients.

The user reviewed the [dry-run](catalog-migration-dry-run.json), a byte-verified
original backup, and approved applying it to this local checkout. The
[application report](catalog-migration-applied.json) records the backup path.
Original SHA-256:
`57afe4ffc6d9f7312a57a543c3f8d4444dc6d93bd7215ae5d92ab939defe7fec`.
All original fields, row order, 44 titles/provider IDs/posters and extra fields
are preserved. Two empty posters remain empty in backend storage; the public
projection substitutes the local fallback. Startup never assigns catalog keys.
Poster refresh retains keys/aliases/unknown fields.

Backups created beside `movies.json` are ignored by Git. The additional review
copy is `.venv/phase2-review/movies.before-phase2.json`; keep an operator-owned
backup outside the virtual environment before any approved release. Do not
overwrite later catalog edits with this historical backup.

For a future reviewed migration, first run (development interpreter shown):

```powershell
.\.venv\python.exe -B tools/migrate_catalog.py --input movies.json --manifest docs/catalog-key-manifest.json --output movies.json --dry-run
```

Review row/key assignments and verify a backup before running the same command
with `--apply` replacing `--dry-run`. Apply creates and verifies a timestamped
backup, writes a same-directory temporary file, flushes/fsyncs, then replaces.
Already-migrated in-place data is left byte-for-byte unchanged. Dry-run writes
neither output nor backups, including when input and output are the same path.

## Local verification

Use the checkout's `.venv/python.exe`; it currently has the required dependencies.
The original 26-test suite passed before implementation. On Windows in this
restricted environment, put temporary files in the workspace:

```powershell
$env:TEMP = Join-Path (Get-Location) '.venv\pytest-temp'
$env:TMP = $env:TEMP
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider
node --test tests/tablet.test.cjs
```

The existing explicit 127.0.0.1 socket-timeout test requires execution outside
this sandbox's socket restriction. All TV launches are mocked; no real TMDB,
ADB device, AWS or production endpoint is contacted. Intermediate full suite:
103 Python tests passed in 3.86 seconds, before subsequent review additions.
Final observed results are recorded in [verification](phase-2-verification.md).

The 100-row Flask-client fixture benchmark measured p95 admission 0.87 ms and
status 0.91 ms over 50 admitted jobs. This is a local in-process measurement;
it excludes production scheduling and browser/network time.

Tests cover JSON/header/query validation, error statuses, safe projections,
catalog failure, migration preservation/backups/fault injection, concurrency
(20 simultaneous calls), old/new exclusion, duplicate dispatch prevention,
TTL/capacity, cooldown, shutdown, restart evidence loss, worker recovery, shell
errors, safe retry, deadlines, slow-trickle reads and output limits. Node tests
stub fetch/timers to verify client behavior without a browser or TV.

## Accessibility and iPad checks

User reports a several-year-old iPad running current iPadOS and Safari; exact
model and version are unverified. No browser minimum is inferred from that.

Source/fixture checks cover native button semantics, accessible movie names,
polite atomic status, visible focus style, unavailable controls, preserved grid
dimensions, local fallback and no-script instructions. Layout review fixtures
were generated locally under `.venv/phase2-review/` with 768×1024, 1024×768 and
384-pixel widths and stubbed fetch. Browser inspection could not complete:
Computer Use stopped because it could not confidently verify the current URL.
No visual layout, keyboard, zoom, Safari or VoiceOver pass is claimed.

Before enabling the flag, record device/browser versions and manually verify:

- Portrait/landscape grid, scrolling and posters; no horizontal overflow at
  tablet widths or 200% zoom. Titles and focus must remain understandable.
- Keyboard Tab, Enter and Space each request only the focused movie. VoiceOver
  announces each named button and request status without moving focus.
- Rapid taps, busy responses, offline POST, slow response, delivery uncertainty,
  reload recovery, storage denied/corrupt and browser back/reload never duplicate
  a command or silently use legacy GET.
- Cached legacy and flag-on clients select the same provider mapping. With live
  tests separately approved, have a human observe wake/Home/deep link and picture.

The wider Phase 3 accessibility redesign, favorites, recents and settings remain
deferred. These checks are release gates, not claims of completed device tests.

## Staged rollout (separate production approval required)

1. Inspect the actual deployment triggers and snapshot the current artifact,
   catalog and service configuration. Preserve HOME, .env and authorized ADB
   keys. No workflow exists under `.github` here; `deploy.sh` hard-resets and
   restarts and is not a verification command.
2. Release the compatibility reader/API with the tablet flag off. If staging
   historical artifacts, keep its pre-migration catalog until the reviewed
   migration step; the migrated catalog in this checkout is only locally approved.
3. Review a fresh production migration dry-run and verified backup, then obtain
   approval to apply to production. Do not copy the local backup over newer data.
4. Restart only with approval. Keep Gunicorn one worker/four threads; no preload
   dispatcher startup. Check `/health` and catalog/status GET without waking TV.
5. With separate live-device approval, test legacy pass-through and new launches,
   exact mappings and uncertainty. Enable `TABLET_API_ENABLED=true` only after
   API and target-iPad checks pass; this requires production configuration approval.
6. Check LAN operation independently of internet/tunnel availability. Do not
   expose the control API or ADB ports publicly. Authentication/edge changes are
   Phase 4 work and separately gated.

## Rollback and shutdown

With explicit operator approval, turn the tablet flag off and revalidate the
legacy grid; both routes remain implemented. For full rollback, restore the
previous artifact and its matching, reviewed catalog backup, then restart with
approval. Inspect intervening catalog changes before restoring. Never reset HOME,
ADB identity or .env. Do not automatically rollback data or resend unknown jobs.

PlaybackService.shutdown stops new admission and waits at most the configured
grace (default 5 seconds, maximum 15). A command still running at grace expiry
retains its reservation until it ends; it is never abandoned to admit another.
The lazy worker registers this hook with atexit. Forced process exit loses all
request evidence; old IDs return 404 after restart and nothing is replayed.
Ensure the process manager allows enough shutdown time for the intended grace.

Legacy usage counters are process-local aggregates available through
`app.extensions['playback_service'].legacy_usage()` for operator inspection.
They contain no identifiers and reset on restart. Aggregate/preserve operational
evidence across releases before considering retirement. Removal still needs a
separately approved task, two releases and 30 days without legitimate calls,
confirmed migrated iPads and a communicated date. No retirement is scheduled.

No commit, push, deployment, service restart, production catalog/configuration
change or live-TV verification was performed by this task.
