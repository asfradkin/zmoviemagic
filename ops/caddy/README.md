# Caddy for the locally hosted Alexa endpoint

Current household status, November 24, 2026: the user installed this reviewed
configuration, obtained a public certificate and verified Alexa-to-TV playback.
The original unrestricted LAN Caddyfile is superseded. Start with the
[operations guide](../../docs/movie-magic-operations.md) for active paths and checks.
The old configuration served `moviemagic.fradkin.net` with `tls internal` and
proxied every path to Flask; restoring it while forwarding 443 would be unsafe.

`Caddyfile.alexa.example` is the reviewed replacement installed by the user for
that single-site configuration. The example remains a template, not a live-file
inspection or permission to overwrite a subsequently changed Caddyfile. It keeps the
internal certificate for the LAN site and adds an explicit home-subnet/loopback
peer check. The separate public site accepts only original URI `/alexa` with POST,
caps body/header sizes, bounds header/idle and upstream waits, and uses the tested
Nginx guard on `127.0.0.1:8082`. Caddy must not proxy the public site directly to
Flask or trust forwarded IPs as proof of LAN membership.

Public certificate issuance/renewal uses the standard ACME issuer with HTTP-01
disabled. TLS-ALPN-01 uses TCP 443, so Certbot and a port 80 router forward are
unnecessary. Do not change the old LAN site's `tls internal` to a public issuer:
its DNS intentionally points to a private LAN address. Initial public certificate
issuance and trust were subsequently confirmed by the user's curl check without
`-k` and working Alexa requests. A renewal cycle has not yet been observed.

## Isolated checks

Run `tests/test_alexa_caddy.py` using the separate test environment. One test adapts
the actual production template without starting it or issuing certificates. Eight
HTTP loopback scenarios use ephemeral ports and a fake upstream, checking exact
URI/method policy, untouched body/signature headers, preserved upstream Host,
body-size rejection and LAN denial even with forged forwarding headers. The tests
disable the admin API and automatic HTTPS in disposable instances only.

The test binary can be a locally installed Caddy. No global service, production
configuration, real certificates or TV is used. Caddy 2.6.2 reports streaming
body-size failures as 502; the check requires rejection and no processed upstream
body, while allowing modern versions' 413 response as well. Skips because Caddy is
absent are not a native verification pass.

## Preparation before an approved install

1. Confirm `systemctl is-active caddy` and the actual configuration ownership/path.
   Review installed/candidate package versions and available maintenance updates
   before internet exposure; syntax compatibility with 2.6.2 is not a security
   support claim. No upgrade/restart is authorized by the example.
2. Back up the existing Caddy/Nginx/service/app configuration with protected file
   ownership. Retain Caddy's existing internal CA and storage; never delete or
   copy its private keys into the repository. Prepare exact rollback steps.
3. Review the Caddyfile diff with the user, including the current trusted home
   subnet. If any other Caddy sites have been added, merge deliberately rather
   than replace them from this example. Do not publish unrestricted old routes.
4. For Nginx, prepare the existing `ops/nginx/zmoviemagic-alexa.conf.example` as a
   loopback-only site. Back up/remove only the verified default site symlink when
   approved, so Nginx no longer tries to bind Caddy's 80/443. Inspect other enabled
   configurations too. Lint before starting/reloading any service.
5. Install the reviewed Alexa app changes and optional requirements separately
   from the test sandbox. Configure the expected skill/owner IDs, default-off
   feature flag and exact internal Host; preserve one Gunicorn worker, app secret,
   catalog, ADB identity and LAN access. Do not run `deploy.sh` as validation.
6. With explicit approval, activate reviewed configurations and run local denial
   checks. Then approve/open TCP 443 to Caddy only, with corresponding IPv4/IPv6
   protections. Never forward app 8000, Nginx 8082, ADB 5555/5037 or admin 2019.
   Confirm DNS, external denials, public certificate trust and renewal, and LAN
   operation during WAN outage. Do not infer these from local loopback checks.
7. Finish the development skill's HTTPS endpoint/account checks. Real movie
   requests require separate live-device approval and the current Fire TV IP.

For rollback, remove the public router/firewall exposure before restoring the old
unrestricted Caddyfile. Otherwise restoring the original LAN-only file while 443
is still public could publish legacy controls. Restore protected matching app/
proxy settings without replaying unknown jobs. Keep the LAN site, catalog and
authorized ADB identity.

References: [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https),
[request matchers](https://caddyserver.com/docs/caddyfile/matchers), and
[ACME issuer settings](https://caddyserver.com/docs/caddyfile/directives/tls).
