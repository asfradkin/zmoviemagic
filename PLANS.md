# ZMovieMagic v2 implementation plan

Status update, 2026-11-07: the user separately approved local Phase 2
implementation, the 44-key manifest and local additive catalog migration.
See [the implementation/release runbook](docs/phase-2-runbook.md). Production
rollout and target-device release gates remain pending. Later phases remain
specifications only; this document does not authorize deployment or production changes.

## Baseline and roadmap

Phase 1 is the existing Flask/service/ADB application. The current working tree is
the authority for implementation; see [architecture](docs/architecture.md) for the
verified baseline and gaps. Existing README operational instructions remain in
place. Its claimed GitHub deployment workflow was not present under `.github`
during inspection; determine actual deployment triggers before any push.

| Milestone | Deliverable | Exit gate |
|---|---|---|
| M2 | Stable catalog and playback API alongside legacy UI | Catalog round trip, API contracts, legacy tests, concurrency tests |
| M3 | Accessible tablet UI | Safari/VoiceOver, accidental-touch and outage recovery checks |
| M4 | Authenticated remote API | Edge and origin denial tests; LAN iPad unaffected |
| M5 | Private Alexa skill and controls | Resolution, utterance tests, target-device control validation |
| M6 | Shared personalization and resilience | Atomic persistence, recovery, optional HA contract tests |

## Dependency-ordered implementation backlog

Each row is an independently reviewable task. Complete automated tests and the
listed gate before its dependent task. All file names below describe future work.

| ID | Task and main files | Depends on | Verification / completion |
|---|---|---|---|
| P2.1 | Catalog validation, immutable key manifest, normalization and resolver in `services/movie_service.py`; movie tests | Phase 1 | All 44 entries preserved; duplicate keys rejected; ambiguous aliases explicit |
| P2.2 | Dry-run migration tool `tools/migrate_catalog.py`, key manifest, compatibility reader | P2.1 | Legacy/new round trips; repeat run unchanged; failure preserves original |
| P2.3 | Shared command admission, one background dispatcher, status/idempotency in `services/playback_service.py` | P2.1 | Legacy/API requests cannot overlap; timeouts never silently replayed |
| P2.4 | `/api/movies`, `/api/play`, `/api/status` in `app.py` and API tests | P2.2, P2.3 | Error matrix; no provider IDs; queued versus delivered explicit |
| P2.5 | Staged iPad migration in `templates/index.html` | P2.4 | Old/new clients launch identical IDs; no POST-to-GET automatic retry |
| P2.6 | Migration/rollback runbook and release verification | P2.5 | Local checks pass; production verification approval gated |
| P3.1 | Semantic poster cards, responsive CSS, local fallback assets | P2.5 | Touch targets, keyboard, contrast, 200% zoom, orientations |
| P3.2 | Feedback and request state machine in `static/tablet.js` | P3.1 | Offline/timeout/busy/reload and repeated taps tested |
| P3.3 | Tablet-local favorites and recent launch requests using stable keys | P3.2 | Storage denied/corrupt fallback; favorites never launch |
| P3.4 | Target-iPad usability checks and caregiver settings | P3.3 | Accessibility and accidental-touch checklist recorded |
| P4.1 | Backend bearer scopes, LAN session/CSRF, redaction, rate limits | P2.4 | Auth/forged-header tests; legacy LAN retained |
| P4.2 | Remote route prefix and loopback proxy allowlist templates | P4.1 | Remote UI, legacy, health and administration denied |
| P4.3 | Tunnel/Access templates and rotation runbook | P4.2 | Offline lint; approved staging test of both auth boundaries |
| P4.4 | Approved production connectivity verification and rollback rehearsal | P4.3, P3.4 | HTTPS works; no inbound forwarding; LAN works without tunnel |
| P5.1 | Backend `/api/resolve`, `/api/control`, capability flags, fixed key events | P2.4, P4.1 | Resolution contract; shared lock; unsupported controls fail closed |
| P5.2 | Target-device pause/resume/stop feasibility test | P5.1 | Live-TV approval; behavior recorded per version |
| P5.3 | Interaction model and deterministic slot export tool | P5.1 | Alias/ambiguity fixtures; no provider IDs in skill artifacts |
| P5.4 | Lambda handler/client, secrets, idempotency, bounded HTTP | P5.3, P4.3 | Mock events; duplicate delivery; edge HTML/outage tests |
| P5.5 | Private skill end-to-end verification and rollback notes | P5.2, P5.4, P4.4 | Echo invocation/all controls work; truthful speech |
| P6.1 | Atomic JSON state repository and migration tools | P2.2 | Parallel writes, crash windows, corrupt/readonly recovery |
| P6.2 | Favorites/recent APIs and command-delivery recording | P6.1, P2.3, P4.1 | No queued/failed/uncertain history; duplicate jobs deduplicated |
| P6.3 | Tablet local-to-household import and server sync | P6.2, P3.3 | Explicit import, conflicts, offline behavior, local rollback |
| P6.4 | Readiness, non-waking dependency status, recovery policy | P6.1, P5.1 | Circuit/cooldown tests; stale connectivity; restart unknown |
| P6.5 | Optional Home Assistant templates/tests | P6.2, P6.4, P5.1 | Scoped credential; HA outage does not affect iPad |
| P6.6 | Approved release verification and restore rehearsal | P6.3, P6.4 | Backup/restore, LAN/Alexa regression; HA optional |

P6.1/P6.2 may follow M4 before M5 if shared favorites are more valuable than voice
control. M3 deliberately offers device-local favorites first. Alexa controls are a
backend-first extension in P5.1, never Lambda-owned ADB operations.

## Common release gates

1. Inspect working tree, deployment triggers, and relevant specification.
2. Implement one task with targeted tests and the full existing pytest suite.
3. Review compatibility, security, and migration dry-run output.
4. Prepare release artifact, backup, rollback commands; obtain approval before
   changing production configuration, services, catalog, TV or DNS.
5. Verify health, old iPad launch, new API status and phase-specific gates. On
   failure restore previous artifact and matching data backup; preserve ADB keys.

## Decisions and constraints

- One household, one Fire TV, one backend process; no accounts or database.
- New HTTP requests are asynchronous so Alexa need not wait for ADB. The in-memory
  dispatcher is intentionally not a durable queue.
- No route retirement in Phase 2. Legacy removal needs a separate approved task
  after at least two releases and 30 days without legitimate legacy usage, with
  operator log review and confirmation that every iPad has migrated.
- Phase 6 preferences are household-wide, not child/voice profiles.
- Domain availability, target iPad OS, title aliases, invocation name and actual
  Fire OS/Disney+ control behavior require operator/device validation.
- Deployment procedures describe future approved work, not actions performed here.

## Planning verification

The initial specification review could not run pytest. The subsequent approved
implementation established a green baseline: all 26 original tests passed using
`.venv/python.exe`. See the runbook for expanded test results and remaining
browser/device release gates. Do not assume `Scripts/python.exe` exists here.
