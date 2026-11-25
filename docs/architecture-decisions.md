# Movie Magic: design decisions and reasons

Recorded **November 25, 2026**. These are the choices made during this household
rollout and the reasons discussed or established by the implementation. The
[current architecture](architecture.md) shows what runs where; the
[operations guide](movie-magic-operations.md) explains how to maintain it.

Some ideas were considered and superseded. "Not selected" below means they were
not needed for this release, not that they are universally bad or cannot work.
Where troubleshooting did not isolate a single cause, the uncertainty is recorded.

| Main choice | Reason in one sentence |
|---|---|
| Local Flask/Python | Reuse one understandable codebase and the working TV services |
| Caddy | It already owned HTTPS and the LAN certificate, and automates public TLS |
| Private Nginx guard | Preserve the reviewed path/header/rate/time controls behind Caddy |
| Direct HTTPS | Fit the working Deco/WOW connection without moving the domain's DNS |
| GoDaddy A-record updater | Remove the observed DDNS CAA failure while handling future WAN-IP changes |
| One Gunicorn worker | Preserve one shared command reservation and in-memory repeat history |
| Separate LAN/public hostnames | Keep the grid and legacy controls private while exposing the skill entrance |
| Focused profile recognition | Select the intended profile without blind confirmation or relaunching |
| Staged patches/tests | Preserve existing household data, credentials and working behavior |

## 1. Keep the existing app and make the Python understandable

**Decision:** extend the existing Flask app factory and service boundaries.
Use plain conversation functions/dictionaries and preserve the local movie grid.

**Why:** the user wants to understand and maintain the code. A working laptop,
catalog and Fire TV launch path already existed. Reusing them avoids a second
catalog, duplicated launch logic or a framework migration. MovieService resolves
titles, PlaybackService coordinates commands, and FireTVService owns ADB.

**Tradeoff:** some safety/verification plumbing is more detailed than the spoken
conversation itself. It is isolated so changing wording or aliases does not
require understanding certificates, network transport or UI parsing.

## 2. Start with a play-only custom Alexa skill

**Decision:** use a custom skill with `movie magic`, English (US), and one-sentence
requests such as "Alexa, ask Movie Magic to play Luca." Keep it in development
for the owner's account and independently enforce that owner in the backend.

**Why:** native Alexa/Disney+ title launching did not satisfy the desired workflow.
The existing catalog could provide the exact launch mapping. One sentence is easy
to use, and play-only scope avoids adding unverified pause/resume/stop behavior.

**Tradeoff:** the invocation includes "ask Movie Magic"; this is not a native
Disney+ Video Skill or interception of every "Alexa, play" request. Public-store
publication, account linking and support for other owners were not required.
Development availability alone is not the application's authentication mechanism.

## 3. Ask for clarification instead of guessing

**Decision:** one exact title/alias can submit immediately; up to three matches
produce numbered choices. More matches require a more specific title.

**Why:** accidentally starting the wrong movie would undermine a simple interface.
Permanent keys keep title changes separate from provider IDs and voice aliases.
Recheck the selected catalog entry before launching rather than trusting stale
session choices. Existing valid legacy IDs still pass through for compatibility.

**Tradeoff:** some requests require a second spoken turn. The code intentionally
does not silently use spelling similarity to choose among ambiguous titles.

## 4. Host the skill in local Python instead of Lambda

**Decision:** Amazon calls a verified HTTPS endpoint on the existing Flask app.
The Alexa conversation calls existing service objects directly.

**Why:** this keeps one codebase, catalog and command coordinator. Lambda would
add another deployment/runtime, credentials/configuration and a remote call back
to the laptop, without removing the need for secure laptop connectivity. The
user preferred no extra cost and few accounts/services. Amazon supports custom
skills hosted as HTTPS web services. [Amazon hosting documentation](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html)

**Tradeoff:** the laptop must be on and internet-reachable for Alexa. This does not
make speech recognition local or offline: Amazon still interprets the utterance.
ASK CLI was installed for diagnosis; its accidentally configured AWS credentials
are not used by this architecture, and no AWS deployment was performed here.

## 5. Keep one Gunicorn worker and the current JSON catalog

**Decision:** one worker/four threads; bounded in-process coordination and JSON
storage. Do not add Redis, a database, a broker or multiple workers for this use.

**Why:** one household TV needs serialized actions, not more simultaneous device
commands. Multiple workers would each have independent locks and repeat records.
The current app is small enough that a shared-state infrastructure change adds
more maintenance than benefit. Preserve catalog keys and existing entries.

**Tradeoff:** restarts lose job/idempotency history. There is no durable exactly-once
guarantee. Scaling or durable recovery would need a justified shared-state design,
not just changing Gunicorn's worker count.

## 6. Use direct HTTPS through Deco and retain GoDaddy DNS

**Decision:** forward only TCP 443 to the Ubuntu laptop and keep registration and
authoritative DNS at GoDaddy. Use a separate public hostname for Alexa.

**Why:** the user questioned moving DNS because the domain also serves a GoDaddy
Builder website and Google/Gmail email. Direct HTTPS fit the available Deco/WOW
connection and avoided a DNS-provider migration for this release. Initial matching
WAN/public IPs supported investigating this path; later certificate issuance and
actual Alexa calls established that it worked.

**Alternative:** Cloudflare Tunnel/Access was proposed and initially selected,
then superseded. A tunnel would avoid opening an inbound router port and could
be reconsidered if WAN conditions change. The proposal's DNS/account/edge setup
was unnecessary once direct HTTPS worked. This is not a claim that every possible
Cloudflare arrangement requires migrating every domain record.

**Tradeoff:** the household now maintains a narrow internet-facing HTTPS service,
router forward, certificates and dynamic DNS. A future ISP/NAT change can require
revisiting connectivity. Local grid access remains a separate path.

## 7. Reuse Caddy for TLS rather than replacing it with Nginx/Certbot

**Decision:** keep Caddy as the HTTPS entry point and certificate manager.

**Why Caddy here:** it was already running, owned ports 80/443 and served the
private movie hostname with an internal certificate. Replacing it would create
port conflicts or require migrating a working LAN setup and its trust material.
Its configuration could preserve that site and add the dedicated Alexa site.
Caddy automates obtaining and renewing managed certificates. [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)

**Alternative:** the earlier Nginx-plus-Certbot/webroot proposal would have added
a separate certificate tool and HTTP-01 challenge setup. Discovery of the active
Caddy service made reuse the smaller change. Nginx can serve HTTPS, so this was
a fit-with-existing-installation choice, not a claim that only Caddy can do it.

**Tradeoff:** Caddy remains another service to maintain. Syntax tests and the
recorded distro version do not by themselves establish long-term security support.
Retain its storage/internal CA and review updates during planned maintenance.

## 8. Use public validation on TCP 443; keep private certificates private

**Decision:** the new public hostname uses a publicly trusted certificate through
TLS-ALPN-01 on 443, with HTTP-01 disabled. The old LAN hostname retains `tls internal`.

**Why:** Amazon needs a trusted HTTPS endpoint, while the existing LAN name points
to a private address and already has its own trust arrangement. Using 443 for
certificate validation avoids another public router forward and a separate
Certbot renewal job. [Caddy challenge documentation](https://caddyserver.com/docs/automatic-https#acme-challenges)

**Tradeoff:** public renewal still depends on reachable 443 and correct DNS/CAA
behavior. Initial issuance and trust were observed; a full renewal cycle was not.
Replacing the old private site's certificate is not necessary for the Alexa site.

## 9. Retain Nginx as a private, tested request guard

**Decision:** Caddy routes the exact public Alexa request to Nginx on
`127.0.0.1:8082`; Nginx forwards to Flask on loopback port 8000.

**Why both proxies:** Caddy handles public TLS and site routing. The reviewed
Nginx guard already provides explicit raw-URI/method allowlisting, request and
connection quotas, size/time bounds, no upstream retry, and a deliberately small
header set. Keeping it reused tested controls rather than removing/rebuilding
them merely to reduce a box in the diagram. The extra hop stays on the laptop.

**Tradeoff:** there are two configurations and services to diagnose. A future
single-proxy design could be simpler, but would need equivalent controls and
tests; removing Nginx without that review would change the protection boundary.

## 10. Protect the local grid while exposing only the signed skill path

**Decision:** publish only exact POST `/alexa`; reject other public paths and
restrict the existing private Caddy site to direct home-network peers. Keep app,
ADB, private guard and admin ports off the router's public forward list.

**Why:** the local/legacy interface has intentionally different trust and
compatibility requirements. The original Caddy proxy could make an internet
request look like a trusted loopback request to Flask if published unchanged.
The restricted LAN site must be active before enabling public 443. Forwarded
headers do not prove that a caller is on the home network.

**Tradeoff:** a root-page 404 at the public name is intentional. Remote browser
access is not automatically enabled by making Alexa work. Restoring an old
unrestricted Caddyfile requires closing public forwarding first.

## 11. Verify Amazon and explicitly authorize the skill and owner

**Decision:** verify the original request's signature/certificate and freshness,
then require the configured application ID and user ID in context and session.
Do not enroll the first caller automatically.

**Why:** HTTPS authenticates the server to Amazon; it does not restrict who may
submit a movie request. The private owner check is independent of signature
verification and skill development status. A LAN source, cookie, bearer token
or fake forwarded header cannot bypass the Alexa checks. Proxies preserve the
signed body and necessary signature headers.

**Implementation choice:** use Amazon's SDK crypto checks with a small adapter
for bounded certificate download/cache, and admit one verifier job at a time.
This avoids inventing cryptography while addressing unbounded I/O/cache behavior
in the dependency. The speech code stays separate and readable.

**Tradeoff:** pinned upstream dependencies need future maintenance and currently
emit deprecation warnings. A slow verifier can occupy its single slot. Resource
bounds and safe rejection do not promise that all underlying DNS calls stop
instantly or that every failure can be retried without consequences.

## 12. Replace the TP-Link CNAME with a direct, automatically updated A record

**Decision:** retain the public hostname, but point its A record directly to the
WAN IPv4 and maintain it with a small Python task using GoDaddy's API.

**Why:** the CNAME idea initially avoided a custom updater by relying on Deco
DDNS. Actual certificate attempts and DNS probes then showed CAA `SERVFAIL` for
the TP-Link target, while the main domain answered normally. CAA checks follow
CNAMEs, so simply adding unrelated root records was not the established fix.
The direct A record removed that failing dependency and issuance succeeded.
[Let's Encrypt CAA behavior](https://letsencrypt.org/docs/caa/)

**Tradeoff:** an A record alone would become stale if WOW changes the address.
The updater now handles that, at the cost of a private GoDaddy token, expiry
maintenance and a short detection/cache delay. Deco DDNS can remain registered
but is not part of the working Alexa DNS resolution chain.

## 13. Use a small standalone DNS tool and systemd timer

**Decision:** standard-library Python, a read-only default, `--apply` for the timer,
an existing-record lookup and a replacement of only that record by its ID.
Check roughly every five minutes, with a 40-second service limit.

**Why:** no Node package, extra daemon, cloud scheduler or Flask startup hook is
needed for this job. systemd already manages the laptop's services and provides
boot scheduling, logs and status. The read-first/single-record API path preserves
website and email records and avoids rewriting a DNS zone. GoDaddy documents
individual-record lookup/replacement and TTL preservation requirements.
[GoDaddy DNS API](https://developer.godaddy.com/en/docs/api-users/domains/manage/dns)

**Tradeoff:** task failure is visible in systemd logs rather than an automatically
configured external alert. Tokens expire and require replacement. A later run
reconciles an uncertain write by reading first; it is not an immediate blind retry.
An active timer and successful unchanged-IP run do not prove real WAN-change
recovery. Proxy/VPN/routing changes warrant checking the observed public IP.

## 14. Use DHCP reservations and narrow firewall access

**Decision:** Ubuntu uses DHCP with Deco reservations for laptop/admin addresses.
Allow LAN web access from the whole main `/22` subnet, SSH from the reserved
admin PC only, and public TCP 443 on Wi-Fi. Remove old `/24` and broad control-port
rules; retain existing discovery rules.

**Why:** the move from `192.168.86.x` to `192.168.68.x` left Ubuntu's manual address,
default route, firewall sources and app Host/LAN trust settings stale. DHCP plus
router reservations makes the address predictable without embedding a stale
gateway in Ubuntu. The user wanted any home browser to reach the grid rather
than a single iPad IP; that did not require broadening SSH or internet access.

**Tradeoff:** private-address/subnet changes still require reviewing trust rules,
Caddy's home-peer matcher, reservations and the TV address. The public DNS updater
does not fix private network addressing. Keep the current SSH session open until
a second connection verifies a firewall change.

## 15. Treat delivery as evidence, not playback, and avoid blind launch repeats

**Decision:** distinguish request acceptance, command delivery and observed
playback. Serialize all launches and avoid automatically repeating uncertain
delivery. Keep the old wake/Home/Disney+ deep-link sequence and authorized ADB key.

**Why:** a successful socket write or Android intent response does not show the
movie actually playing. A timeout can occur after delivery; automatically trying
again could restart or replace a movie. The working launch behavior was preserved
instead of experimenting with an unrelated playback mechanism.

**Tradeoff:** a user may need to look at the TV or use the remote after uncertainty.
Legacy response wording is retained for compatibility, but is not proof of
playback. State is bounded/in-memory, not a durable observation system.

## 16. Select `zach` only from an identified, focused profile card

**Decision:** optional backend XML recognition followed by one fixed Select event.
Require the Disney+ package, recognized picker/title, unique exact profile label
and already-focused actionable parent. No coordinates, profile navigation or PIN.

**Why:** the real UI dump exposed `Access zach's profile` under a focused card,
so a small deterministic check was possible. The user confirmed that choosing
that no-PIN profile continues the pending movie; another deep-link launch is not
needed. Blindly pressing OK after every request could affect an unrelated screen.

**Tradeoff:** profile/app/UI changes can cause a safe no-op requiring the remote.
Inspection adds bounded time while the command reservation remains active.
Physical remote activity can change UI between capture and Select, so avoid using
it during the check. Both interrupted and ordinary launch cases passed live tests.

## 17. Use controlled patches, private backups and layered verification

**Decision:** inspect dirty working trees, review targeted patches, back up affected
files and test before enabling/restarting. Keep production secrets/ADB identity
out of source. Do not run deploy.sh, reset hard, commit or push as a shortcut.

**Why:** the server contained existing edits to the catalog/deployment script and
an old virtualenv backup. Source changes had to preserve those and the current
configuration. Mocked tests establish contracts; isolated native proxy tests
establish routing behavior; actual Echo/TV checks establish user-visible playback.
None substitutes for every other layer.

**Tradeoff:** rollout took several small, reviewable stages. Unit-test success
alone did not authorize deployment or demonstrate public TLS, screen behavior,
WAN-change recovery or certificate renewal. The verification log records which
checks actually occurred. The app still has deployed uncommitted changes; any
future commit/deployment needs a separate reviewed task.

## 18. Preserve the browser workflow and isolate runtime dependencies

**Decision:** retain the existing grid/Jinja/plain-JavaScript approach and the
server's Python virtualenv. Keep optional Alexa dependencies in their separate
requirements file and use a separate test virtualenv for Linux checks.

**Why:** Zach's picture-based interface and the authorized ADB identity were
already working. Adding voice should not force a browser-framework change,
container migration or replacement of household data. Separating test dependency
experiments from the running app made the Ubuntu/Python/OpenSSL upgrade and old
SDK compatibility checks reviewable before activation. TMDB's existing poster
path was retained; it is not the Alexa title-resolution or device-control service.

**Tradeoff:** the current app still has its existing startup/catalog/poster
requirements, and virtualenv paths must be preserved in the service. Successful
voice/playback tests do not establish every historical iPad/Safari/accessibility
gate or a new UI rollout. Those are separate verification scopes.

## Alternatives and future triggers

| Option | Why it is not in this deployment | When to revisit |
|---|---|---|
| IFTTT / generic webhooks | No integration was built or validated; another service would still need secure title resolution and device coordination | A concrete supported trigger adds value without losing current controls |
| Home Assistant | Not needed solely to add this one voice-to-TV path | The household adopts it for broader automation |
| Lambda / Alexa-hosted backend | Additional runtime/deployment and laptop callback path | A specific operating requirement justifies the split |
| Cloudflare Tunnel | Direct HTTPS met the selected household requirements | Inbound reachability, NAT/ISP conditions or exposure preferences change |
| Nginx-only TLS / Certbot | Caddy already managed the working LAN site and occupied 80/443 | Consolidation is justified and equivalent controls/renewal are tested |
| Caddy-only proxying | Existing private Nginx controls were reused and tested | All limits/auth/header/path protections are deliberately preserved |
| Database / broker / many workers | Single-TV bounded local coordination is sufficient | Shared state, scale or durable recovery is required |
| Native Video Skill / general media control | Outside the play-only scope; no assumption of Disney+ app integration support | Target-device/provider behavior is established and separately designed |
| Broad profile navigation / PIN automation | Focused no-PIN selection solves the supplied case with less UI logic | More household profiles or changed UI require a supported extension |

## Diagnostic lessons that affected the rollout

The initial "not supported on this device" response with empty JSON Input was
not solved by interface toggles, testing reset or a temporary invocation name.
CLI inspection exposed an empty custom locale declaration despite a retrievable
model. After the manifest/model updates and successful builds, invocation later
generated JSON and reached the disabled backend. We did not establish which
individual change alone resolved Amazon's routing symptom.

Once requests reached Flask, the disabled Alexa flag explained the expected 404.
Obtaining the real user ID, privately configuring skill/owner IDs and enabling
the handler allowed the opening response and then real movies. A successful
simulation status did not mean successful skill playback. CLI request flags also
differed from raw API JSON; inspect the installed command's help before reuse.

These lessons explain the final configuration; they are not instructions to
repeat all diagnostic changes on an already-working installation.
