# Repository rules

These rules apply throughout ZMovieMagic. See [PLANS.md](PLANS.md),
[architecture](docs/architecture.md), and the phase specifications before changing behavior.

- Keep Flask, the app factory, and MovieService / PlaybackService / FireTVService boundaries. Put catalog resolution in MovieService, command coordination in PlaybackService, and ADB operations in FireTVService. Routes and external clients must not construct shell commands.
- Preserve the existing iPad grid, movie catalog entries, Disney+ deep links, wake/Home behavior, authorized ADB identity, and legacy `/play/<video_id>` contract until the documented retirement gate is approved. Legacy valid IDs currently pass through even when absent from the catalog.
- Treat application movie keys as immutable. Keep provider IDs private to backend storage and the temporary legacy interface. Never regenerate keys after a title change or silently choose between ambiguous aliases.
- Distinguish request acceptance, ADB command delivery, and actual playback. Command delivery never proves playback. New UI, logs, speech, and APIs must describe the evidence available.
- Keep one Gunicorn worker while locks, cooldowns, jobs, and idempotency are process-local. Do not introduce multiple workers, a database, a broker, or a framework rewrite without a justified design revision.
- Bound network operations and command admission. Serialize all Fire TV actions, including legacy requests. Do not automatically repeat an ambiguously delivered command or retry a timed-out launch.
- Validate all input before side effects. Use fixed command templates and allowlisted actions. Do not accept arbitrary shell text, device addresses, package names, or provider URLs from clients.
- Never expose ADB device port 5555, ADB server port 5037, or an unauthenticated control endpoint to the internet. Remote access requires both approved edge protection and backend authentication.
- Keep secrets, `.env`, tunnel credentials, tokens, session keys, and ADB private keys out of source control and logs. Use placeholders in examples. Do not read real secrets merely to document configuration.
- Use existing Python conventions, Flask JSON responses, pytest fixtures, mocked Fire TV operations, and temporary catalog files. Do not contact real ADB, TMDB, AWS, or production services in automated tests; explicit isolated loopback tests are allowed.
- Before a behavior change, inspect current tests and working-tree changes. Preserve user edits. Add meaningful tests for contracts, migrations, concurrency, failures, authentication, and compatibility as required by the relevant specification.
- Run `python -B -m pytest -q -p no:cacheprovider` with the intended interpreter. Report missing tools or dependencies honestly; test inspection is not a passing run. Browser changes also require documented accessibility and iPad checks.
- Review JSON migration dry runs and backups before applying them. Preserve titles, posters, provider IDs, and unknown catalog fields. Never rewrite the production catalog at startup as a schema migration.
- Maintain plain JavaScript/Jinja progressive enhancement and accessible controls. Prevent accidental launches without unnecessary steps for the primary user.
- Production configuration changes, service restarts, tunnel/DNS changes, deployment, and live-device verification require explicit user approval. Specifications or coding requests alone do not authorize them.
- Do not commit or push unless requested. Inspect deployment scripts/workflows first: a push may trigger production deployment. Never run `deploy.sh` or a production `git reset --hard` as routine verification.
- During the current specification-only task, change documentation only. Future feature implementation needs a separate request; this file does not authorize it.
