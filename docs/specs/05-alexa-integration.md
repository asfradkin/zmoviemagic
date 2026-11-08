# Phase 5 — Alexa integration

Status: implementation specification. Backlog P5.1–P5.5. Prerequisites:
[Phase 2](02-playback-api.md) API and [Phase 4](04-secure-connectivity.md) boundaries.

## 1. Objective and user-facing outcomes

A household member can say "Alexa, ask movie magic to play Luca", or ask the skill
to pause, resume or stop the current Fire TV media. Titles and familiar aliases
resolve in ZMovieMagic, with understandable unknown/ambiguous/offline feedback.
Speech must never claim playback is confirmed from an accepted API request.

## 2. Current-state analysis

No Alexa model, Lambda or transport-control API exists. MovieService currently
resolves only Disney IDs; Phase 2 adds stable-key indexes and deterministic
aliases. FireTVService only launches Disney+ and uses wake/Home before launch.
Pause/resume/stop cannot reuse that sequence. All device logic stays backend-owned.

## 3. Functional requirements

- Provide a private household Alexa Custom Skill with AWS Lambda endpoint.
- Launch by recognized title or alias; backend resolves spoken text and performs
  the launch. Lambda never maps titles to Disney IDs or opens ADB.
- Support explicit pause, resume and stop with separate backend actions.
- Unknown titles prompt a retry; ambiguous titles offer at most three choices.
  Never launch the first candidate automatically.
- Support help, cancel, fallback and session end with no unintended TV command.
- Protect skill invocation by skill-ID validation and API credentials.
- Deduplicate repeated Alexa request IDs and keep HTTP calls bounded.
- Keep iPad behavior independent of the skill's availability.

## 4. Nonfunctional requirements

Use a small Python Lambda and ASK SDK, separate from Flask runtime dependencies.
Select and pin a currently supported AWS Python runtime at implementation time.
Prefer no VPC attachment for this outbound HTTPS-only Lambda unless organizational
policy requires it. No DynamoDB, SQS or persistent voice-user database.

Target handler response under 6 seconds including secret retrieval/network calls.
Alexa allows approximately eight seconds for a full response; a progressive
response does not remove that deadline.
[Amazon's timing documentation](https://www.developer.amazon.com/en-US/docs/alexa/custom-skills/send-the-user-a-progressive-response.html)
supports the budget. Budget a total 3 seconds for resolve + admission HTTP calls,
not 3 seconds per retry; short-circuit when remaining execution time is insufficient.
Use monotonic total-deadline accounting, explicit connect/read timeouts and no
unbounded urllib/SDK retry defaults. Do not wait for actual ADB execution.

## 5. Detailed technical design

### Backend-first extension (P5.1)

Add POST /api/resolve and /api/control with authenticated remote aliases. Resolver
accepts spoken text or key, returns unique key/canonical title or candidates. The
backend remains authoritative even if Alexa supplies a resolved slot ID. Do not
trust that ID as a provider identifier.

Control payload enum pause/resume/stop maps only to fixed Android key events:
pause -> KEYCODE_MEDIA_PAUSE (127), resume -> KEYCODE_MEDIA_PLAY (126), stop ->
KEYCODE_MEDIA_STOP (86). Android defines the separate media key events in the
[KeyEvent reference](https://developer.android.com/reference/android/view/KeyEvent).
Their effect on the actual Fire OS/Disney+ release remains unverified and is a
mandatory P5.2 release gate. Never substitute toggle key 85 for separate actions,
nor Home, force-stop or app relaunch for stop without a revised approved design.

Transport controls do not wake, Home or relaunch Disney+. Use existing connection
logic and shared PlaybackService admission/cooldown/idempotency. Once a key send
starts, uncertain failures are not automatically repeated. Unsupported controls
return 409 action_unavailable before dispatch. Initially capabilities are false;
enable each only after observed target-device validation. Device API success is
still only command_sent; no paused/playing/stopped state inference.

Add status capabilities:
{"play":true,"pause":false,"resume":false,"stop":false}.
If any required control cannot be validated, M5 is incomplete for the requested
scope: document the blocker and seek a design decision rather than silently
shipping a full-support claim.

### Interaction model

Initial locale en-US; invocation "movie magic" is a proposed name requiring console
validation. Model uses custom MOVIE_TITLE slot with canonical names, immutable key
IDs and synonyms exported from backend catalog. Avoid AMAZON.SearchQuery fallback
in the first model; custom slots can still yield unrecognized raw text, which must
be sent to backend resolver. Confirm recognition of titles outside slot list in
the simulator and actual Echo; if insufficient, revise model in a separate task.

| Request / intent | Slots and utterances | Behavior |
|---|---|---|
| LaunchRequest | "open movie magic" | Welcome/help, ask movie; no TV action |
| PlayMovieIntent | MovieTitle: MOVIE_TITLE; "play {MovieTitle}", "watch {MovieTitle}", "put on {MovieTitle}" | Resolve backend then submit key |
| ChooseMovieIntent | Choice: AMAZON.NUMBER; "number {Choice}", "option {Choice}" | Resolve selected prior key again, then submit |
| AMAZON.PauseIntent | standard plus "pause the movie" | Submit pause |
| AMAZON.ResumeIntent | standard plus "resume the movie" | Submit resume |
| AMAZON.StopIntent | standard plus "stop the movie" | Submit stop, end session |
| AMAZON.CancelIntent | standard | Cancel dialog only, no TV action |
| AMAZON.HelpIntent | standard | Examples, no TV action |
| AMAZON.FallbackIntent | standard | Reprompt once; end after second failure |
| SessionEndedRequest | no intent | Cleanup only, no stop command |

Built-in intent customization and utterance conflicts must be checked against
[Amazon's built-in intent guidance](https://developer.amazon.com/en-US/docs/alexa/interaction-model-design/tips-for-using-built-in-intents-for-your-skill.html).
Outside an active skill, bare "pause" may target another Alexa experience. Document
reliable phrasing "ask movie magic to pause"; do not promise global media control.

Minimal model fragment (full model must include all table rows):

```json
{
  "interactionModel":{
    "languageModel":{
      "invocationName":"movie magic",
      "intents":[
        {"name":"PlayMovieIntent","slots":[{"name":"MovieTitle","type":"MOVIE_TITLE"}],
         "samples":["play {MovieTitle}","watch {MovieTitle}"]},
        {"name":"AMAZON.PauseIntent","samples":["pause the movie"]},
        {"name":"AMAZON.ResumeIntent","samples":["resume the movie"]},
        {"name":"AMAZON.StopIntent","samples":["stop the movie"]}
      ],
      "types":[
        {"name":"MOVIE_TITLE","values":[
          {"id":"wall-e","name":{"value":"WALL E","synonyms":["wall ee"]}}
        ]}
      ]
    }
  }
}
```

Export is a build-time hint, never an independent resolution authority. Refresh
after catalog/alias edits; stale models must not allow removed keys to launch.

### Lambda structure and request flow

Use ASK SDK request handlers and a small typed HTTP client:
1. Validate expected skill ID in Lambda trigger and handler configuration; reject
   absent/mismatched IDs before credentials or API calls. Validate request type,
   supported locale, slots and size. Never log full request events.
2. Retrieve edge and backend secrets through narrowly scoped Secrets Manager
   permissions; cache briefly in warm runtime (up to 5 minutes), refresh once on
   auth failure if total budget permits. No credentials in skill model/attributes.
3. Play: send raw bounded MovieTitle.value to resolver. Use unique backend result,
   or save up to three candidate keys/titles in session attributes with expiry
   (2 minutes); ask "Did you mean Moana or Moana 2?" and accept a numbered choice.
4. Choice selection must refer to saved candidates, be in range/not expired, and
   revalidate key with resolver before submission. Do not launch arbitrary
   session-attribute values without backend validation.
5. Submit POST /api/play or /api/control. Idempotency-Key is "alexa-" + SHA-256 of
   Alexa requestId (bounded ASCII). Backend principal remains the machine token.
   Retries of the same incoming event reuse it.
6. On 202 say "I sent a request for Luca to Fire TV" or "I sent the pause request".
   Do not poll ADB completion in the critical path. If response is lost, say the
   request may have reached the TV; no fresh request ID or automatic resubmission.
7. Return an ASK response, escaped PlainText or properly XML-escaped SSML.
   End session after accepted commands; keep it open for clarification/help.

Different Alexa request IDs may represent repeated user utterances; do not dedupe
by title/time heuristics. Shared cooldown limits rapid repeats. In-memory backend
idempotency does not survive restart: never promise exactly-once execution.

Use HTTPS allowlisted API origin and fixed relative paths, certificate validation,
redirects disabled, response size cap 256 KiB, and JSON/schema checks. Error
responses can be HTML at Access. Reject credentials-bearing redirects instead
of following them. No direct Disney calls or network scanning from Lambda.

## 6. API contracts and JSON examples

POST /api/resolve (requires resolve:read) accepts exactly one of query/movie_key,
JSON body at most 4 KiB:

```json
{"query":"wall ee"}
```

200 unique:

```json
{"resolution":"unique","movie":{"key":"wall-e","title":"WALL·E","available":true}}
```

409 ambiguous:

```json
{
  "error":{"code":"ambiguous_movie","message":"Choose a movie.","retryable":false},
  "candidates":[{"key":"moana","title":"Moana"},{"key":"moana-2","title":"Moana 2"}]
}
```

404 movie_not_found when no match. Candidate list is capped at 3; if more, return
a truncated flag and prompt for a more specific title. Query length 1–100 chars.
Unique but unavailable -> 409 movie_unavailable. Resolution never launches.

POST /api/control (requires control:write plus Idempotency-Key):

```json
{"action":"pause"}
```

202:

```json
{
  "request_id":"65b80b5f-4a08-4c26-8d92-f2bb90f9b890",
  "action":"pause",
  "command_state":"queued",
  "playback":{"state":"unknown","evidence":"none"},
  "status_url":"/api/status?request_id=65b80b5f-4a08-4c26-8d92-f2bb90f9b890"
}
```

Job movie_key is null for controls. Error/status rules match Phase 2; action outside
enum is 400 invalid_action; unvalidated capability is 409 action_unavailable.
An expired/unknown device connection is not itself proof a control cannot run;
the worker attempts bounded connection and records evidence.

Alexa event fixture fragment:

```json
{
  "context":{"System":{"application":{"applicationId":"amzn1.ask.skill.EXAMPLE"}}},
  "request":{"type":"IntentRequest","requestId":"amzn1.echo-api.request.EXAMPLE",
    "locale":"en-US","intent":{"name":"PlayMovieIntent",
      "slots":{"MovieTitle":{"name":"MovieTitle","value":"wall ee"}}}}
}
```

Example response:
{"version":"1.0","response":{"outputSpeech":{"type":"PlainText",
"text":"I sent a request for WALL E to Fire TV."},"shouldEndSession":true}}.

## 7. Data models and migration requirements

No database. Model export contains key/name/synonyms only. Session attributes
contain pending candidates, issued_at and failure_count; no tokens, provider IDs,
voice identity or durable watch history. Catalog aliases use Phase 2 fields.

Secrets Manager JSON contains api_base_url, access_client_id, access_client_secret
and backend_token. Store expected skill ID and secret ARN as nonsecret deployment
settings. No actual credentials belong in repository. Backend capability
configuration is explicit, default false, with a hardware validation record.

## 8. File-by-file implementation changes

| File | Future change |
|---|---|
| app.py | Resolve/control endpoints and remote aliases, scopes |
| services/movie_service.py | Public resolver adapter over Phase 2 indexes |
| services/playback_service.py | Generalize job action with same shared admission |
| services/firetv_service.py | Fixed control method and safe delivery outcomes |
| config.py | Capability flags, default disabled |
| alexa/interaction-model/en-US.json | Full intents, slots, examples |
| alexa/lambda_function.py | ASK handlers, dialog and error mapping |
| alexa/api_client.py | Bounded HTTPS, headers, JSON/error checks |
| alexa/requirements.txt | Pinned Lambda-only ASK and AWS dependencies |
| alexa/template.yaml | Reviewable Lambda/IAM/secret references; no secret values |
| tools/export_alexa_slots.py | Deterministic validated public catalog export |
| tests/test_resolution_api.py, test_controls.py | Backend resolution/control contracts |
| alexa/tests/ | Event fixtures, mocked HTTPS/secrets, response assertions |
| docs/alexa-runbook.md | Private setup, utterances, hardware matrix, rollback |

## 9. Dependencies and prerequisites

P5.1 precedes Lambda; P5.2 hardware validation gates claiming all controls. Phase 4
must be deployed and verified before remote end-to-end tests. AWS and Alexa
developer accounts, compatible locale/Echo and suitable invocation name are
required. Confirm supported Lambda runtime/SDK versions and regional endpoint
requirements at implementation time.

[Amazon documents skill-ID validation](https://developer.amazon.com/en-US/docs/alexa/custom-skills/handle-requests-sent-by-alexa.html)
and [Lambda trigger configuration](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-an-aws-lambda-function.html).
Restrict Lambda invoke permission to Alexa Skills Kit and the expected skill.

## 10. Security and failure handling

Map unknown/ambiguous to friendly clarification, unavailable to "That movie isn't
available", 429 to "Please wait a moment", auth errors to caregiver setup notice,
and edge/network timeout to "I couldn't confirm the request. Please check the TV."
No exception text, internal hostname, token or raw slot speech in logs.

Retry read-only resolution at most once within total budget; do not automatically
retry mutation after timeout. Missing slots prompt once, then end. Cancel/session
end never stop the TV; explicit StopIntent does. Incoming skill events require
validated skill identity; backend credentials alone are not permission to accept
arbitrary Lambda events. APIs retain all Phase 4 controls and body limits.

## 11. Automated testing requirements

Test title/alias/Unicode/unknown/ambiguous/unavailable resolution, candidate expiry,
number selection and stale catalog. Verify every intent, Launch/SessionEnded,
missing slot, wrong skill ID, bad locale, help/cancel/fallback and XML escaping.
Wrong skill IDs cause zero network calls.

Mock Secrets Manager, HTTP and clock. Test 202 queued speech, every API error,
Access HTML, redirects, SSL/network failures, exhausted deadline, repeated events,
warm secret caching and refresh. Assert no ADB imports in Lambda and no provider
IDs in model/export. Backend tests prove fixed event mappings, no wake/Home for
controls, serialization against legacy play, unsupported capabilities and
no resend after ambiguous control delivery. Interaction model build/validation
is required in the developer console under approved skill changes.

## 12. Measurable acceptance criteria

- Ten curated title/alias utterances, including WALL E/Frozen II variants, resolve
  to expected backend keys in automated fixtures and actual Echo checks.
- Ambiguous/unknown utterances dispatch zero commands before clarification.
- Every supported control passes three observed trials on the actual TV version;
  unverified controls remain disabled and block full M5 completion.
- One repeated event/requestId produces at most one job within retention window.
- Handler returns under 6 seconds in injected slow-network budget tests.
- Speech describes requests, never confirmed playback from 202 or ADB success.
- Skill-ID/auth failures and cloud outages leave local iPad launching functional.

## 13. Deployment, verification and rollback

Prepare model, Lambda package, IAM/secret references and tests before approval.
Obtain explicit approval for AWS resources, credentials, skill configuration and
live Fire TV tests. Validate controls locally first, then deploy a versioned Lambda
and private development skill; enable skill-ID-verified trigger; configure
credential references; test denials, clarification and accepted commands.
Use actual Echo in addition to simulator. Record Fire OS/Disney+ version.

Rollback Lambda alias to previous version or disable private skill; revoke API/
Access credentials when needed. Backend endpoints can remain for iPad; disable
unreliable control capabilities independently. Preserve catalog keys and legacy
route. No public skill publication is included or authorized.

## 14. Out of scope and unresolved decisions

No Video Skill/Smart Home Skill, streaming to Echo, account linking, global
"Alexa play" interception, voice profiles, progress resume, seek or content purchase.
Resume means send media-play to the current media session, not relaunch at a saved
position. Confirm invocation name/locale, stop behavior, private-skill usability
for household accounts and current console requirements. If media keys are ignored,
choose a revised backend control mechanism only after a separate feasibility review.
