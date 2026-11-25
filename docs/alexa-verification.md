# Local play-only Alexa verification — 2026-11-22

## Completed follow-ups — user-reported live results, 2026-11-24

The user applied the reviewed seven-file profile patch after a silent server
`git apply --check` and source-backup instructions. Their full Ubuntu suite
passed **324 tests, 28 upstream SDK warnings in 14.51s**. This server test count
does not include the 43 DNS updater cases previously run in the separate DNS
check directory; the local Windows source suite includes both sets.

After setting `DISNEY_PROFILE_NAME=zach` and following validation/restart
instructions, the user confirmed that a picker-interrupted Alexa request
automatically selected `zach` and played the requested movie. They then confirmed
an ordinary request while already past the picker also worked. These are
user-reported actual selection/playback results, not deductions from ADB replies.

The three requested operational follow-ups are now in place: narrowed UFW rules
with a new SSH connection verified, a successful GoDaddy updater run and enabled
five-minute timer, and guarded profile selection with both live launch cases
passed. A real WAN-IP change, certificate-renewal cycle, token replacement and
broader historical release gates have not been newly exercised by these checks.
No commit, push or deploy.sh run was performed by the agent.

Earlier entries below retain preparation history; their pending statements are
superseded where the subsequent live evidence above establishes completion.

## User-reported live acceptance — 2026-11-24

The user activated the reviewed loopback Nginx guard and Caddy configuration.
Public certificate issuance initially failed through the TP-Link DDNS CNAME:
CAA queries returned SERVFAIL for that target. Replacing only the dedicated
`movies-api.fradkin.net` CNAME with an A record resolved this blocker. A local
HTTPS check without certificate bypass returned 404 for `/`; a POST to `/alexa`
reached Flask while the feature was disabled. Automatic A-record updates remain
to be configured; the original CNAME approach is no longer the active plan.

The development manifest initially contained empty `apis.custom.locales` despite
a retrievable en-US model. The user added `en-US: {}`, submitted the retrieved
model through ASK CLI, and confirmed its build succeeded. Invocation subsequently
produced request JSON. These observations do not establish which individual
change resolved Amazon's earlier device-support message. ASK CLI 2.30.7 is in a
separate server diagnostic directory. Its credentials must remain outside source.

The user configured the exact skill and owner IDs privately, appended the fixed
internal proxy host, passed configuration validation, and restarted the service.
The skill's opening response worked. The user then confirmed actual TV playback
for Luca, Frozen, Elemental, Robin Hood and Tangled, plus numbered ambiguity
selection. The original `movie magic` invocation name was restored and worked.
This is user-reported on-screen evidence, beyond command-submission speech.

Remaining follow-ups are automatic DNS updates, review of broad/obsolete UFW
rules without losing SSH or LAN access, and optional selection of one Disney+
profile when its picker interrupts startup. The user wants automatic selection
of the exact profile `zach`, reports that it has no PIN, and confirms the original
requested movie starts after selecting it manually. No profile automation is
implemented; selecting the profile should not send the movie launch again. Any
future implementation must identify the picker before acting, preserve command
serialization and bounds, and avoid blind confirmation presses or automatic
replay of an ambiguously delivered movie launch. IPv6 exposure, external denial
coverage, certificate renewal, rollback and the earlier iPad checks are not
established merely by these successful movie tests.

Firewall follow-up: the user removed the broad 5000/22/8000 rules, both old
192.168.86.x rules, and the redundant single-client 8000 rule. Their resulting UFW
listing allows SSH only from the reserved admin IPv4 on Wi-Fi, port 8000 from
192.168.68.0/22 on Wi-Fi, and public TCP 443 on Wi-Fi for IPv4/IPv6. Existing UDP
5353 discovery rules remain. The user confirmed a second SSH connection worked.
This is host-rule evidence, not an independent external IPv6 port scan.

DNS follow-up: the user created a private GoDaddy PAT for the requested updater.
The new standalone standard-library tool, mocked tests and systemd examples are
prepared locally; see [DNS setup](alexa-dns-updates.md). Local full regression:
336 passed, 2 native Nginx skips, 25 SDK warnings. No actual token was read by the
agent, no live API request was made and no updater/timer was installed or enabled.

Subsequent DNS activation evidence: the user ran all 43 updater tests on Ubuntu
successfully, stored the token privately, and supplied a successful read-only
live check reporting the existing A record already current. They installed the
tested standalone script and systemd units. Unit verification produced only an
unrelated distribution `system-xfs_scrub.slice` CPUAccounting warning. The first
service run reported `Result=success` and `ExecMainStatus=0`; the timer is enabled,
`active (waiting)`, and shows a next trigger roughly five minutes ahead. This
confirms successful live API reads and scheduling. No changed-IP write, real
WAN-change recovery or future token replacement is established by this evidence.

Profile source follow-up: the supplied XML exposes a unique enabled profile
description directly inside its focused actionable card on the recognized Disney+
picker. The local recognizer accepts the real capture. A default-off helper now
sends only a single Select after that fresh match, bounded and serialized with
launches; it never navigates to another card or repeats the movie launch. All 29
new profile tests passed in the full Windows regression (365 passed, 2 native
Nginx skips, 25 SDK warnings). See [profile rollout](disney-profile-selection.md).
This is prepared source, not an installed/live-verified profile feature.

The entries below retain the earlier preparation and isolated-test history;
their pending rollout statements are superseded only by the evidence above.

Live-checkout source follow-up: the user reported base revision `73aba9b`, local
edits only to `deploy.sh` and `movies.json`, and an untracked old virtualenv backup.
The 30-file reviewed source patch excludes those paths, the real `.env`, virtualenvs
and ADB identity. Its check passed silently on the server. After the backup/apply
instructions, the user supplied the complete run from `~/zmoviemagic` using the
separate check environment: **295 passed, 28 warnings in 14.24s**. All native
checks ran; no skips were reported. This verifies the patched source on Ubuntu
under the check environment's dependencies, not service activation or public TLS.
Backup existence/content has not been independently inspected. The actual app
virtualenv's optional dependency installation and verifier import check are next;
no restart or external publication is inferred from these tests.

Application-runtime follow-up: the user supplied `Application verifier ready`
from `./venv/bin/python -B -c` importing and constructing `alexa.verification.AmazonVerifier`
inside the actual app checkout. This confirms that import in the application
environment. The pip installation/check output was not supplied, so no independent
pip-check result is asserted. Next is the reviewed loopback-only Nginx guard:
back up `/etc/nginx`, install the example, replace only the previously verified
default enabled-site symlink, lint, and start/restart Nginx with only port 8082 on
loopback. Caddy retains 80/443. Keep the application feature disabled and public
router/firewall access closed until the remaining identity/proxy/TLS gates pass.

Private Nginx activation follow-up: the user supplied `ss` output showing Nginx
listening only on `127.0.0.1:8082` and a curl request for `/` with the intended
public Host returning **404**. This establishes the private listener/root denial
in the active proxy, not full external publication or the signed backend route.
Next is backing up the active Caddyfile and validating the reviewed example as
`/etc/caddy/Caddyfile.alexa-candidate` before replacing/reloading the active file.
The active Caddyfile must restrict the old LAN site before any router forwarding.

Follow-up, 2026-11-24: the user reports Ubuntu 26.04.1 LTS, Python 3.14.4
in the app virtualenv, and OpenSSL 3.5.5. In a separate
`~/moviemagic-alexa-check` virtualenv, the pinned verifier imports and constructs
successfully. The user then supplied the complete isolated Ubuntu test output:
**82 passed, 25 warnings in 2.66s**, using the three selected Alexa suites. This
establishes those mocked signed-request/chain/conversation/transport checks on
the reported Linux environment, not full production rollout or real Alexa/TV
operation. The user subsequently supplied the native Nginx test result:
**1 passed, 3 warnings in 1.20s** for
`test_native_alexa_proxy_denials_and_signature_transport`. This verifies isolated
loopback proxy lint, exact-route denials and signed-header forwarding on that host.
It does not verify a public TLS endpoint or live app. TLS/public-network and full
Linux regression checks remain pending. The user is pursuing direct HTTPS through GoDaddy DNS and Deco;
the earlier Cloudflare deployment steps/templates are not a direct-HTTPS config.

Public DNS preparation: the user registered `fradkin-movies.tplinkdns.com` in Deco
and added the GoDaddy CNAME `movies-api.fradkin.net` pointing to it. A read-only
lookup through resolver 1.1.1.1 confirmed that CNAME and that both hostnames resolve
to the same IPv4. The restricted environment's default loopback resolver timed
out; the explicit public-resolver lookup succeeded. This is DNS evidence only,
not incoming HTTPS reachability or a TLS validation result. No public control
endpoint, port forwarding or certificate issuance has been verified yet.

Superseded proposal: standard Nginx plus Certbot webroot HTTP-01. This would
require inbound TCP 80 for an exact ACME challenge-only location, in addition to
TCP 443 for the authenticated Alexa route. It revises the earlier 443-only outline
and must be explained/reviewed before any firewall/router publication. Existing
Nginx enabled sites and port listeners need a read-only check before preparing
the actual configuration. Prefer automatic renewal; manual recurring TXT updates
are not the default plan. No certificate private key or ACME account file should
be requested or copied into source control.

Listener discovery: the user's read-only output shows Caddy already listening on
both `*:80` and `*:443`. Nginx has only the default enabled-site symlink; the
system Nginx service's status/configuration is not established by the isolated
test. Do not stop Caddy, overwrite its configuration, or make Nginx compete for
those ports. First obtain Caddy's version/configuration path and review its
existing routes without disclosing embedded credentials. In particular, no port
forwarding may proceed on the assumption that other Caddy sites cannot expose
the local UI or legacy controls through a loopback origin.

Candidate adaptation: use existing Caddy for public TLS/certificate renewal and
the tested Nginx restrictions on loopback 8082, then the signed Flask endpoint.
This may remove the need for Certbot. The configuration, certificate challenge
method, interaction with current Caddy sites, and rollback still require review;
no service or listener change was performed by the agent.

The user supplied Caddy 2.6.2's configuration: `moviemagic.fradkin.net` with
`tls internal` and an unrestricted loopback proxy to Flask. A separate reviewed
example and tests now live under `ops/caddy/` and `tests/test_alexa_caddy.py`.
An official Windows Caddy 2.6.2 binary was downloaded into ignored test output and
verified against the release's SHA512 manifest; it was not installed as a service.
An initial check mistakenly compared SHA256 against that SHA512 manifest, failed
closed, and extracted/executed nothing. The corrected SHA512 check passed.

Native isolated checks with that binary: **9 passed in 9.14s**. The real template
adapts successfully with separate internal-LAN and public-ACME issuer policies;
HTTP-01 is disabled for the public issuer. The disposable loopback tests confirm
normalization/query/method denials, body/signature/Host forwarding, oversized-body
rejection and no LAN bypass via forwarded identity. Initial assertions expected
413 for an oversized streaming request, while 2.6.2 returns 502; the corrected
assertion requires rejection and no processed upstream body. Those initial two
failures are not counted as passing checks.

The intended public path is Caddy TLS -> Nginx loopback guard -> signed Flask
endpoint, with only TCP 443 forwarded after approval and public validation.
No actual Caddy certificate, reload, upgrade, firewall or router change has been
performed by the agent. The updated policy still needs an isolated native run on
the user's Linux Caddy and a supported-package review before publication. See
the [Caddy preparation/rollback notes](../ops/caddy/README.md).

Full local regression after adding the Caddy policy: **293 passed, 2 skipped,
25 warnings in 24.89s**, using the required pytest command with the verified test
binary on PATH and reviewed loopback access. The two native Nginx checks still
skip on this Windows host, while the user's separate Linux Nginx result above
is a pass. An initial collection attempt found the temporary extracted source
copy from the earlier bundle smoke check, causing duplicate `tests.conftest`
imports. That explicitly verified temporary extraction was removed and the full
run then passed; no project source or test ZIP was removed. Scanner: zero findings;
`git diff --check` passed with informational newline-conversion warnings.

`test-results/alexa-caddy-check.zip` contains only the Caddy example, its README,
the native test and a SHA256 manifest, under the existing sandbox's source prefix.
It contains no binary, credentials, catalog or active service configuration.
Linux policy checks, service status and package-candidate inspection remain pending.

User-host Caddy follow-up: the supplied Ubuntu run of `tests/test_alexa_caddy.py`
reports **9 passed in 5.47s**. `systemctl is-active caddy` reports `active`.
The configured Ubuntu resolute/universe repository lists installed and candidate
package `2.6.2-14`; this records package availability, not a general security
support assertion. No package upgrade or production Caddyfile reload was requested
or performed by the agent. The isolated Caddy policy gate on that host is now
passed; public TLS issuance, external denial tests and actual app deployment remain
pending. Before preparing the live source update, obtain the Ubuntu checkout's
revision/working-tree status and service paths so user source/configuration edits
can be preserved. Do not deploy the test sandbox as the production application.

An isolated bundle, `test-results/alexa-ubuntu-check.zip`, contains 31 allowlisted
source/support files plus a SHA256 manifest. It excludes real `.env`, catalog,
credentials and deployment/restart scripts. Its extracted copy passed **82 Alexa
tests, 25 upstream warnings in 7.72s** with the local Windows Python 3.12; this
does not establish Python 3.14/Linux success. The bundle also includes the optional
native Alexa proxy test for a later isolated run when Nginx is available. It is
an ignored local test artifact, not an application deployment package.

Run only the three selected `test_alexa_skill.py`, `test_alexa_web.py` and
`test_alexa_transport.py` suites initially in the separate Ubuntu test environment.
Install the bundled runtime/test/Alexa requirements there, not into the live app
virtualenv. Certificates, catalog and TV calls are synthetic/mocked. No port
forwarding, service restart, production environment read or real-TV command is
needed for these tests. The supplied output shows Flask 3.1.3, pytest 9.2.0,
cryptography 46.0.7, certvalidator 0.11.1 and oscrypto 1.3.0, among the installed
test dependencies. The warnings are upstream datetime API deprecations; assertions
passed and no warnings were suppressed. Nginx is now available on the user's host
and its isolated test passed. Next: DDNS/public hostname preparation, then a
separately reviewed direct HTTPS certificate/proxy configuration. The existing 8082 proxy
template is loopback-only, not a complete direct public HTTPS configuration.

User separately requested implementation after selecting local Flask hosting,
Cloudflare connectivity and readable Python. The feature remains disabled by
default. No commit, push, deployment, DNS/tunnel/service change, account creation
or live-device command was performed.

## Observed automated results

Intended interpreter: `.venv/python.exe`, Python 3.12. TEMP/TMP were directed to
the ignored `.venv/pytest-temp` directory. Required full command:

```text
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider --tb=short
284 passed, 2 skipped, 25 warnings in 15.10s
```

The two skipped checks are native machine-API and Alexa Nginx lint/HTTP tests,
because Nginx is not installed. cloudflared is also absent; no native ingress
validation is claimed. The 25 warnings come from upstream SDK naive-datetime
usage deprecated by Python/cryptography; they do not indicate failed assertions.
Pinned dependency compatibility and signed-chain tests must pass on the actual
Linux runtime before enabling the feature. No Linux compatibility claim is made.

Before adding Alexa tests, the existing suite passed **202 tests, 1 skipped** with
the feature disabled. Its initial restricted run had **200 passed, 2 failed,
1 skipped** because Windows blocked the existing isolated loopback sockets.
Passing full runs used reviewed execution with loopback access. None of these
tests uses real ADB, Alexa, TMDB, AWS or production services.

`python -B tools/scan_secrets.py` reported **0 findings** without opening live
secret files. `git diff --check` passed with informational LF/CRLF warnings.
`python -B -m pip check` reported no broken requirements. Alexa packages were
installed only into this checkout's development virtualenv; the optional runtime
requirements are recorded in `requirements-alexa.txt`. No production dependencies
were installed. Tests also prove disabled settings do not import optional verifier
packages.

## What the new checks establish

- Luca, Frozen, Tangled, Elemental and Robin Hood submit the expected permanent
  keys to the existing playback service, with a fake Fire TV. Frozen II remains
  separate. Unknown titles cause no command; reprompting is bounded.
- Ambiguities require a numbered selection. Invalid/expired choices, removed
  catalog keys and more than three matches never silently choose a movie.
- Help/cancel/stop/session-end never send a device command. Replies distinguish
  request acceptance from actual playback. A simulated lost admission response
  does not trigger another submission.
- Alexa duplicates reuse PlaybackService idempotency. Active Alexa launches and
  legacy requests share the existing reservation; existing tablet/dispatcher
  regression tests also pass. No changes were made to FireTVService commands,
  catalog data, immutable keys, worker configuration or UI assets.
- A synthetic test CA and leaf key are generated in memory; only that CA is
  trusted in signed fixture tests. Actual SDK signature/chain validation accepts
  a matching body and rejects altered bodies, invalid signatures, untrusted roots,
  wrong signing domains and expired certificates. Downloads are mocked.
- Correctly signed requests from the wrong skill/user, including conflicting
  session/context identities, cannot launch. LAN/Bearer/cookie trust does not
  replace verification. Remote APIs retain their disabled/authenticated boundary.
- Timestamp checks cover the exact plus/minus 150-second boundaries and nearby
  failures. Malformed, duplicate-field, oversized and nonstandard JSON, invalid
  certificate URLs and alternate request paths are rejected before side effects.
- The verifier rejects redirects and oversized/overlong chains, bounds inactivity
  and wall-time waits, caps/expires its cache, and permits only one outstanding
  verification. A timed-out verification cannot later launch; saturation rejects
  promptly rather than creating new threads or queued verification jobs.
- Proxy raw-URI and configuration invariant tests pass. The generated voice model
  is deterministic and contains only public names/keys/aliases; the export does
  not rewrite the catalog or refresh posters.

## Remaining release gates

The upstream verifier uses old chain dependencies. Validate import and real
signed-fixture verification against the actual production Python/OpenSSL/platform
in an isolated environment first; failure must block enabling Alexa. SDK
deprecation warnings are recorded rather than suppressed.

Run native proxy/tunnel tests and validate the concrete Cloudflare free-plan edge
policy. The new direct Amazon endpoint cannot use Access service-token headers;
approve its exact method/path protections and backend verification without
weakening any existing machine API protection. No actual edge denial, DNS,
firewall, external-port or TLS certificate checks were performed.

Review the code with the user: they must be able to trace success and clarification,
change a reply and understand aliases. Verify console model build, expected skill
and owner IDs, and actual Echo recognition. These are not established by pytest.
Perform the pending household iPad/Safari checks and separately approved real-TV
wake/Home/deep-link checks. Do not claim confirmed playback from command delivery.

Before DNS changes, export/review the existing GoDaddy records and preserve the
website, email and DNSSEC configuration. Account setup, DNS/tunnel publication,
service restart, deployment and live-device verification require explicit user
approval. The [setup guide](alexa-setup.md) describes the proposed sequence and
rollback, not an executed rollout.
