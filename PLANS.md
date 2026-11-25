# ZMovieMagic v2 implementation plan

Architecture documentation, November 25, 2026: [current architecture](docs/architecture.md)
now describes the working household topology; [design decisions](docs/architecture-decisions.md)
records the reasons, alternatives and tradeoffs. The previous baseline/target
architecture body is preserved in [history](docs/architecture-history.md).
This documentation update changes no running configuration or application behavior.

Current household reference: [Movie Magic operations](docs/movie-magic-operations.md)
consolidates the working setup, maintenance, troubleshooting and recovery. Read
it before the historical planning updates below when operating the installed app.

Live follow-up completion, 2026-11-24: the user confirmed the narrowed firewall
with a fresh SSH connection, a successful GoDaddy DNS updater service and enabled
five-minute timer, and automatic selection of Disney+ profile `zach` followed by
actual playback. A subsequent ordinary launch past the picker also passed. The
profile source patch passed all 324 server tests (28 SDK warnings); the DNS tool
previously passed 43 tests in its separate Ubuntu check directory. See the
[live verification record](docs/alexa-verification.md). These complete the three
requested follow-ups, without claiming the unrelated broader roadmap gates.

Profile implementation follow-up, 2026-11-24: the user supplied a real Disney+
picker hierarchy and requested automatic selection of its no-PIN `zach` profile.
A default-off focused-card recognizer and bounded FireTVService helper are now
prepared locally, with mocked recognition/failure/serialization checks. Movie
launch, identity, grid and catalog contracts are preserved. See
[profile design/rollout](docs/disney-profile-selection.md). No profile update has
been installed on the server or tested on the live device yet.

Follow-up, 2026-11-24: the user confirmed live Alexa/TV playback for all five
requested titles and ambiguity selection, and then requested automatic DNS
updates, firewall cleanup and selection of the Disney+ profile `zach` when needed.
The user verified the narrowed UFW rules and a fresh SSH connection. A separate
standard-library GoDaddy A-record updater, mocked checks and timer templates are
prepared locally; the full suite passed 336 tests with two native Nginx skips.
See [DNS setup](docs/alexa-dns-updates.md) and [current live evidence](docs/alexa-verification.md).
Ubuntu updater verification, production installation/activation, live API access
and fixed-profile screen detection remain pending. Existing rollout statements
below are historical preparation notes, not evidence contradicting this update.

Connectivity follow-up, 2026-11-24: the user is pursuing direct HTTPS with GoDaddy
DNS and Deco DDNS. Their existing Caddy 2.6.2 already owns 80/443 and has a LAN
site proxying to Flask with an internal certificate. A separate proposed Caddy
policy now restricts that site to home peers and exposes only the signed Alexa
URI through the loopback Nginx guard, with TLS-ALPN certificate validation on 443.
The proposal has nine isolated local native checks; user-host validation, package
maintenance review and explicit production/publication approval remain pending.
See [Caddy notes](ops/caddy/README.md) and [verification](docs/alexa-verification.md).
No Caddy reload, port forwarding or live TV command was performed by the agent.

Implementation update, 2026-11-22: the user separately requested implementation of
the selected local play-only Alexa design. The default-off Flask endpoint,
conversation, bounded SDK verification adapter, model/export tool and isolated
tests are implemented. See the [code/setup walkthrough](docs/alexa-setup.md) and
[verification record](docs/alexa-verification.md). Accounts, Linux dependency
validation, native proxy/tunnel checks, DNS/edge setup, user code walkthrough and
real Echo/iPad/TV acceptance remain pending. This is not full M5 completion or
production rollout authorization.

Planning update, 2026-11-22: a [play-only Alexa first release](docs/alexa-play-only-plan.md)
is being designed with the user. It reuses catalog resolution and launch services,
defers media controls, and makes a user-readable Python walkthrough an acceptance
gate. The user confirmed own-account devices, en-US, five catalog test titles,
existing `fradkin.net` ownership and a preference for no or very low extra costs.
The user selected local Flask hosting through Cloudflare, replacing the proposed
Lambda path for this release. Direct Amazon request verification and a dedicated
edge route are specified in the draft; AWS and a new resolver API are unnecessary.
GoDaddy manages both domain registration and DNS, and both website and email use
the domain. Preserve both services before any proposed DNS changes.
Target extra subscription cost is $0, subject to edge-plan checks.
That planning update authorized no deployment; the broader M5 backlog remains pending.

Status update, 2026-11-07: the user separately approved local Phase 2
implementation, the 44-key manifest and local additive catalog migration.
See [the implementation/release runbook](docs/phase-2-runbook.md). Production
rollout and target-device release gates remain pending. The user subsequently
requested local Phase 3 implementation: P3.1–P3.3 and caregiver settings are now
implemented; P3.4 target-device usability verification remains pending. See
[tablet verification](docs/tablet-verification.md). The user subsequently approved
local P4.1–P4.3 implementation: authentication, LAN sessions/CSRF, bounded quotas,
remote aliases and connectivity templates are implemented. Native proxy/tunnel
validation and approved staging remain pending; see
[Phase 4 verification](docs/phase-4-verification.md) and the
[security runbook](docs/security-runbook.md). P4.4 and Phases 5–6 remain pending;
this document does not authorize deployment or production changes.

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
