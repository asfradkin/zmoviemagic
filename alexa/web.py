"""The one HTTP entrance: verify Amazon and the owner before running the skill."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import os
import re
from threading import BoundedSemaphore

from flask import jsonify, request

from alexa.skill import handle_request
from services.playback_service import APIError


def validate_settings(config):
    """Called before catalog/network work. Disabled installs need no Alexa packages."""
    if not getattr(config, "ALEXA_ENABLED", False):
        return
    if (not re.fullmatch(r"amzn1\.ask\.skill\.[A-Za-z0-9-]{1,128}", getattr(config, "ALEXA_SKILL_ID", ""))
            or not re.fullmatch(r"amzn1\.ask\.account\.[A-Za-z0-9_-]{1,512}", getattr(config, "ALEXA_USER_ID", ""))):
        raise ValueError("Alexa requires the expected skill ID and owner user ID")
    if "REPLACE" in config.ALEXA_SKILL_ID or "REPLACE" in config.ALEXA_USER_ID:
        raise ValueError("Replace Alexa ID placeholders before enabling")
    if os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
        raise ValueError("Debug mode must be off when Alexa is enabled")
    # Check optional dependency compatibility before catalog startup can do I/O.
    from alexa.verification import AmazonVerifier


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON field")
        result[key] = value
    return result


def read_event(raw):
    def reject_constant(value):
        raise ValueError("Nonstandard JSON number")
    event = json.loads(raw, object_pairs_hook=strict_object, parse_constant=reject_constant)
    if not isinstance(event, dict) or event.get("version") != "1.0":
        raise ValueError("Invalid Alexa event")
    command = event.get("request")
    if not isinstance(command, dict) or command.get("type") not in {
            "LaunchRequest", "IntentRequest", "SessionEndedRequest"}:
        raise ValueError("Unsupported Alexa event")
    request_id = command.get("requestId")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 256 or not request_id.isprintable():
        raise ValueError("Invalid request ID")
    if command.get("locale") != "en-US":
        raise ValueError("Unsupported locale")
    if command["type"] == "IntentRequest" and not isinstance(command.get("intent"), dict):
        raise ValueError("Invalid intent")
    stamp = command.get("timestamp")
    if not isinstance(stamp, str) or len(stamp) > 40:
        raise ValueError("Invalid timestamp")
    timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or abs((datetime.now(timezone.utc) - timestamp).total_seconds()) > 150:
        raise ValueError("Expired Alexa event")
    return event


def authorized(event, skill_id, user_id):
    """These IDs are trusted only after the body signature has been verified."""
    context = event.get("context", {})
    session = event.get("session", {})
    if not isinstance(context, dict) or not isinstance(session, dict):
        return False
    system = context.get("System", {})
    if not isinstance(system, dict):
        return False
    for container in (system, session):
        # Normal custom-skill events carry both copies. Reject disagreement.
        application, user = container.get("application", {}), container.get("user", {})
        if not isinstance(application, dict) or not isinstance(user, dict):
            return False
        actual_skill, actual_user = application.get("applicationId"), user.get("userId")
        if (not isinstance(actual_skill, str) or not isinstance(actual_user, str)
                or not hmac.compare_digest(actual_skill.encode(), skill_id.encode())
                or not hmac.compare_digest(actual_user.encode(), user_id.encode())):
            return False
    return True


def register_alexa(app, config):
    """Register only when enabled; use one worker and no queued verifications."""
    if not getattr(config, "ALEXA_ENABLED", False):
        return
    from alexa.verification import AmazonVerifier

    verifier = AmazonVerifier()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="alexa-verify")
    slot = BoundedSemaphore(1)
    # Exposed like the other services, for dependency injection in isolated tests.
    app.extensions["alexa_verifier"] = verifier
    app.extensions["alexa_executor"] = executor
    principal = "alexa-" + sha256((config.ALEXA_SKILL_ID + ":" + config.ALEXA_USER_ID).encode()).hexdigest()[:24]

    @app.post("/alexa", provide_automatic_options=False)
    def alexa_endpoint():
        limiter = app.extensions["rate_limit_service"]
        try:
            limiter.consume("alexa", "all-callers")
        except APIError as error:
            return jsonify(error.body()), 429, {"Retry-After": str(error.retry_after)}
        if (request.query_string or request.environ.get("RAW_URI", request.environ.get("REQUEST_URI", "/alexa")) != "/alexa"):
            return jsonify({"error": "invalid_request"}), 400
        if request.mimetype != "application/json":
            return jsonify({"error": "unsupported_media_type"}), 415
        if request.content_length is not None and request.content_length > 32768:
            return jsonify({"error": "request_too_large"}), 413
        headers = {name: request.headers.get(name, "") for name in ("Signature-256", "SignatureCertChainUrl")}
        if any(not value or len(value) > 2048 or "," in value for value in headers.values()):
            return jsonify({"error": "invalid_request"}), 400
        if not slot.acquire(blocking=False):
            return jsonify({"error": "verification_busy"}), 503, {"Retry-After": "1"}
        future = None
        try:
            raw = request.stream.read(32769)
            if len(raw) > 32768:
                return jsonify({"error": "request_too_large"}), 413
            raw = raw.decode("utf-8")
            event = read_event(raw)
            # The worker can only verify. A late completion can NEVER launch a movie.
            future = executor.submit(verifier.verify_body, headers, raw)
            future.add_done_callback(lambda done: slot.release())
            future.result(timeout=4)
            # Certificate retrieval may have crossed the freshness boundary.
            event = read_event(raw)
            if not authorized(event, config.ALEXA_SKILL_ID, config.ALEXA_USER_ID):
                return jsonify({"error": "forbidden"}), 403
            limiter.consume("request", principal)
            return jsonify(handle_request(event, app.extensions["movie_service"],
                                          app.extensions["playback_service"], principal, limiter))
        except FutureTimeout:
            return jsonify({"error": "verification_unavailable"}), 503
        except APIError as error:
            return jsonify(error.body()), error.status, {"Retry-After": str(error.retry_after)}
        except Exception:
            # Never emit SDK errors, certificate URLs, raw events or account IDs.
            return jsonify({"error": "invalid_request"}), 400
        finally:
            if future is None:
                slot.release()
