# Phase 4 security and connectivity runbook

Local P4.1–P4.3 implementation approved 2026-11-07. This runbook is preparation,
not authorization to install software, provision live secrets, change production
configuration/firewalls/DNS, restart services, publish a tunnel or contact the TV.
P4.4 and actual-iPad Phase 3 gates remain pending. Remote tablets, Alexa handlers,
resolve/control and Phase 6 endpoints are out of scope.

## Local application contract

Startup now fails closed before catalog refresh unless `FLASK_SECRET_KEY` is a
stable random secret of at least 32 characters and `TRUSTED_LAN_CIDRS` and
`ALLOWED_HOSTS` are explicit. Generate the key using a cryptographic generator;
length validation cannot prove entropy. Example values are placeholders.

- CIDRs are strict IPv4/IPv6 networks; loopback must be listed explicitly.
  Never include guest networks or an all-address range. IPv4-mapped IPv6 peers
  are not silently translated; explicitly validate the production socket form.
- Hosts are exact authorities, including a port when browsers send one. Include
  the existing private iPad address/port and `zmm-origin.internal` for the proxy.
  No wildcard, forwarded Host/IP or Cloudflare identity header grants trust.
- `/` grants a signed household session only to direct trusted peers. Cookies
  are HttpOnly, SameSite Strict, non-sliding, and expire after 12 hours by default
  (`SESSION_LIFETIME_SECONDS`, 60–43200). HTTP LAN cookies deliberately lack Secure;
  a LAN observer can steal them. Isolate the trusted household network. Local
  HTTPS and Secure cookies require a separately approved URL/proxy migration.
- Session-authenticated API calls also require the direct LAN address. Commands
  require JSON, `X-CSRF-Token`, same-origin Origin when present, and no cross-site
  Fetch Metadata. Reload `/` to recover an expired session; never automatically
  resubmit a command. Favorites/recovery state remains in the browser.
- Legacy `/play/<video_id>` remains LAN-only, no-store, and needs no new browser
  headers or cookie. Mismatched Origin/cross-site metadata is denied when supplied.
  Its unavoidable mutating-GET/CSRF risk remains until the Phase 2 retirement gate.
  Existing response shapes, valid unknown-ID pass-through and usage counters remain.
- API status and idempotency use authenticated principals. Remote metadata omits
  device connectivity; playback remains unknown even after command delivery.
- Existing one-worker/four-thread service, private address/port, HOME, ADB keys,
  movie catalog and `TABLET_API_ENABLED` selection remain unchanged.

`REMOTE_API_ENABLED=false` is the default. Security checks on local routes are
active even with remote disabled. Do not deploy this artifact without first
reviewing the new required settings and preparing LAN rollback access.

## Backend credential registry

`API_TOKEN_FILE` points to an external JSON file. It is required when remote mode
is enabled; specifying it while remote is disabled also enables local scoped
bearer clients. File size is bounded to 256 KiB/128 credentials. On POSIX, group
and other permissions are rejected; provision 0600, owned by the app user. On
Windows, restrict its ACL to the operator/service identity; Python cannot prove
the Windows ACL through POSIX mode bits. Keep `.env`, registry, tunnel credentials,
Access secrets and all ADB keys outside Git, owner-readable only.

Credential format is `<token-id>.<secret>` where the secret is the canonical
unpadded base64url encoding of 32 cryptographically random bytes. Generate it
with `secrets.token_urlsafe(32)` in a protected operator session. Store only
`hashlib.sha256(secret.encode('ascii')).hexdigest()` in the registry. Store the
full credential only in the authorized caller's secret store. Do not paste
credentials into shell history, issue descriptions or logs.

Schema (placeholders intentionally fail validation):

```json
{"version":1,"tokens":[{"id":"alexa-v1","secret_sha256":"PLACEHOLDER_HASH","principal":"alexa-household","scopes":["catalog:read","playback:write","status:read"],"enabled":true}]}
```

Scopes `resolve:read` and `control:write` are recognized for future credentials;
they create no endpoints. Other recognized future scopes are preferences read/
write and health read. Grant only needed scopes. IDs/principals are 1–64 ASCII
letters/digits/underscore/hyphen; `lan-household` is reserved. Shared principals
share quota, idempotency and job visibility across overlapping credential IDs.

Registry validation is fail-closed, rejects repeated/unknown fields, duplicate
IDs and invalid hashes/scopes. Invalid tokens receive uniform 401 and
`WWW-Authenticate: Bearer`; valid credentials lacking scope receive 403.
The registry is a validated startup snapshot, not a watched mutable file.
**An approved application restart is required for rotation or revocation.**
If immediate restart cannot be approved/performed, revoke the Access credential
or disable the tunnel immediately through the authorized incident procedure;
editing the registry alone does not revoke a running process's credential.

## Admission and safe logging

Process-local sliding windows combine play/legacy command admissions per
principal: 10/minute, burst 2/2 seconds. General requests, including commands and
idempotent replays: 120/minute, burst 10/second. A valid replay skips command quota,
not request quota. Invalid input does not launch or reserve a job. Command quota
is charged after validation and shared-slot checks; worker-start failures may
consume quota but never create a delivered/replayed launch.

Authentication failures: 30/minute per actual socket peer. All remote-prefix
traffic: 300/minute aggregate, including invalid credentials. Behind the proxy,
failed credentials share its loopback peer. No spoofed IP headers affect quota.
At most 1024 buckets across policies, each bounded by its minute limit; idle
expiry 15 minutes. Capacity exhaustion returns 429 instead of evicting live
buckets. A flood can temporarily deny service; memory and commands remain bounded.
The shared playback slot/cooldown still serializes legacy, LAN and remote calls.

Never log Authorization, Access headers, cookies, CSRF, raw request bodies or
provider commands. Application security errors are sanitized JSON; ADB warning
logs record exception type instead of raw exception text. Proxy access logging
is disabled; keep error severity critical and debug off. Deployment-level log
collectors and edge retention need separate review. Run
`python -B tools/scan_secrets.py` before sharing changes. It scans tracked source
and non-ignored additions; forbidden secret paths are flagged without reading
their contents. Its ASCII signatures are supplemental, not a universal scanner.

## Approved staging/deployment sequence (not executed)

1. Confirm domain/Access plan, exact trusted LAN/guest boundaries, IPv4/IPv6
   topology, firewall tools, operator recovery access and P3.4 iPad checks.
   Inspect actual deployment triggers first: `deploy.sh` hard-resets/restarts;
   README's referenced GitHub workflow is absent from this checkout.
2. Back up current application/config/unit/firewall/proxy artifacts with protected
   permissions. Preserve existing catalog and service-user HOME/ADB identity.
   Prepare the exact previous artifact and matching configuration for rollback.
3. Provision external settings and session key with remote disabled. Use the
   current `.env` loading path until an approved configuration migration. An
   approved systemd drop-in may add an external EnvironmentFile; preserve the
   existing ExecStart (one worker), bind, HOME and app identity.
4. Install Nginx/cloudflared only with approval. Adapt the checked-in `.example`
   files to the actual versions and hostname. Nginx must listen only on
   127.0.0.1:8081; the app remains on the existing LAN address/port. The Nginx file
   belongs inside `http {}` because it contains a raw-URI map.
5. Perform offline lint on isolated copies: `nginx -t -c <isolated-config>` and
   `cloudflared tunnel --config <isolated-config> ingress validate`. Verify
   ingress-rule matching for allowed/denied URLs with `ingress rule`. See
   [Cloudflare configuration validation](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/)
   and [Nginx map syntax](https://nginx.org/en/docs/http/ngx_http_map_module.html).
6. Configure a named outbound tunnel with a dedicated hostname and a separate
   Access **Service Auth**, service-token-only policy. No bypass/public Allow
   policy or quick tunnel. cloudflared uses its own unprivileged service account,
   separate from the app/ADB identity. Protect its tunnel JSON/config permissions.
7. Caller sends independent Access client ID/secret headers plus backend Bearer.
   Nginx discards incoming headers except explicit backend essentials and sets
   the internal Host. Public routes are only GET movies/status and POST play.
   Queries are denied except one unencoded status request ID. Resolve/control,
   UI, legacy, health, static and internal names remain denied. No CORS publication.
8. Require host/router firewall coverage for both address families. Permit app
   8000 only from loopback and approved LAN ranges; remove inbound forwarding for
   5000/8000/5555/5037. Keep ADB local/private. Do not make the app loopback-only
   without an approved LAN proxy/URL migration. Inspect rules with the operator;
   this repository cannot establish the actual external exposure.
9. Enable remote only after registry/config validation and approved restart.
   Verify missing Access cannot reach origin; valid Access without backend token
   gets 401; insufficient scope gets 403; malformed paths/methods/bodies are
   denied before effects. Verify origin directly still requires bearer on every
   remote route. Confirm TLS externally and no reachable inbound ports including
   IPv6. Never infer playback from HTTP 202 or command_sent.
10. Only after separate live-device approval, send one known launch, observe the
    TV, then stop tunnel/disconnect WAN and verify the existing iPad still works.
    Record exact iPadOS/Safari and accessibility/suspend/resume results. Proxy
    timeouts are ambiguous and never justify an automatic fresh launch.

## Rotation, expiry, incidents and outage recovery

Record token owners, scope, creation/expiry, rotation due date and verification
without recording secret values. Configure an operator reminder before Access
expiry (for example 30 days and 7 days); creating live reminders requires approval.
Never silently choose never-expiring credentials. Follow
[Cloudflare service-token lifecycle documentation](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

For routine rotation: provision new backend ID/hash with the same principal and
new Access token; deploy the validated registry through an approved app restart;
update the caller's AWS Secrets Manager version with least-privilege role access;
verify both boundaries, then revoke old Access/backend credentials. Target overlap
at most 24 hours; record completion and the restart that removed old backend ID.
No Lambda implementation or AWS resource changes are included in Phase 4.

For compromise: immediately revoke Access/disable the tunnel through the approved
incident procedure, disable/remove the backend entry, validate and restart under
approval. Rotate any exposed independent credentials. Preserve sanitized request
IDs/outcomes, never raw secrets. Flask key rotation expires browser sessions;
it must never replace/delete authorized ADB keys.

For Cloudflare/AWS/internet outage: remote fails closed, LAN remains independent.
Check non-waking health on LAN and operator configuration; do not retry a launch
whose delivery is uncertain. Edge HTML/redirects are authentication/connectivity
failures, not API JSON. Future callers must disable redirects carrying credentials
and never forward bearer headers to another host.

Rollback removes remote exposure first (disable tunnel/Access, revoke remote
credentials), then restores backed-up app/proxy/unit configuration under approval.
Retain LAN firewall protections, original iPad URL/catalog/browser preferences and
ADB identity. Never expose legacy endpoints or ADB temporarily for troubleshooting.
Restart loses in-memory jobs; never replay pending commands. Rehearse and record
rollback as P4.4, not as part of automated tests.
