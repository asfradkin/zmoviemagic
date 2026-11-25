# Automatic DNS updates for Movie Magic

Current household status, November 24, 2026: all 43 updater tests passed on Ubuntu;
the private-token live check reported the A record already current. The installed
service completed successfully and the enabled timer showed `active (waiting)`
with its next five-minute trigger. Actual changed-WAN-IP recovery remains untested.
See [everyday operation and troubleshooting](movie-magic-operations.md). Sections
below describe the code, original preparation and future maintenance/reinstallation.

This small standalone tool keeps the existing `movies-api.fradkin.net` A record
pointing to the server's public IPv4 address. It uses only Python's standard
library. Flask, Gunicorn, the catalog and TV commands do not import it.

The user requested this follow-up after real Alexa/TV playback and ambiguity
checks passed. The former TP-Link CNAME failed CAA checks, so the working setup
uses a direct GoDaddy A record. GoDaddy now supports DNS API access for an account
holding one domain. No new DDNS provider or nameserver change is required.

## What the code does

Read `tools/update_alexa_dns.py`, especially `sync_dns()`:

1. Read only the existing A record named `movies-api` from GoDaddy.
2. Require exactly one result with the expected name/type and a valid ID/TTL.
3. Ask ipify for the server's public IPv4 address, without sending it the token.
4. If the addresses match, stop without writing.
5. In the default check mode, print the proposed change and stop.
6. With `--apply`, replace only that record by its ID, preserving name/type/TTL.

The script has no create/delete operations or whole-zone update. Website, mail,
other records, nameservers and the private LAN hostname are outside its fixed
write path. The token itself grants DNS access more broadly than this script:
store it privately and revoke it if compromised. Do not give it nameserver,
domain-purchase or unrelated permissions.

It refuses redirects, uses normal HTTPS certificate checks, disables environment
proxies, limits responses to 128 KiB and sets a five-second socket timeout. Error
messages omit token values and API response bodies. It never immediately repeats
a failed PUT. A later scheduled run first reads the record again to reconcile an
update that might have succeeded before a lost response. An unconfirmed response
does not prove the write failed. Public DNS caches can retain an old answer until
the existing TTL expires; checking every five minutes does not eliminate that.

The supplied systemd service provides a 40-second process limit, including DNS
resolution and slow responses, and runs as `afradkin` with a read-only filesystem.
A timer runs it roughly every five minutes, with up to 15 seconds of jitter. The
same service cannot overlap itself. Run manual checks through `timeout 40s`.
Do not run simultaneous manual `--apply` commands. No app restart is needed.

## Isolated verification before installation

The tests mock both external services; no GoDaddy, ipify or TV calls are made.
Use the established Ubuntu test environment from the source-bundle directory:

```bash
~/moviemagic-alexa-check/bin/python -B -m pytest -q -p no:cacheprovider tests/test_alexa_dns.py
```

These tests verify the single-record scope and TTL preservation, missing/duplicate
and unexpected record rejection, public-IP validation, no write in check mode,
no write for unchanged IPs, credential separation, bounded responses, redirection
and error redaction, and no immediate retry of an uncertain write. They do not
establish live API access, actual timer operation or behavior after a WAN change.

Local verification, 2026-11-24: the complete suite ran with the intended Windows
development interpreter: **336 passed, 2 skipped, 25 upstream SDK warnings in
23.21s**. All 43 updater cases passed as part of that run. The two skips are the
native Nginx checks unavailable on Windows; native Caddy checks ran. An initial
sandbox-restricted full run was interrupted after loopback fixture errors; the
successful run used approved local loopback access. No real external API or TV
was contacted. Ubuntu tests and live read-only API access remain pending.

## Store the credential privately

Create a PAT in the GoDaddy portal with `domains.domain:read` and
`domains.dns:update`. Save its expiry and the replacement procedure in your
password manager. GoDaddy currently allows expiry up to one year; this requires
periodic token replacement. No expiry reminder has been scheduled automatically.

On Ubuntu, enter the token using a hidden prompt. This avoids shell history and
keeps it outside the repository. The exclusive-create mode refuses to overwrite
an existing token; rotation is an explicit operation.

```bash
python3 - <<'PY'
from getpass import getpass
import os
from pathlib import Path

directory = Path.home() / '.config/moviemagic-dns'
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
directory.chmod(0o700)
token = getpass('Paste GoDaddy token (hidden): ').strip()
if not token or any(c.isspace() for c in token):
    raise SystemExit('Expected one nonempty token')
path = directory / 'token'
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, 'w') as handle:
    handle.write(token + '\n')
print('Token saved privately.')
PY
```

Do not paste the token, `.ask/cli_config`, AWS files or application `.env` into
chat. A configured AWS CLI profile is unrelated to this updater.

## Read-only live check

After isolated tests pass, review and install only the new tool and templates;
do not reapply the old Alexa patch or overwrite existing app/catalog/user edits.
The established app root is `/home/afradkin/zmoviemagic`.

```bash
cd ~/zmoviemagic
timeout 40s python3 -B tools/update_alexa_dns.py
```

An unchanged IP prints `DNS already current`. A differing IP prints `CHECK ONLY`
with current/proposed addresses. No DNS write occurs in either case. Inspect
that result before approving the first live update and timer activation. If the
API rejects the request, fix permission/eligibility/expiry first; do not broaden
the token or migrate DNS blindly.

## Approved activation and checks

The following production actions require explicit user approval. This file alone
does not authorize them. Before first activation, save the existing A record's
value and TTL privately and review the dry-run output. If changing an existing
timer/service, back up and review its current files before replacing them.

```bash
sudo install -m 644 ops/systemd/moviemagic-dns.service.example /etc/systemd/system/moviemagic-dns.service
sudo install -m 644 ops/systemd/moviemagic-dns.timer.example /etc/systemd/system/moviemagic-dns.timer
sudo systemd-analyze verify /etc/systemd/system/moviemagic-dns.service /etc/systemd/system/moviemagic-dns.timer
sudo systemctl daemon-reload
sudo systemctl start moviemagic-dns.service
sudo systemctl status moviemagic-dns.service --no-pager
sudo systemctl enable --now moviemagic-dns.timer
systemctl list-timers moviemagic-dns.timer --no-pager
sudo journalctl -u moviemagic-dns.service -n 15 --no-pager
```

A oneshot service normally becomes inactive after a successful run. Inspect
`Result=success` and its journal, rather than expecting it to stay active.
Verify the record publicly and retest Alexa after activation. A scheduled success
without a changed IP does not prove a real WAN-change recovery; record that later
when an actual change occurs. No reboot or connection interruption is needed to
prove the basic dry-run/API check.

## Stop, rotate and recover

Stop automatic updates with `sudo systemctl disable --now moviemagic-dns.timer`.
An already-running service can finish; stop it too before changing credentials
or performing a conflicting manual DNS change. Revocation at GoDaddy immediately
invalidates a compromised token. Replace the token file privately, maintain mode
600, run a check, then start the service and timer after approval. Never put the
token in a command argument or turn on HTTP debug logging.

If restoring an old A value, first confirm it is still the correct public WAN
address; blindly restoring a previous ISP address can redirect Alexa elsewhere.
DNS downtime does not remove local iPad access or change the Fire TV address.
Only TCP 443 should remain forwarded in Deco; changing the public IP does not
require reopening app/ADB ports.

References: [GoDaddy DNS API](https://developer.godaddy.com/en/docs/api-users/domains/manage/dns),
[token permissions](https://developer.godaddy.com/en/docs/api-users/auth), and
[ipify IPv4 lookup](https://www.ipify.org/).
