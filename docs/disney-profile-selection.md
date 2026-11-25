# Disney+ profile selection

Live verification follow-up, 2026-11-24: the user applied the reviewed patch and
reported **324 passed, 28 SDK warnings in 14.51s** from the full Ubuntu test suite.
After the enable/validation/restart instructions, they confirmed automatic
selection of `zach` followed by actual movie playback. They also confirmed an
ordinary subsequent launch while already past the profile picker. The feature
is therefore user-verified on the current TV/app/picker. The local-test and
preparation notes below remain historical and do not negate these later results.

The user requested automatic selection of the fixed Disney+ profile `zach`.
It has no PIN, and the user confirms that selecting it manually lets the original
requested movie start. The user supplied a UI hierarchy from the Fire TV showing
`com.disney.disneyplus:id/profilesContent`, the title `Who's watching?`, and the
description `Access zach's profile` directly inside the focused actionable card.
The recognizer matches that actual capture. The private full dump is not included
in source or test packages; tests use a small synthetic equivalent.

## Read the small parts first

`services/disney_profile.py:is_focused_profile()` answers one question: does this
fresh screen identify the intended profile as the focused selectable card?
It requires the Disney+ package, recognized picker container/title, exactly one
matching label, and exactly one focused enabled/clickable/focusable parent card.
It rejects malformed, oversized or entity-declaring XML and conflicting screens.
There are no coordinates, image matching, shell text from profile names or
navigation rules. Case matters: the configured name must match the displayed one.

`FireTVService._select_profile_after_launch()` is the only new device behavior:

1. Do nothing when `DISNEY_PROFILE_NAME` is blank (the default).
2. After delivering the existing movie launch, inspect the UI at most three times.
3. Only when the recognizer matches, send one fixed `input keyevent 23` (Select).
4. Otherwise leave the TV unchanged so the remote remains available.

The helper uses up to eight seconds, within the new API launch's existing total
15-second command budget. Legacy launches retain their contract and use an
additional bounded eight-second best-effort profile check. Both paths keep the
PlaybackService reservation throughout the check. Other launches are rejected as
busy while it runs. This adds inspection time even if the profile picker does not
appear. It is not run from catalog/status/health requests or Alexa help/open.

Each dump uses a backend-generated unique temporary TV file. The fixed command
dumps XML, reads it and removes that same file. A failed or delayed dump cannot
silently reuse an older probe's XML. The transport caps output at 64 KiB and
applies the existing deadline/socket bounds. A remote dump may finish its cleanup
after a local timeout; it sends no selection after that timeout. No raw XML,
profile names, provider IDs or raw exception text are logged by this helper.

The helper never repeats a possibly delivered Select event or movie launch.
Profile errors do not turn an already-delivered movie command into a failed
launch or trigger the legacy reconnect/relaunch path. Logs distinguish
`select_sent`, `not_detected` and `unconfirmed`. A Select command response is not
proof of successful selection or on-screen playback. Existing Alexa speech and
public API evidence remain unchanged.

## Limits that keep this understandable

This first version does not move focus between cards, tap fixed coordinates,
enter a PIN, edit profiles or handle login/household prompts. If `zach` is not
already focused, a Disney+ update changes the UI, the screen is protected, or the
picker appears after the bounded checks finish, use the remote. This matches the
current supplied household picker; additional navigation needs new evidence and
a separately reviewed change. Do not use the physical remote concurrently with
the short inspection/selection, because the displayed screen can change between
its capture and the Select event.

## Local verification and deployment

The tests use fake ADB operations only. Check the new recognition, failures and
concurrency plus existing launch/dispatcher regressions with the intended Python:

```bash
~/moviemagic-alexa-check/bin/python -B -m pytest -q -p no:cacheprovider tests
```

Local verification, 2026-11-24: all 29 new profile cases passed, including actual
FireTVService/PlaybackService admission during a blocked fake profile probe. The
complete Windows regression run passed **365 tests, 2 native Nginx skips and 25
upstream SDK warnings in 20.83s**. Native Caddy checks ran. An initial focused run
found an incorrect test expectation for the existing busy exception wording and
a sandbox-blocked isolated socket test; the assertion was corrected to inspect
the stable error code, and the complete suite passed with approved loopback
access. The recognizer also returned true for the user's supplied XML in a
separate local read-only check. No live profile Select event was sent by these
checks. Ubuntu source compatibility and real TV behavior remain pending.

Before production source changes, inspect working-tree edits, review the patch,
run `git apply --check`, and save the current affected files. Never overwrite
`movies.json`, `deploy.sh`, the DNS updater, real `.env` or ADB credentials from
an archive. A source patch is prepared against the previously deployed Alexa
source and the unchanged baseline FireTVService; mismatches must be reviewed.
Do not use reset/pull/deploy.sh as a shortcut. Run tests before restarting.

During explicitly approved activation, add this to the protected server `.env`:

```dotenv
DISNEY_PROFILE_NAME=zach
```

Keep existing skill/user IDs, secrets, ADB identity, LAN trust and one-worker
settings. Validate settings without constructing the app or contacting the TV:

```bash
cd ~/zmoviemagic
./venv/bin/python -B -c 'from config import Config; from services.firetv_service import FireTVService; FireTVService("192.0.2.1", profile_name=Config.DISNEY_PROFILE_NAME); print("Profile setting valid")'
```

Only then, with explicit approval, restart `zmoviemagic`. Verify on the real TV
that a picker-interrupted movie selects `zach` and continues; also verify an
ordinary launch while Disney+ is already past the picker. Confirm unknown/PIN/
unfocused screens remain unchanged and LAN/iPad use still works. Record actual
on-screen outcomes separately from command-delivery logs. Mocked tests and the
captured XML alone do not complete these live checks.

To disable, clear `DISNEY_PROFILE_NAME` in `.env` and restart the service during
an approved change. The default-off path performs no profile inspection. Source
rollback should restore only the backed-up affected files, preserving catalog,
DNS, credentials and other user edits. No model rebuild or DNS change is needed.
