# A simple play-only Movie Magic Alexa skill

Historical plan: the draft below preserves the alternatives and original rollout
stages. For the completed household route and why the choices changed, use the
[current architecture](architecture.md), [decision record](architecture-decisions.md)
and [operations guide](movie-magic-operations.md). In particular, Cloudflare and
the TP-Link CNAME path below are not the active deployment.

Deployment-path update, 2026-11-24: the user is pursuing direct HTTPS through
GoDaddy DNS and their Deco BE10000 on WOW internet, replacing the Cloudflare
connection in the original draft below. Keep the GoDaddy Builder website, Google
mail and existing local movie-grid hostname. Use a separate proposed public
`movies-api.fradkin.net` hostname, backed by Deco DDNS if available. No nameserver
migration is planned. The user reports matching router WAN/public IPv4 addresses;
this is not proof of incoming-port reachability. Isolated Ubuntu signed-request
and native Nginx checks passed as recorded in [verification](alexa-verification.md).
The 8082 loopback template still needs a reviewed public TLS arrangement; neither
internet publication nor live-device testing is authorized by these check results.
Amazon Developer and Cloudflare accounts were created by the user, and the custom
voice model built successfully. Cloudflare is unnecessary for the current route.

Implementation follow-up: the user separately requested local implementation.
See the [code/setup walkthrough](alexa-setup.md) and [test record](alexa-verification.md).
The selected local code is now implemented and default-off; the planning text
below records its design. Cloud accounts, production setup, device acceptance and
the user's code-understanding walkthrough remain pending.

Planning draft, 2026-11-22. The user selected local Python hosting with Cloudflare
connectivity. This revises the Lambda proposal; implementation and production
changes still require separate requests/approval. This smaller first release does
not complete the broader [Phase 5](specs/05-alexa-integration.md) milestone.

## Agreed experience

Say "Alexa, ask Movie Magic to play Luca." Use the invocation "Movie Magic",
subject to console validation, with US English. Devices use the owner's Amazon
account. No public store release is planned. Python should be easy for the user
to follow. They have no Amazon Developer or Cloudflare accounts yet and prefer
no additional costs, or very low costs if necessary. GoDaddy is the domain provider
for the existing `fradkin.net`; the user confirmed that DNS records are also
managed at GoDaddy.
The user confirmed that the domain serves both a website and email. Preserving
both services is a prerequisite for any future DNS change.

A unique title or configured nickname launches without another question. For an
ambiguous name, offer up to three numbered titles and wait for a choice. With more
than three matches, ask for a more specific title. Unknown titles launch nothing;
ask for the full title once, then end. Do not guess using spelling similarity.
Cancel and Stop inside this skill end the conversation without controlling the
movie. Help explains that this version only starts movies. Opening without a
title gives a usage example; bare-title replies after opening are not required.

Alexa says "I sent a request for Luca to Fire TV" only after admission. That means
accepted, not command delivery or confirmed playback. On an uncertain submission
outcome say "The request may have reached the TV. Please check the screen before
asking again." Never automatically repeat a launch.

## Where everything runs

```text
Echo hears the request
  -> Amazon Alexa interprets it
  -> HTTPS at movies-api.fradkin.net/alexa
  -> Cloudflare Tunnel and loopback proxy
  -> Existing Flask app verifies the Alexa request
  -> MovieService matches the title
  -> PlaybackService accepts the launch
  -> FireTVService sends the existing Disney+ command
```

The hostname is a proposal, not a configured address. All our Python runs on the
existing Movie Magic laptop in the existing app factory, using the same service
instances and single Gunicorn worker. Amazon still provides Alexa's cloud speech
service; this is not offline Alexa. The laptop must be running and online for
voice requests. Local iPad use remains independent of the voice/cloud connection.

No Lambda, AWS account, Secrets Manager, self-HTTP calls, new public resolve API,
new database or queue is required for this version. The existing API can remain
disabled remotely. Do not enable `REMOTE_API_ENABLED` just to enable Alexa.

## Two small Python files

| Proposed file | Responsibility |
|---|---|
| `alexa/skill.py` | Play, numbered choice, help/cancel and short spoken replies |
| `alexa/web.py` | Register the POST endpoint; bound and verify requests; authorize the household; supply existing services |

The conversation code calls MovieService directly to resolve a title or revalidate
a chosen key, then calls PlaybackService.submit_play(). It never opens ADB or
constructs shell commands. A dedicated stable principal derived from the verified
skill/user identity owns its requests. Hash each Alexa request ID into the existing
bounded idempotency-key format; duplicate events use the same key. Preserve busy,
cooldown, job limits, retention and restart limitations. No exactly-once claim.

Keep ordinary names and explicit branches. Avoid another handler framework,
generic plugins, clever decorators and broad service refactoring. Use Amazon's
Python ASK SDK and web-service verifier rather than writing cryptography. Pin and
inspect compatible packages, including current signature support and bounded
certificate retrieval, before selecting versions. Put these local-hosting
dependencies in a clearly named optional requirements file and document their
installation on the app host; they are not Lambda-only dependencies anymore.

Supporting artifacts are one voice-model JSON file, a small catalog export tool,
tests, example proxy/tunnel settings and a setup guide. No Lambda deployment files
or API client module is needed. Export title/key/aliases only, never provider IDs.
Refreshing the model after catalog changes can improve recognition; the backend
remains authoritative when the model is stale or Alexa returns an unknown value.

The user must be able to follow one successful request and one ambiguous request,
find the spoken replies, understand adding an alias, and locate failure handling.
If that walkthrough is difficult, simplify before extending the feature.

## A dedicated verified Alexa endpoint

This is an explicit design revision to Phase 4's Lambda/Access service-token path.
Amazon directly calls a custom HTTPS endpoint and cannot supply our Access token
or backend Bearer header. Do not publish a machine API without those protections.

For this skill only, publish the exact `POST /alexa` endpoint through a dedicated
hostname/tunnel route and loopback proxy. Deny every other remote path/method and
all query strings; reject alternate encodings, double slashes and normalization
bypasses. Preserve the raw request body and the SDK-required Amazon signature and
certificate headers. Do not redirect the endpoint, rewrite its JSON, require an
interactive login, or issue browser challenges to valid Alexa requests.

Apply explicit edge method/path/body protections available on the selected free
plan, plus loopback proxy limits and bounded application admission before costly
verification. The edge layer is not authentication. This dedicated endpoint cannot
use the machine API's Access Service Auth policy. Any Access bypass must be scoped
to this endpoint/hostname; never remove Access or Bearer requirements from the
existing machine API. Native and staging denial tests gate approval of this new
edge design. If the free edge configuration cannot meet the agreed protections,
revisit the design/cost rather than silently publish it.

Always verify the Amazon signature over the original body, certificate chain and
certificate URL, freshness (at most 150 seconds), expected skill ID and configured
Alexa user ID. Check these even for LAN/loopback requests; forwarding headers are
not proof of identity. Reject missing, inconsistent or wrong identities before
resolution or side effects. Use the SDK verifier with verification enabled; test
its behavior instead of assuming the adapter enforces our skill/user allowlist.
Invalid signature/timestamp requests return HTTP 400 per Amazon requirements.

Do not enroll the first caller automatically. During approved setup, a correctly
signed request for the expected skill may supply an enrollment identifier for
operator review, but launching stays disabled until the user ID is explicitly
configured. It is the skill-scoped account user ID, not a voice profile/person ID.
Do not log complete events, spoken payloads or identifying account values.

The Flask before_request path must explicitly recognize this independently
authenticated endpoint while preserving all existing LAN, CSRF, Host and API
checks. A known Host or loopback source alone must never authorize Alexa commands.
Introduce a separate default-off Alexa feature flag; fail closed on missing IDs.

Bound JSON at 32 KiB initially, header sizes, proxy reads, signature-verification
work and certificate network/cache operations. Validate request type, locale,
title length, event ID and dialog fields. Cap concurrent verification and total
admission memory without a thread per incoming request. Inspect the SDK's fetch,
redirect and cache behavior; no unbounded network defaults are acceptable. Target
an end-to-end handler response under six seconds including verification; return
after launch admission without polling ADB. Recheck the size limit with actual
signed events and document any justified adjustment before release.

Keep candidate session attributes bounded to three keys/titles, timestamp and
reprompt count. Expire them after two minutes and re-resolve a selected key before
submission. Validate numbered choices and session data; never store credentials
or provider IDs there. Shared locks serialize Alexa, legacy and iPad launches.

References: [Amazon web-service requirements](https://www.developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html)
and [Python SDK verification](https://www.developer.amazon.com/en-US/docs/alexa/alexa-skills-kit-sdk-for-python/host-web-service.html).

## Accounts, domain and costs

Create an Amazon Developer account using the Amazon login associated with the
Echo. Registration is free. Configure an HTTPS endpoint in a development skill;
test on the actual account/device. Do not confuse leaving it unpublished with
backend authorization. No separate AWS account or paid Alexa subscription is
part of this design.

Create a Cloudflare account and target a free Tunnel/edge configuration. Expected
incremental subscription cost is $0 if its verified free-plan capabilities meet
the design; existing internet, laptop electricity and domain renewal remain.
There is no longer a $0.40/month AWS secret-storage charge. Confirm current terms
and any paid option before provisioning; do not silently select paid features.
Sources: [developer registration](https://developer.amazon.com/en-US/docs/alexa/ask-overviews/create-developer-account.html)
and [Cloudflare plans](https://www.cloudflare.com/plans/zero-trust-services/).

The domain can remain registered at GoDaddy. The normal free full-zone Cloudflare
setup changes authoritative DNS nameservers, not the registrar. Before proposing
that change, export/review the existing GoDaddy DNS records and preserve website, mail, verification
records and DNSSEC settings with a rollback plan. Inventory existing A/AAAA/CNAME,
MX, SPF, DKIM, DMARC, verification and other records before a proposed migration;
check website and mail operation before and after, and define rollback criteria.
Do not rely on automatic record discovery being complete. The movie endpoint uses
its own hostname and must not replace website or mail records. If DNS cannot move, evaluate
alternatives before selecting one. No DNS changes, router forwarding, inbound app
ports or public ADB are part of this planning task.
See [Cloudflare DNS setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/).

## Small implementation stages for a later request

1. Review SDK compatibility, bounded verification and the dedicated edge design;
   prepare a mocked request that demonstrates the straight-line Python flow.
2. Add the default-off endpoint and household verification. Prove invalid callers
   cause zero service/device actions. Reuse the existing services directly.
3. Add play and numbered-choice conversations, the model export and regression
   tests. Walk through code with the user before adding anything else.
4. Prepare exact developer-account, DNS, tunnel, proxy, enrollment and rollback
   instructions. Validate native proxy/tunnel configuration and LAN/iPad gates.
5. With separate approval, configure infrastructure, enable the household skill
   and record real Echo/TV checks. Disable the Alexa route/flag to roll back while
   retaining the iPad and ADB identity. No pending/unknown command is replayed.

Tests must cover signatures, timestamp boundaries, wrong skill/user, enrollment,
certificate URL/timeout failures, bounded admission, route normalization/denials,
and no new bypass to existing APIs. Test unique/unknown/ambiguous titles, expired
or invalid choices, removed movies, help/cancel, busy, duplicate events, uncertain
delivery and simultaneous Alexa/iPad/legacy requests. Use mocked Fire TV and
certificate fetches; signed fixtures may use a generated test trust chain, never
a production identity. Run the required Python suite and skill tests without
contacting real AWS, Alexa, TMDB or ADB. Document checks honestly.

Live launch examples use Luca, Frozen, Tangled, Elemental and Robin Hood. Their
catalog keys are `luca`, `frozen`, `tangled`, `elemental` and `robin-hood`. Frozen II
is separate; do not invent an ambiguity for "Frozen". Use a genuine shared alias
or synthetic fixture for choices. Verify unknown-title handling, unavailable
backend feedback, and continued iPad use. Catalog eligibility is not proof of
provider availability or on-screen playback.

## Remaining questions and deferred scope

Registration and DNS management at GoDaddy are confirmed, as are website and email
dependencies. Identify the website and email hosting providers from the reviewed
records/operator information before preparing a migration checklist. No additional
DNS-provider clarification is needed. Exact Echo model and the app host's Python/OS versions
will be recorded before deployment; inspect compatible dependency versions then.
The selected local feature was implemented under the subsequent separate request.
No accounts, infrastructure or production settings were changed here.

Pause/resume/stop TV controls, global "Alexa, play" interception, voice profiles,
shared history, Home Assistant and IFTTT remain deferred. The broader Lambda and
control designs are historical/future alternatives, not prerequisites for this
locally hosted play-only release.
