# Phase 2 observed verification — 2026-11-07

Local implementation only. No commit, push, deploy, production configuration
change, service restart or live-TV test was performed.

## Executed tests

The original baseline passed: **26 passed in 0.69 seconds**.
The final expanded Python suite passed:

```text
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider --tb=short
113 passed in 3.78s
```

TEMP/TMP pointed to `.venv/pytest-temp`. Execution outside the sandbox was
approved for the original isolated 127.0.0.1 socket-timeout test. The initial
sandbox-only attempts hit temporary-directory/socket permission errors; those
attempts were not green runs. No production device was involved.

JavaScript tests use Node's built-in test runner and injected fetch/timers:

```text
node --test tests/tablet.test.cjs
```

They cover successful delivery polling, duplicate taps, network failure, late
acceptance after timeout, bounded polling, busy responses, missing status,
unknown/failed outcomes, reload-only GET recovery, expired/malformed saved
records, denied storage, corrupt/denied DOM initialization and unexpected server
errors. All 13 tests passed; none were skipped.

`git diff --check` passed (Git also emitted informational LF/CRLF conversion
warnings). No dependencies were installed during this implementation.

## Performance and catalog audit

The 100-row Flask-client benchmark admitted 50 jobs against a mocked Fire TV:

| Measurement | Observed p95 | Specification target |
|---|---:|---:|
| Admission | 0.87 ms | <250 ms |
| Status | 0.91 ms | <250 ms |

This measures local in-process HTTP handling, excluding browser/network and
production host scheduling. It is not a production latency measurement.

A separate read-only audit against both original backups confirmed:

- 44 rows and 44 unique approved keys.
- Every original field value and row order preserved; only keys/aliases added.
- Both backup files match the original catalog byte for byte.
- Public catalog serializes to 7,195 UTF-8 bytes, below the 256 KiB limit.
- All 44 entries have syntactically valid provider IDs; no provider ID appears
  in the public catalog. Availability means catalog eligibility, not service or
  playback verification.
- The shared Aristocats title remains explicitly ambiguous.

## Remaining release verification

Source/fixture checks and fetch-stub tests passed; **no visual browser/iPad pass
is claimed**. Computer Use inventory initially timed out, then recovered, but
window inspection was stopped because the tool could not confidently verify
the browser URL. No further UI automation was issued.

The user reports current iPadOS/Safari on a several-year-old iPad. Exact model,
OS/browser version, portrait/landscape rendering, 200% zoom, focus/keyboard,
VoiceOver and physical touch checks remain pending. The
[runbook](phase-2-runbook.md) documents these gates and the staged rollout and
rollback procedure. Live-TV checks and production rollout need separate
approval. `TABLET_API_ENABLED` remains default-off; the existing iPad client
and legacy endpoint remain available.
