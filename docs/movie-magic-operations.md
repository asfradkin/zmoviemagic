# Movie Magic: everyday use and maintenance

Working household setup, verified with the user on **November 24, 2026**.
Start here when returning to this project. This is the current operating guide;
older plans and verification entries also contain historical preparation steps.
Real secrets and account identifiers are intentionally omitted.

## Everyday use

Say:

> Alexa, ask Movie Magic to play Luca.

Luca, Frozen, Tangled, Elemental and Robin Hood were all tested successfully on
the real TV. Ambiguous requests offer up to three titles; reply with the offered
number. No movie is launched until there is one resolved choice.

If Disney+ asks who's watching, Movie Magic can select the **`zach`** profile.
The profile has no PIN. Both profile-interrupted playback and an ordinary launch
while already past the picker were tested successfully.

Alexa says a request was sent to Fire TV. That confirms submission, not playback.
Check the TV if anything looks wrong before repeating a request. Pause, resume
and stopping the TV are not implemented by this skill; "Alexa, exit" leaves the
skill conversation.

The existing local movie grid remains available at:

```text
http://192.168.68.106:8000/
```

LAN grid access does not depend on Alexa or public DNS. Internet availability is
still needed for Disney+ streaming itself.

## What runs where

| Item | Current setup |
|---|---|
| Ubuntu server | `jukebox`, login `afradkin` |
| Server address | `192.168.68.106`, reserved in Deco |
| Admin computer | `192.168.68.112`, reserved in Deco |
| Deco gateway | `192.168.68.1` |
| Home subnet | `192.168.68.0/22`, mask `255.255.252.0` |
| Server Wi-Fi interface | `wlp1s0` |
| Application directory | `/home/afradkin/zmoviemagic` |
| Application environment | `/home/afradkin/zmoviemagic/.env` |
| Application Python | `/home/afradkin/zmoviemagic/venv/bin/python` |
| Application service | `zmoviemagic` |
| Gunicorn | One worker, four threads, listening on port 8000 |
| Fire TV address | `FIRE_TV_IP` and `FIRE_TV_PORT` in `.env`; reserved in Deco |
| Alexa public endpoint | `https://movies-api.fradkin.net/alexa` |
| Alexa skill | Movie Magic, English (US), development testing enabled |
| Invocation name | `movie magic` |
| Backups | `/home/afradkin/zmoviemagic-backups` |

The exact Fire TV address was confirmed to match configuration, but was not
recorded in this chat. Read the current setting rather than inventing an address.
Do not confuse Docker's `172.17.0.1` address with the laptop's LAN address.

Verified host versions during setup: Ubuntu 26.04.1 LTS, Python 3.14.4,
OpenSSL 3.5.5 and Caddy 2.6.2 from the Ubuntu package. Treat these as recorded
versions, not a recommendation to pin them forever.

## The request's path

```text
Echo → Amazon Alexa → public HTTPS/Caddy → private Nginx guard → Flask
     → movie resolution → serialized playback job → ADB → Fire TV → Disney+
```

| Component | File or location | Purpose |
|---|---|---|
| Caddy | `/etc/caddy/Caddyfile` | Public TLS and exact public path/method restriction |
| Nginx guard | `/etc/nginx/sites-available/zmoviemagic-alexa` | Loopback-only listener on `127.0.0.1:8082` |
| Flask | `app.py`, `config.py` | Application setup and private configuration |
| Alexa entrance | `alexa/web.py`, `alexa/verification.py` | Amazon signature, freshness, skill ID and owner checks |
| Alexa conversation | `alexa/skill.py` | Titles, choices and spoken responses |
| Movie lookup | `services/movie_service.py` | Resolve names/aliases to permanent movie keys |
| Command coordination | `services/playback_service.py` | Admission, serialization and repeat protection |
| Device operations | `services/firetv_service.py` | Existing wake/Home/deep link and guarded profile selection |
| Profile recognition | `services/disney_profile.py` | Recognize the specific focused profile picker |
| Voice model | `alexa/interaction-model/en-US.json` | Invocation, intents, titles and aliases |

Caddy owns ports 80/443 locally. Only **TCP 443** is forwarded from the internet
in Deco to `192.168.68.106:443`. Certificate validation/renewal uses TLS-ALPN on
443, so no port 80 router forward or Certbot is needed for this configuration.
The public site exposes only POST `/alexa`, not the movie grid or legacy controls.

The existing `moviemagic.fradkin.net` site retains its internal certificate and
is restricted to direct home-network/loopback peers. Do not restore the original
unrestricted Caddyfile while public port forwarding remains enabled.

## Important application settings

Edit `/home/afradkin/zmoviemagic/.env` privately. Keep existing settings; the
following is a reference, not a replacement file to paste over the real one:

```dotenv
ALEXA_ENABLED=true
ALEXA_SKILL_ID=YOUR_FULL_APPLICATION_ID
ALEXA_USER_ID=YOUR_FULL_OWNER_USER_ID
DISNEY_PROFILE_NAME=zach
FLASK_DEBUG=false
```

- The skill ID is `context.System.application.applicationId` from Alexa JSON
  Input; it begins `amzn1.ask.skill.`.
- The owner ID is `context.System.user.userId`, beginning `amzn1.ask.account.`.
  It is not a voice-profile/person ID. Session and context identities must agree.
- Preserve the session secret, TMDB key, current Fire TV address and ADB identity.
- `ALLOWED_HOSTS` must retain the existing LAN authorities and include
  `zmm-origin.internal`, the fixed Host supplied by the Nginx guard.
- `TRUSTED_LAN_CIDRS` retains loopback and the approved `192.168.68.0/22` subnet.
- The machine/remote API is separate. Alexa does not require enabling
  `REMOTE_API_ENABLED` or exposing other API routes.

Back up `.env` before changing it. Never print the whole file into chat, store it
in Git or replace it with `.env.example` on the working server.

## Automatic DNS updates

GoDaddy still holds the domain and authoritative DNS. The GoDaddy Builder website
and Google/Gmail email records were preserved. No Cloudflare, Lambda, domain
nameserver migration or additional hosting subscription is part of this setup.

The public `movies-api` record is an **A record** updated to the current public
IPv4 address. It is not a CNAME to Deco DDNS. That earlier CNAME to
`fradkin-movies.tplinkdns.com` failed certificate CAA lookups with `SERVFAIL`.
Deco DDNS registration can remain, but the working Alexa hostname does not depend
on it. Keep the private LAN hostname's private address separate from this A record.

| DNS item | Location or behavior |
|---|---|
| Updater | `/home/afradkin/zmoviemagic/tools/update_alexa_dns.py` |
| Private token | `/home/afradkin/.config/moviemagic-dns/token`, mode 600 |
| GoDaddy permissions | `domains.domain:read`, `domains.dns:update` |
| Service | `/etc/systemd/system/moviemagic-dns.service` |
| Timer | `/etc/systemd/system/moviemagic-dns.timer`, enabled |
| Frequency | Roughly every five minutes, plus up to 15 seconds jitter |
| Public-IP check | ipify over HTTPS; it never receives the GoDaddy token |
| Write scope in code | Only the one existing `movies-api.fradkin.net` A record; preserve TTL |

The updater does nothing if the address already matches. It refuses missing,
duplicate or unexpected records and invalid/non-public IPs. Its default mode is
read-only; the timer runs it with `--apply`. It never immediately repeats an
uncertain update. DNS caches can still hold the old answer until its TTL expires.

The token permits broader DNS access than the script uses. Keep it private.
**Record the token's actual expiry in your password manager and replace it before
then.** GoDaddy offers expiries up to one year; no automatic expiry reminder was
created. See [the DNS guide](alexa-dns-updates.md) for installation and rotation.

Successful live API reads, service execution and the next scheduled timer trigger
were verified. A real ISP address change has not yet occurred as a recovery test.

## Firewall rules after cleanup

UFW is active with default incoming denial. These are the retained rules:

| Port | Allowed source / interface |
|---|---|
| TCP 22 (SSH) | `192.168.68.112`, on `wlp1s0` |
| TCP 8000 (grid) | `192.168.68.0/22`, on `wlp1s0` |
| TCP 443 (HTTPS) | Anywhere, on `wlp1s0`, IPv4 and IPv6 |
| UDP 5353 (discovery) | Existing IPv4 and IPv6 allow rules retained |

Broad 5000/22/8000 rules, obsolete `192.168.86.x` rules and redundant single-iPad/
computer web rules were removed. A second SSH connection succeeded afterward.
No independent external IPv6 port scan was performed in this work.

Keep the router's public forward limited to TCP 443. Do not forward 8000, 8082,
ADB device 5555, ADB server 5037 or Caddy admin 2019. When changing SSH/firewall
rules, keep the current session open and verify a second connection before closing
it. An admin-computer IP change requires reviewing the narrow SSH allow rule.

## How profile selection works

After the movie command is delivered, the optional helper reads a fresh screen
description up to three times. It sends one Select event only if:

1. The screen belongs to Disney+ and is the recognized "Who's watching?" picker.
2. Exactly one label says `Access zach's profile`.
3. That label's card is enabled, selectable and already focused.

It does not blindly press OK, move between profiles, use fixed screen coordinates,
enter a PIN or send the movie launch again. If the UI changes or another card is
focused, use the remote. Leave the remote untouched during the short check.
The original pending movie continues after selecting the profile.

Inspection is bounded to eight seconds, within the new launch's existing overall
15-second budget. The legacy launch path gets a separate bounded eight-second
profile check. Other launches can report busy during inspection. No profile work
runs when `DISNEY_PROFILE_NAME` is blank. See [the profile guide](disney-profile-selection.md).

## Useful checks: safe to run without launching a movie

On Ubuntu:

```bash
systemctl is-active zmoviemagic caddy nginx
systemctl status moviemagic-dns.timer --no-pager
systemctl show moviemagic-dns.service -p Result -p ExecMainStatus
systemctl list-timers moviemagic-dns.timer --no-pager
sudo ufw status numbered
```

The app, Caddy and Nginx should be active. The timer should be `active (waiting)`
with a next trigger. The DNS service is a oneshot: inactive after a successful run
is normal; look for `Result=success`, `ExecMainStatus=0` and its journal.

Read-only DNS check:

```bash
timeout 40s python3 -B ~/zmoviemagic/tools/update_alexa_dns.py
dig @1.1.1.1 movies-api.fradkin.net A
dig @1.1.1.1 movies-api.fradkin.net CAA
```

The updater should say `DNS already current` or `CHECK ONLY`. Public A lookup
should match the current WAN IPv4; CAA should not return `SERVFAIL`.

Check Caddy's local TLS certificate and root-page denial:

```bash
curl -sS --max-time 10 \
  --resolve movies-api.fradkin.net:443:127.0.0.1 \
  -o /dev/null -w '%{http_code}\n' \
  https://movies-api.fradkin.net/
```

Expected: **404 without a TLS error**. Do not add `-k` to a certificate-trust check.
This local check bypasses public DNS/router reachability; actual Alexa requests
exercise the external path. A root 404 is intentional, not a broken website.

Recent logs:

```bash
sudo journalctl -u zmoviemagic -n 40 --no-pager
sudo journalctl -u caddy -n 30 --no-pager
sudo journalctl -u moviemagic-dns.service -n 15 --no-pager
```

If requesting help, share only relevant sanitized output. Do not enable HTTP/ADB
debug logging, paste credentials or expose certificate/ADB private keys.

## Troubleshooting

| Symptom | First checks |
|---|---|
| "Not supported on this device", empty JSON Input | Skill testing Development/en-US; actual invocation; CLI model status; custom locale declaration below |
| "Problem with the requested skill's response" | App service/logs; `ALEXA_ENABLED`; exact endpoint and proxy Host; owner/skill IDs |
| Owner rejected after changing test settings | Inspect the new request's `userId`; testing re-enablement can change it; update private configuration deliberately |
| TLS error | Caddy logs, public DNS and Deco TCP 443 forward; distinguish connection timeout from CAA `SERVFAIL` |
| DNS updater HTTP 401/403 | Token expiry, required scopes and domain ownership; do not paste token or broaden unrelated permissions |
| DNS timer has no next trigger | Recheck after a running oneshot finishes; inspect timer/service status and journal |
| Profile picker remains | Exact lowercase `zach`, no PIN, target focused, recognized UI; inspect `Disney profile action=` in app journal |
| `select_sent` but movie did not play | Check the screen; delivery alone does not prove selection or playback; do not automatically resend |
| Grid unavailable after network changes | Server DHCP reservation, main subnet, `.env` LAN/Host settings and UFW interface/source rules |
| Fire TV cannot be reached | Compare its About → Network IP with `.env`; keep the authorized ADB identity and inspect `adb devices` locally |

The original network was `192.168.86.0/24`; it changed to Deco's
`192.168.68.0/22`. Ubuntu's old static address/default route lived in
`/etc/netplan/50-cloud-init.yaml`; switching to DHCP and setting Deco reservations
restored connectivity. Later network changes may require revisiting Netplan,
reservations, UFW, app Hosts/LAN trust, Caddy's home-peer CIDR and Fire TV IP.
The public DNS updater does not repair changed private LAN addresses.

### Alexa console and diagnostic tools

Console: [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
Build → Endpoint uses HTTPS, Default Region:
`https://movies-api.fradkin.net/alexa`, trusted certificate authority option.
No North America override was populated in the verified configuration.
Interfaces are off; Auto Delegation may remain on. The skill remains unpublished.

ASK CLI 2.30.7 was installed separately at:

```text
/home/afradkin/alexa-diagnostics/node_modules/.bin/ask
```

Do not use the Code tab's "Convert to Alexa-hosted" button to fix this self-hosted
setup. AWS credentials were accidentally configured during ASK setup; they are
not used by Movie Magic or the DNS updater. No AWS resource deployment was
performed in this work. Keep ASK/AWS credential files private.

During troubleshooting, the manifest had `apis.custom.locales: {}` despite a
retrievable model and a successful console build. The user added
`"en-US": {}`, submitted the model through CLI, waited for its build to succeed,
and eventually obtained real request JSON. Do not assume one change alone was
proved to fix every instance of the symptom. The temporary `jukebox movie magic`
invocation was later restored to `movie magic` and verified.

To inspect model status, copy the skill ID from the console into a private shell
variable, without putting the real value in documentation:

```bash
read -r -p "Movie Magic skill ID: " skill_id
~/alexa-diagnostics/node_modules/.bin/ask smapi get-skill-status \
  --skill-id "$skill_id" --resource interactionModel
```

Inspect `interactionModel.en-US.lastUpdateRequest.status`, not just a manifest
update status. Run `ask smapi COMMAND --help` for the installed CLI's arguments;
the simulation command takes `--input-content`, `--device-locale`, `--stage` and
`--session-mode`, not the raw API's `--simulation-request` object. Full simulation
results may contain account data/tokens; don't paste them unfiltered.

## Changes, maintenance and recovery

Before modifying configuration, back up the relevant files privately. The backup
directory already contains timestamped pre-Alexa source/config copies, an Nginx
archive, Caddyfile copy, UFW archive and pre-profile source/environment backups.
List the current files before choosing a restore point; do not assume an example
filename is an actual existing backup. Archives containing `.env` are private.

After an approved `.env` change, restart the app to load it:

```bash
sudo systemctl restart zmoviemagic
systemctl is-active zmoviemagic
```

Keep **one Gunicorn worker** while locks and repeat protection are process-local.
A restart loses in-memory jobs/idempotency history; check the TV before repeating
an uncertain request. Do not use `deploy.sh` or `git reset --hard`: the checkout
contains deployed uncommitted changes and existing edits to `deploy.sh` and
`movies.json`. Do not overwrite the catalog from a test archive.

For a Caddy change, validate the intended file before reloading. For Nginx, run
`sudo nginx -t` before reload. These are maintenance actions, not routine read-only
health checks. Preserve Caddy's internal CA/storage and the authorized ADB key.

To disable automatic profile selection, set `DISNEY_PROFILE_NAME=` and restart
the app. To disable Alexa only, set `ALEXA_ENABLED=false` and restart; LAN access
uses its own controls. These are reversible operational changes when needed.

To stop automatic DNS writes, stop the timer and any already-running service:

```bash
sudo systemctl stop moviemagic-dns.timer moviemagic-dns.service
```

For permanent disabling across boot, use
`sudo systemctl disable --now moviemagic-dns.timer`. To rotate an expiring token,
stop writes, replace its private file using an editor/hidden prompt, retain mode
600, run a read-only check, then start/verify the service and timer. Keep a record
of the new expiry. Never place the token in a command argument or Git.

Before restoring an **old unrestricted Caddy configuration**, close the public
TCP 443 router/firewall exposure first. Restore only reviewed affected files and
preserve LAN access, the movie catalog, secrets and ADB identity. Do not blindly
restore an old public A value: WOW might no longer assign that address to you.

## Verification and supporting documents

- All five requested titles and numbered ambiguity selection passed live checks.
- Automatic `zach` selection and subsequent ordinary launches passed live checks.
- Firewall cleanup retained a working second SSH connection.
- DNS updater: 43 isolated Ubuntu tests passed; live read/check/service/timer passed.
- Profile-patched server suite: **324 passed, 28 upstream SDK deprecation warnings**.
  The DNS tests were run separately in `~/moviemagic-dns-check`, so those 43 are
  not included in that server-suite count.
- Local combined Windows suite: **365 passed, 2 native Nginx checks skipped**.
- A real WAN-address change, a certificate-renewal cycle, future token replacement
  and the broader historical iPad/accessibility/roadmap checks were not exercised
  by these results. Successful command submission alone is never playback proof.

| Need more detail? | Document |
|---|---|
| Current application/network diagrams | [Current architecture](architecture.md) |
| Why Caddy and other choices were made | [Design decisions](architecture-decisions.md) |
| Original baseline and superseded proposals | [Architecture history](architecture-history.md) |
| Plain-English Alexa code/setup | [Alexa setup](alexa-setup.md) |
| DNS operation and credential rotation | [DNS updates](alexa-dns-updates.md) |
| Profile guards, limits and rollback | [Profile selection](disney-profile-selection.md) |
| Caddy routing, tests and rollback | [Caddy notes](../ops/caddy/README.md) |
| Detailed tests and live evidence | [Verification record](alexa-verification.md) |
| Broader security contract | [Security runbook](security-runbook.md) |

The code and documents are in the shared Windows checkout at
`C:\Users\andre\Documents\zmoviemagic`. This runbook and aligned supporting docs
were saved there after the live rollout. A separate documentation-only ZIP can
be copied to Ubuntu and extracted into a review directory; review any existing
documentation edits before replacing them. Copying documentation does not require
an app restart. No documentation task commits or pushes code automatically.

To copy the documentation bundle, use Windows PowerShell:

```powershell
scp "C:\Users\andre\Documents\zmoviemagic\test-results\moviemagic-operations-docs.zip" afradkin@192.168.68.106:~/
```

On Ubuntu, extract it into a separate review folder:

```bash
python3 -m zipfile -e ~/moviemagic-operations-docs.zip ~/moviemagic-docs-review
```

The bundle contains Markdown documentation and a checksum manifest only. It does
not apply code, edit `.env`, alter DNS/firewall rules or restart any service.
The primary guide is `~/moviemagic-docs-review/docs/movie-magic-operations.md`.
