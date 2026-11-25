# Movie Magic Alexa: what the code does

For daily operation, start with the [current household runbook](movie-magic-operations.md).
The user deployed and verified this play-only integration on November 24, 2026:
all five requested titles and ambiguity choices worked on the real TV, as did
automatic `zach` selection and an ordinary subsequent launch. The household uses
Caddy TLS, loopback Nginx, direct GoDaddy A-record updates and an owner-restricted
development skill. No Cloudflare, Lambda or nameserver migration is required.
Alexa remains disabled by default in source for new installations. This document
explains the code and reconstruction steps; the [verification record](alexa-verification.md)
distinguishes tested behavior from remaining broader roadmap checks.

## Start with the conversation

Read [`alexa/skill.py`](../alexa/skill.py) first. The important function is
`handle_request()`. It follows these steps:

1. Read the intent: play a movie, choose a number, ask for help, or cancel.
2. For play, read the title and call `movies.resolve(title)`.
3. For several matches, say their names and return their keys as session choices.
4. For one match or a valid numbered choice, read the current catalog entry again.
5. Call `playback.submit_play(movie_key, principal, request_key)`.
6. Say that the request was sent. Do not claim the movie is playing.

Example: "Alexa, ask Movie Magic to play Luca" resolves to the permanent key
`luca`. The existing playback worker looks up its Disney+ ID and sends the same
wake/Home/deep-link commands as the iPad. The Alexa conversation never handles
Disney+ URLs or ADB commands.

For an ambiguous nickname, the reply lists at most three numbered titles. Alexa
returns the chosen number on the next request. The skill checks that the choices
are at most two minutes old and the selected movie still exists. It sends nothing
until there is one selection. More than three matches asks for a fuller title.
"Frozen" matches Frozen directly; Frozen II does not make it ambiguous.

## The three places you might edit

| Change | Where |
|---|---|
| Change Alexa's wording | The `HELP` constant and `reply()` calls in `alexa/skill.py` |
| Add a familiar nickname | The existing movie's `aliases` array in the catalog; keep its permanent key |
| Understand a rejected request | The checks in `alexa/web.py`; public errors omit account IDs and internal diagnostics |

After an approved catalog edit, re-export the voice model and rebuild the
development skill model. No silent catalog migration or automatic cloud update
happens. The backend validates the title even when Alexa suggests an old value.

The conversation uses plain dictionaries and functions. `alexa/web.py` is the
Flask entrance; `alexa/verification.py` is a separate security adapter. You do not
need to understand certificates to change spoken replies or title nicknames.
The adapter exists because Amazon's SDK otherwise downloads certificates without
a timeout and keeps an unbounded cache. We reuse its chain/SAN/signature checks.
We replace URL handling/fetch/cache with a fixed Amazon host, no redirects,
timeouts, a 64 KiB limit, at most eight certificates and four cached chains.

## Local verification (safe; fake TV only)

Use the project's intended Python. In this checkout it is `.venv/python.exe`.
The optional Alexa packages are in `requirements-alexa.txt`; ordinary disabled
Movie Magic does not import them. Installation is into a development virtualenv:

```powershell
.\.venv\python.exe -B -m pip install -r requirements.txt -r requirements-test.txt -r requirements-alexa.txt
$env:TEMP = Join-Path (Get-Location) '.venv\pytest-temp'
$env:TMP = $env:TEMP
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider
```

The signed-request tests create a temporary CA and signing key in memory, trust
that CA only in the test, and intercept certificate downloads. They test real
signature and chain validation without contacting Amazon or a TV. Missing optional
packages produce explicit skips; those are not verification of Alexa security.
The existing isolated loopback tests may require local-network permission on
Windows. Native Nginx tests skip if it is absent.

Generate the model locally, without starting Flask, refreshing posters, or writing
the catalog:

```powershell
.\.venv\python.exe -B tools/export_alexa_model.py --catalog movies.json --output alexa/interaction-model/en-US.json
```

The generated file contains movie keys, names, aliases and sample phrases only.
It includes Luca, Frozen, Tangled, Elemental and Robin Hood from the existing
catalog. Console build and actual Echo recognition remain release gates.

## The protected entrance

Proposed route: `https://movies-api.fradkin.net/alexa`. It only accepts JSON POSTs.
The Amazon signature authenticates the original body. The skill and skill-scoped
owner user ID must match both context and session. Browser cookies, local network
access, bearer tokens and forwarding headers do not substitute for these checks.
The endpoint issues no cookies and responses are not cached.

Each event's request ID produces a fixed repeat-protection key. Repeated delivery
uses the existing PlaybackService record and does not send another command within
its retention window. A backend restart loses those records; there is no durable
exactly-once guarantee. Failed/ambiguous commands are never automatically repeated.

Only one signature verification can be outstanding. Further requests fail quickly
rather than queueing. The verifier worker can only verify, never launch. The HTTP
handler waits at most four seconds for it. Slow DNS may keep that single worker
occupied after the caller times out; later callers receive unavailable until it
finishes. No extra threads are spawned, and late completion cannot launch a movie.
A stuck verifier may require an approved service restart. Normal cached requests
do not fetch certificates. Certificate chain validation does not fetch OCSP/CRLs
with the pinned library's default context; this preserves its default revocation
policy, not a guarantee of immediate certificate revocation detection.

## Reconstruction checklist for direct HTTPS

These steps describe building/reviewing an installation. The current household
status is in the runbook above; do not reinstall it merely to follow this list.

1. Confirm the production host's OS/Python and import/test the pinned optional
   dependencies in an isolated environment. The upstream SDK/chain libraries are
   old, emit deprecation warnings and have platform/OpenSSL compatibility risks.
   Windows verification here is not Linux verification. Do not enable if import,
   chain/signature tests or resource bounds fail on the actual Linux runtime.
2. Create a free Amazon Developer account using the Echo's Amazon login. Create
   a Custom skill in US English named Movie Magic; select an HTTPS endpoint, not
   Alexa-hosted or Lambda. Import `alexa/interaction-model/en-US.json` and build.
   Verify the invocation name and utterances in the developer console.
3. Obtain the skill ID and the owner `context.System.user.userId` from the
   console's request inspector. Do not use a voice profile/person ID. Keep those
   identifiers out of commits/logs. Configure them explicitly in protected local
   configuration; there is no automatic first-caller enrollment. Inspecting a
   failed development test's input does not require the backend to accept a launch.
4. Preserve the GoDaddy Builder website, Google mail and existing private
   movie-grid hostname. Use an A record for `movies-api.fradkin.net` pointing to
   the public WAN IPv4. The former CNAME to `fradkin-movies.tplinkdns.com` failed
   CAA lookups and was replaced. The [standalone DNS updater](alexa-dns-updates.md)
   now maintains only this A record. Registration and nameservers stay at GoDaddy.
5. Use Caddy's public ACME issuer for the new hostname, with HTTP-01 disabled so
   certificate issuance/renewal uses TLS-ALPN on TCP 443. Keep the old grid's
   internal certificate and restrict its direct peers to the home subnet. See
   `ops/caddy/Caddyfile.alexa.example` and its README. Do not expose the current
   unrestricted LAN Caddyfile by simply forwarding 443.
6. Install `ops/nginx/zmoviemagic-alexa.conf.example` only as a loopback 8082 guard,
   after reviewing/backing up enabled sites and removing only the approved default
   site symlink that would compete for Caddy's 80/443. Preserve the machine API's
   separate protection. Lint before service changes. Isolated native checks and
   subsequent user-reported activation passed; review the actual installed
   configuration before changing it rather than blindly replacing it from examples.
7. Before copying source, inspect the live checkout and service paths. The user
   reports base revision `73aba9b`, local edits to `deploy.sh` and `movies.json`,
   and an untracked `venv-before-ubuntu-upgrade/`. Preserve all three. A source
   patch must exclude those paths, real `.env`, virtualenvs and ADB credentials.
   Review its stat and run `git apply --check` before any approved application.
   Do not reset/pull over edits, run `deploy.sh`, commit or push as a shortcut.
8. During approved deployment, back up affected source/config files, install the
   reviewed patch and optional requirements, and test with Alexa still disabled.
   Use the separate test environment for the full Python tests in the `tests`
   directory, so the old virtualenv backup is not accidentally collected. Validate
   the current production catalog read-only; never replace it from this checkout.
9. Configure `ALEXA_SKILL_ID`, `ALEXA_USER_ID`, `ALEXA_ENABLED=true`, and the exact
   internal proxy Host in `ALLOWED_HOSTS` during an approved change/restart. Preserve
   the app's session secret, LAN subnet rules, one-worker setup and ADB identity.
   `REMOTE_API_ENABLED` may stay false. Debug must be off. Missing IDs abort startup.
10. With explicit approval, activate the reviewed Caddy/Nginx policies and open
    only TCP 443 to Caddy after local denial checks. Cover IPv4/IPv6 firewalls and
    validate external denials and public certificate trust/renewal. No app, ADB,
    Nginx guard or admin port is forwarded. Certbot and an inbound 80 forward are
    unnecessary with the selected Caddy challenge. Do not infer WAN reachability
    merely from matching IPs or DNS success.
11. Configure the verified HTTPS endpoint in the development skill, then perform
    denial cases and separately approved five-title Echo/TV checks. Confirm the
    Fire TV's actual current address first; the network migration may have changed
    it. Check LAN iPad use during WAN outage and record actual recognition/latency.
    No queued/command-sent response proves on-screen playback.

The development skill remains unpublished and usable on the owner's account.
Explicit backend skill/user checks are still required. Alexa/internet outages
should leave LAN iPad use working. Pause/resume/stop TV controls are not implemented.

## Rollback

Prepare protected copies of the previous app/config/proxy/DNS settings before
rollout. Remove the public router/firewall exposure and disable the development
skill before restoring the old unrestricted LAN Caddyfile. Then disable
`ALEXA_ENABLED` through an approved configuration change/restart. Restore the
previous artifact/config if needed; preserve catalog keys, iPad URL and ADB identity.
Do not replay unknown requests. DNS rollback must preserve website/mail records
and account for propagation. The user performed the recorded rollout manually;
the [operations guide](movie-magic-operations.md) describes the current result.

References: [Amazon HTTPS skill hosting](https://www.developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html),
[Python web-service verification](https://www.developer.amazon.com/en-US/docs/alexa/alexa-skills-kit-sdk-for-python/host-web-service.html),
and the [selected design](alexa-play-only-plan.md).
