# Phase 4 local implementation and verification

Approved local P4.1–P4.3 work, 2026-11-07. No production configuration, credential,
service, tunnel, DNS, firewall or live-device changes were performed by this agent.
No commit, push or deployment was performed by this agent. HEAD advanced externally
to `358d462` during work and incorporated earlier edits; those changes were
preserved. Additional review fixes remain in the working tree.

## Implemented scope

- `AuthService`: fail-closed explicit LAN CIDRs/Host authorities, strong-secret
  configuration checks, bounded validated external hash registry, constant-time
  comparison, scopes, independent remote Bearer auth, signed LAN sessions/CSRF.
- `RateLimitService`: thread-safe sliding windows for general requests, commands,
  failed authentication and remote aggregate traffic; bounded bucket/event memory,
  idle expiry and 429/Retry-After. Valid replays consume general quota only.
- Flask routes: remote movies/play/status aliases share existing services;
  authenticated principals reach idempotency/status; remote status omits device
  metadata. JSON errors and no-store responses; no new endpoints for later phases.
- LAN compatibility: legacy valid unknown IDs still pass through without new
  headers/cookies, subject to direct LAN/Host/origin checks and quota. Both tablet
  modes retain catalog, interaction and wake/Home/deep-link behavior. API browser
  commands carry CSRF; session expiry prompts reload without automatic resubmission.
- Placeholder-only named tunnel, loopback Nginx allowlist and isolated service
  templates, plus [security/rotation/rollback runbook](security-runbook.md).
- Raw ADB warning diagnostics removed from logs; command logs use principal,
  request ID, action/outcome and timing. A source scanner flags recognizable
  credential patterns and forbidden secret filenames without opening live files.

Security settings are required even with `REMOTE_API_ENABLED=false`. The checked-in
service unit, one worker, bind, HOME and authorized ADB identity are unchanged.
No catalog migration or Phase 5/6 implementation was added.

## Observed automated results

Intended interpreter: `.venv/python.exe` (Python 3.12). Temp directories were
redirected to the ignored `.venv/pytest-temp` path. Full suite:

```powershell
$env:TEMP = Join-Path (Get-Location) '.venv\pytest-temp'
$env:TMP = $env:TEMP
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider
```

Result: **202 passed, 1 skipped in 13.04s**. After final logging changes, the same
suite with `--junitxml=.venv/phase4-results.xml` again reported **202 passed,
1 skipped in 8.52s**. The report run emitted two `record_property`/xunit2 format
warnings; assertions passed and properties were present in the local report.

Observed p95 timings in that report:

| Measurement | p95 |
|---|---:|
| Authenticated remote status, including route/status/JSON | 0.71 ms |
| Existing API admission benchmark | 1.73 ms |
| Existing local status benchmark | 1.34 ms |

These are development-host measurements with fake devices, not production timing
guarantees. The status/auth path met the specification's under-20-ms target here.

Coverage includes token failures/revocation flags, missing scopes, constant-time
comparison usage, invalid/missing registry and startup validation before catalog
effects; direct IPv4/IPv6 and forged headers; signed session expiry, cookies, CSRF,
cross-origin/Fetch Metadata; principal-owned jobs, replay and command/general quotas;
window boundaries/caps/expiry/concurrent consumers; remote method/route/body/query
denials; aggregate/failure limits; sanitized errors and scanner canary detection.
Existing catalog, migration, legacy, dispatcher/concurrency and bounded ADB tests
remain green. POSIX permission enforcement has a platform-conditional assertion;
this Windows run cannot prove production Linux permissions or Windows ACLs.

A real loopback HTTP test uses an isolated Werkzeug server with temporary catalog
and mocked Fire TV. It verifies session cookie/CSRF exchange, independent Bearer
auth, forged identity denial, principal isolation and old LAN clients. The
existing isolated ADB-library timeout test also ran; neither contacts real ADB.
Windows socket restrictions initially blocked loopback execution; final passing
runs used reviewed execution outside that restriction. Early machine-job helper
failures and a fixture's inherited local tablet flag were corrected; neither is
counted as a passing run.

The native Nginx test is **skipped because Nginx is not installed**. It prepares
an isolated config, lints with `nginx -t` and, when available, launches a loopback
proxy against the fake app to test publication/normalization/method/body denials.
Raw-URI regex/invariant tests passed here but do not replace native parsing or
HTTP integration. cloudflared is also absent, so ingress syntax/rule validation
was not run. No tools were installed. P4.2/P4.3 native verification remains pending.

Client checks:

- `node --test tests/tablet.test.cjs`: **19 passed**.
- `node --test tests/ui/tablet.spec.cjs`: **14 passed**, using existing cached
  Playwright/Chromium and the documented `NODE_PATH`/browser settings in
  [tablet verification](tablet-verification.md). All browser traffic is intercepted;
  external posters are blocked. The suite verifies the actual CSRF header,
  keyboard/touch interaction, rapid-tap suppression, focus, storage, uncertainty,
  outage/auth feedback, contrast, 200% text reflow and tablet-size layouts.
- `python -B tools/scan_secrets.py`: **0 findings**; synthetic canary detection is
  separately tested. Live `.env`, tunnel credentials and ADB keys were not opened
  by the scanner. This is signature-based coverage, not proof of absence of secrets.

## Remaining release gates and risks

Native Nginx/cloudflared lint and isolated proxy HTTP tests must pass on a suitable
host before staging. Deployment must validate exact hostname, network boundaries,
IPv6 behavior, protected file ownership/ACLs and existing iPad URL. Do not infer
actual firewall or Access configuration from templates. No edge denial, DNS,
external-port or approved successful TV command was tested.

Actual iPadOS/Safari, physical accidental-touch and accessibility/usability checks
remain pending, including session expiry and suspend/resume. Chromium with
synthetic data does not prove target-iPad behavior. The P3.4 device checklist and
P4.4 tunnel/WAN outage and rollback rehearsal remain mandatory release gates.

Residual risks: trusted-LAN HTTP session sniffing; legacy GET/CSRF compatibility;
operator misconfiguration causing LAN lockout; bounded limiter saturation denying
service; process-local state lost on restart; startup-snapshot credentials requiring
approved restart for revocation. The runbook describes mitigations, recovery and
remote-first shutdown. Command delivery never proves playback and timeouts never
justify an automatic launch retry.
