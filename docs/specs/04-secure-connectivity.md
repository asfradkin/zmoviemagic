# Phase 4 — Secure connectivity

Status: implementation specification. Backlog P4.1–P4.4. No live tunnel, DNS,
credential or production configuration changes are authorized here.

## 1. Objective and user-facing outcomes

Allow an authorized Alexa Lambda to call ZMovieMagic over authenticated HTTPS
while the iPad remains local and works during cloud outages. Neither Fire TV ADB
nor the local ADB server may be internet-accessible.

## 2. Current-state analysis

Production template uses Gunicorn on all interfaces port 8000, one worker/four
threads, and a service-user HOME for the authorized ADB key. The development
server listens on 5000. There is no authentication, CSRF policy, rate limiting or
tunnel configuration. The legacy mutating GET and publicly cacheable grid are
unsafe to publish. A default development Flask secret exists. Preserve LAN
behavior while adding a separate remote boundary.

## 3. Functional requirements

- Use a named outbound Cloudflare Tunnel, dedicated hostname and Cloudflare Access
  Service Auth policy for Lambda. Do not use a public quick tunnel.
- Require an independent backend bearer credential with explicit scopes.
- Publish only allowlisted API methods/paths; deny UI, legacy route, health,
  internal route names, static assets and administrative operations.
- Keep LAN UI on existing private address/port with explicit trusted client ranges.
- Rate limit machine and browser command admission; retain shared cooldown.
- Provide credential rotation, revocation, expiry alerts and outage runbooks.
- Block WAN inbound 5000/8000/5555/5037 and remove any router port forwarding.

## 4. Nonfunctional requirements

LAN playback has no runtime dependency on Access, AWS or an identity provider.
Auth and limiter are local bounded-memory operations; target under 20 ms per
request on host. One worker remains mandatory. Every remote hop uses TLS except
the explicit loopback proxy/origin hop on the same host. Debug off in production.
Limit command JSON to 4 KiB; read-only responses and logs contain no secrets.
Do not rely on optional paid edge rate limiting as the only rate limiter.

## 5. Detailed technical design

### Boundaries and routing

Remote path:
Lambda -> Cloudflare HTTPS/Access -> outbound cloudflared -> loopback Nginx
127.0.0.1:8081 -> existing Flask process on 127.0.0.1:8000 using /remote/api routes.

LAN continues to private host:8000. Gunicorn may keep its current all-interface
bind only if host firewall permits 8000 solely from loopback and approved LAN
ranges, with IPv4 and IPv6 covered. Do not switch to loopback-only without a LAN
proxy and approved iPad URL migration. Nginx remote listener never binds to LAN/WAN.

Cloudflare ingress accepts only the dedicated hostname and API paths, then ends
with a catch-all 404. Nginx is the authoritative method/path allowlist: map public
/api/movies GET, /api/play POST and /api/status GET to /remote/api equivalents.
P5.1 explicitly adds /api/resolve POST and /api/control POST. P6 adds only approved
read-only optional paths; no broad /api/* proxying. Reject encoded slash, double
encoding, dot segments, duplicate slashes and unexpected query parameters before
proxying, with tests against normalization bypasses.

Flask remote routes always require bearer authentication, regardless of IP,
Host or forwarding headers. Local /api routes accept LAN session or scoped bearer.
Both use identical service instances, not a second Gunicorn process. Never infer
trusted origin from X-Forwarded-For, CF-Connecting-IP or user-supplied flags. Do not
enable unrestricted ProxyFix. Validate allowed Hosts explicitly; proxy sets the
configured internal Host and strips incoming forwarding/identity headers.

Example tunnel template, placeholders only:

```yaml
tunnel: TUNNEL_UUID
credentials-file: /etc/cloudflared/TUNNEL_UUID.json
ingress:
  - hostname: movies-api.example.net
    path: ^/api/(movies|play|status|resolve|control)$
    service: http://127.0.0.1:8081
  - service: http_status:404
```

resolve/control remain blocked by Nginx until P5.1. Template is a proposed
locally-managed tunnel; revalidate syntax with the installed cloudflared version.
[Cloudflare documents named tunnel setup](https://developers.cloudflare.com/tunnel/get-started/).
Access policy is separate: service-token-only, no bypass or public Allow policy.

Example Nginx location shape (complete future config must list each route):

```nginx
location = /api/play {
    limit_except POST { deny all; }
    client_max_body_size 4k;
    proxy_set_header Host zmm-origin.internal;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Forwarded-For "";
    proxy_set_header X-Forwarded-Proto "";
    proxy_set_header CF-Connecting-IP "";
    proxy_pass http://127.0.0.1:8000/remote/api/play;
}
location / { return 404; }
```

Use exact locations and reject invalid query/body combinations in Flask. Resolve
and play admission are quick; configure proxy connect timeout 1s, read timeout 3s.
A proxy timeout never proves non-delivery and must not cause a new launch retry.

### Authentication and authorization

Lambda sends CF-Access-Client-Id and CF-Access-Client-Secret plus
Authorization: Bearer <ZMM token>. Access checks the first pair; Flask checks the
independent bearer. The [Cloudflare service-token documentation](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
defines these two edge headers. Cloudflare identity headers alone never
authenticate a Flask request.

Use opaque 256-bit random backend tokens, with token ID + secret format. Server
stores ID, SHA-256 secret hash, scopes and enabled flag in a protected external
JSON file; compare hashes in constant time. No token minting/admin HTTP endpoint.
Scopes: catalog:read, playback:write, status:read, resolve:read; later
control:write, preferences:read/write, health:read. An Alexa credential gets only
catalog:read, resolve:read, playback:write, control:write, status:read. Unknown
tokens return uniform 401; authenticated missing scope returns 403. Status
request IDs are principal-scoped; a principal must not read another machine's
job. General household playback metadata may be omitted for remote principals.

LAN UI initially trusts explicitly configured household subnets/hosts, rather
than adding a login Zach cannot operate. GET / grants a signed session and a CSRF
token only to direct trusted LAN/loopback addresses with an allowed Host.
Use actual socket remote_addr, never forwarded addresses. Phase 4 startup requires
explicit TRUSTED_LAN_CIDRS and ALLOWED_HOSTS; fail closed if absent. This is a
household trust assumption, not individual identity. It cannot safely serve an
untrusted guest subnet.

For local session commands require valid cookie, CSRF header, exact same-origin
Origin when supplied, JSON content type and rejection of cross-site Fetch
Metadata. Cookie HttpOnly, SameSite=Strict, bounded lifetime (12h). Existing LAN
HTTP cannot use Secure cookies: document this residual LAN sniffing risk, isolate
trusted LAN, and do not set Secure until local HTTPS is deployed with approval.
Remote machine requests use no cookies and remain bearer-only. Session-auth HTML
must be private, no-store; it cannot retain the old public cache policy.

Legacy GET remains local-only with actual-address and Host checks, no bearer
publication. It has unavoidable legacy GET/CSRF risk; reject mismatched Origin/
cross-site metadata when present, disable caching, restrict LAN and retain usage
telemetry. Do not require a new browser header on old clients that would break
them. Retire only at Phase 2's gate.

### Limiting and credentials

Per-principal sliding window: command admissions (play/control combined) 10/minute,
burst 2/2 seconds; read/resolve 120/minute, burst 10/second. A valid idempotent
replay does not consume command quota but still consumes general request quota.
Return 429 with Retry-After. Keep maximum 1,024 buckets; idle expiry 15 minutes.
Authentication failures use a separate fixed-size socket-peer limiter, 30/minute;
remote proxy aggregate cap 300 requests/minute protects against unknown-token
floods. Do not use spoofed client-IP headers for attribution. Edge limits may
supplement this design, not replace it.

Keep production .env and bearer registry owner-readable only (0600), outside
repository where possible; preserve current .env loading until an approved
configuration migration. FLASK_SECRET_KEY must be random, non-default and stable.
Tunnel JSON, Access secrets and ADB keys stay outside Git. Lambda gets credentials
from AWS Secrets Manager using least-privilege execution-role access; no secret
values in deployment templates or logs.

Rotate with overlapping token IDs: provision new backend + Access token, update
Lambda secret version, verify, then revoke old credentials after a short recorded
overlap (target 24h maximum). Compromise requires immediate revocation; loss of
remote access must not disable LAN. Track Access expiration with an operator
reminder; do not silently use never-expiring credentials. Rotation of the Flask
session key may expire tablet sessions, never authorized ADB keys.

## 6. API contracts and JSON examples

Existing payloads remain Phase 2 contracts. Public path /api maps to the internal
remote prefix; clients never construct /remote/api paths. Example headers:

```text
POST https://movies-api.example.net/api/play
CF-Access-Client-Id: <edge-client-id>
CF-Access-Client-Secret: <edge-secret>
Authorization: Bearer <backend-token>
Content-Type: application/json
Idempotency-Key: alexa-EXAMPLE-001
```

Body: {"movie_key":"luca"}. Accepted -> 202 queued, not playback confirmed.

```json
{"error":{"code":"authentication_required","message":"Authentication required.","retryable":false}}
```

Backend 401 includes WWW-Authenticate: Bearer. Missing scope -> 403 forbidden.
Access may return HTML or redirects before Flask; callers treat these as
authentication/connectivity failure, do not parse them as catalog JSON and never
follow redirects carrying credentials. Do not forward bearer headers to other
hosts. Application errors use the standard JSON envelope.

## 7. Data models and migration requirements

Credential registry example (not a real token):

```json
{
  "version":1,
  "tokens":[
    {"id":"alexa-v1","secret_sha256":"PLACEHOLDER_HASH","principal":"alexa-household",
     "scopes":["catalog:read","resolve:read","playback:write","status:read","control:write"],
     "enabled":true}
  ]
}
```

New configuration: REMOTE_API_ENABLED=false by default, API_TOKEN_FILE,
TRUSTED_LAN_CIDRS, ALLOWED_HOSTS, existing FLASK_SECRET_KEY, session lifetime and
limiter settings. Enable remote mode only after validated registry, explicit
network settings and non-default secret. Keep old FIRE_TV_IP/PORT, cooldown,
timeouts, TMDB and MOVIES_FILE names. No catalog migration. Browser session
introduction changes HTML caching, not movie keys or legacy request shapes.

## 8. File-by-file implementation changes

| File | Future change |
|---|---|
| services/auth_service.py | Registry validation, scopes, session/CSRF helpers |
| services/rate_limit_service.py | Bounded local limiter with monotonic clock |
| app.py | Remote aliases, auth decorators, Host/LAN checks, safe error responses |
| config.py, .env.example | Validated settings and secret-path placeholders |
| static/tablet.js, templates/index.html | CSRF/session handling; private HTML caching |
| ops/nginx/zmoviemagic-remote.conf.example | Loopback allowlist, limits and timeouts |
| ops/cloudflared/config.yml.example | Named tunnel ingress and catch-all |
| ops/systemd/cloudflared.service.example | Separate least-privilege service |
| zmoviemagic.service | Future approved external environment/firewall documentation; retain worker/HOME |
| docs/security-runbook.md | Provision/rotate/revoke/incident and port checks |
| tests/test_auth.py, test_rate_limits.py, test_remote_routes.py | Auth boundaries, timing, scope, bypass/limiter tests |
| .gitignore | Future external credential/state safeguard patterns; never commit live files |

## 9. Dependencies and prerequisites

Working Phase 2 API and Phase 3 browser flow. Domain under operator control,
Cloudflare account/Access availability and outbound tunnel connectivity must be
confirmed before choosing this deployment. Nginx/cloudflared are proposed host
dependencies, installed only with approval. Confirm host firewall tooling and
IPv6 routing. A private Lambda-to-LAN network is a viable alternative if domain
or Cloudflare is unavailable, but needs a separate cost/operations design.
Public direct port forwarding is not an acceptable fallback.

## 10. Security and failure handling

Threats include leaked machine tokens, public legacy GET, guest LAN access,
forged forwarding headers, credential logging, DNS rebinding, path normalization
bypass and command flood. Controls above address each boundary independently.
Remote authentication is mandatory even on direct-origin calls. Cloudflare
outage must fail closed remotely and leave LAN usable.

Cloudflared runs as its own unprivileged user; app user retains existing authorized
ADB key. Never weaken authorization by deleting adbkey or exposing the ADB daemon.
Do not log Access headers, Authorization, cookies, CSRF tokens or full Lambda
events. Log only principal ID, request ID, action, outcome and coarse timings.
Confirm no debug traces in remote responses.

## 11. Automated testing requirements

Cover all route/method/scope combinations, missing/malformed/revoked tokens,
constant-time comparison usage, invalid registry, default secret rejection,
forged identity/forwarding headers and local Host/CIDR IPv4/IPv6 cases.
Test session/CSRF expiry and cross-origin commands; old LAN client still works.
Verify read/command bucket boundaries, expiry, caps and idempotent replay limits.

Run proxy config lint and isolated HTTP integration tests for path encodings,
legacy/static/internal-route denials, Access-style HTML, redirects and body caps.
Mock Access/Lambda; staging edge tests are a separate approved check, never a unit
test. Secret scanning must flag a test canary but never require reading live .env.

## 12. Measurable acceptance criteria

- External client without Access token cannot reach origin through hostname.
- Valid Access token without backend bearer cannot run any command.
- Valid bearer lacking control scope cannot control TV.
- Remote /play, /, /health and /remote/api paths never reach their handlers.
- External tests show no accessible 5555/5037/5000/8000 ports, including IPv6.
- Command flood is bounded and legacy/API operations still share one slot.
- Existing iPad launches while tunnel service is stopped and WAN disconnected.
- Rotation/revocation works without application secrets in Git or logs.

## 13. Deployment, verification and rollback

Prepare templates and dry-run config validation first. Obtain explicit approval
for production installation, network changes, secrets, DNS and service restarts.
Back up systemd/firewall/proxy configuration; confirm operator LAN access. Stage
backend auth with remote disabled; verify local session/legacy UI. Install
loopback proxy and named tunnel, create Service Auth policy, then enable remote.
Verify denials before an approved successful command and external port checks.

Rollback remote exposure first: disable Access route/tunnel and revoke machine
tokens; retain LAN firewall. Restore previous app/proxy/unit settings from backup
under approval. Do not temporarily publish legacy endpoints or open ADB to debug.
Confirm original iPad URL and authorized ADB identity still function. None of
these production actions is performed by this documentation task.

## 14. Out of scope and unresolved decisions

No remote tablet UI, OAuth account linking, public registration, multi-household
hosting, internet-exposed SSH setup or ADB bridging. Confirm domain/plan and token
expiration options, exact LAN/guest boundaries, actual firewall topology and
local HTTPS feasibility. If the household LAN is not trusted, approving a device
pairing/local authentication design is a prerequisite; subnet trust is insufficient.
