import logging
import json
import os
from datetime import timedelta

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge, HTTPException

from config import Config
from services.auth_service import AuthService
from services.rate_limit_service import RateLimitService
from services.firetv_service import FireTVService
from services.movie_service import MovieService
from services.playback_service import APIError, CooldownError, PlaybackService


def create_app(config=Config):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY
    # Validate security settings before catalog refresh or any other network work.
    auth = AuthService(config)
    lifetime = getattr(config, "SESSION_LIFETIME_SECONDS", 43200)
    if not 60 <= lifetime <= 43200:
        raise ValueError("Session lifetime must be between 60 seconds and 12 hours")
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=False, SESSION_REFRESH_EACH_REQUEST=False,
                      PERMANENT_SESSION_LIFETIME=timedelta(seconds=lifetime))
    limiter = RateLimitService(max_buckets=getattr(config, "RATE_LIMIT_MAX_BUCKETS", 1024),
                               idle_seconds=getattr(config, "RATE_LIMIT_IDLE_SECONDS", 900))
    app.extensions["auth_service"] = auth
    app.extensions["rate_limit_service"] = limiter

    if not config.TMDB_API_KEY:
        raise SystemExit(
            "TMDB_API_KEY is not set. Copy .env.example to .env and add your "
            "key (see README)."
        )

    movie_service = MovieService(
        movies_file=config.MOVIES_FILE,
        tmdb_api_key=config.TMDB_API_KEY,
        tmdb_image_base=config.TMDB_IMAGE_BASE,
        tmdb_search_url=config.TMDB_SEARCH_URL,
    )
    movie_service.load()
    movie_service.refresh_missing_posters()

    firetv_service = FireTVService(
        host=config.FIRE_TV_IP,
        port=config.FIRE_TV_PORT,
        disney_package=config.DISNEY_PACKAGE,
        timeout_seconds=config.ADB_TIMEOUT_SECONDS,
    )
    playback_service = PlaybackService(
        firetv_service=firetv_service,
        cooldown_seconds=config.PLAYBACK_COOLDOWN_SECONDS,
        movie_service=movie_service,
        max_records=getattr(config, "PLAYBACK_MAX_RECORDS", 256),
        retention_seconds=getattr(config, "PLAYBACK_RETENTION_SECONDS", 900),
        shutdown_grace=getattr(config, "PLAYBACK_SHUTDOWN_GRACE_SECONDS", 5),
    )

    app.extensions["movie_service"] = movie_service
    app.extensions["firetv_service"] = firetv_service
    app.extensions["playback_service"] = playback_service
    app.config["TABLET_API_ENABLED"] = getattr(config, "TABLET_API_ENABLED", False)

    @app.errorhandler(APIError)
    def api_error(error):
        response = jsonify(error.body())
        response.status_code = error.status
        if error.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if error.retry_after:
            response.headers["Retry-After"] = str(error.retry_after)
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if not request.path.startswith(("/api/", "/remote/")):
            return error
        code = {413: "request_too_large", 415: "unsupported_media_type",
                405: "method_not_allowed", 404: "not_found"}.get(error.code, "invalid_request")
        response = jsonify({"error": {"code": code, "message": error.name, "retryable": False}})
        response.status_code = error.code
        if error.code == 405:
            response.headers["Allow"] = ", ".join(error.valid_methods)
        return response

    @app.after_request
    def api_cache_policy(response):
        if request.path.startswith(("/api/", "/remote/", "/play/")):
            response.headers["Cache-Control"] = "no-store"
        if request.path == "/":
            response.headers["Cache-Control"] = "private, no-store"
        if request.path.startswith("/remote/"):
            # Machine routes neither issue nor refresh browser cookies.
            response.headers.pop("Set-Cookie", None)
        return response

    @app.before_request
    def local_api_boundary():
        auth.check_host()
        remote = request.path.startswith("/remote/")
        if remote:
            limiter.consume("proxy", "origin")
            if not auth.remote_enabled:
                raise APIError("not_found", 404, "Not found.")
        if request.path == "/" or request.path.startswith("/play/"):
            auth.require_lan()
            auth.check_origin()
            return
        if not remote and not request.path.startswith("/api/"):
            auth.require_lan()
            return
        path = request.path.removeprefix("/remote") if remote else request.path
        scope = {"/api/movies": "catalog:read", "/api/play": "playback:write",
                 "/api/status": "status:read"}.get(path)
        if scope is None:
            raise APIError("not_found", 404, "Not found.")
        if remote or "Authorization" in request.headers:
            g.principal = auth.bearer(scope, limiter)
        else:
            g.principal = auth.browser(command=path == "/api/play")
        limiter.consume("request", g.principal)
        if remote and request.method not in ({"POST"} if path == "/api/play" else {"GET"}):
            raise APIError("method_not_allowed", 405, "Method not allowed.")
        if request.method in ("GET", "HEAD") and (request.content_length or request.environ.get("HTTP_TRANSFER_ENCODING")):
            raise APIError("invalid_request", 400, "Read requests must not contain a body.")

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if not request.path.startswith(("/api/", "/remote/")):
            raise error
        # Never serialize exception text, headers or payloads into remote errors/logs.
        app.logger.error("API failure type=%s", type(error).__name__)
        return jsonify({"error": {"code": "internal_error", "message": "Request failed.", "retryable": False}}), 500

    @app.get("/remote/api/movies", provide_automatic_options=False)
    @app.get("/api/movies")
    def api_movies():
        if request.args:
            raise APIError("invalid_request", 400, "This endpoint does not accept query fields.")
        if not movie_service.catalog_available:
            raise APIError("catalog_unavailable", 503, "The movie catalog is unavailable.")
        return jsonify(movie_service.public_catalog())

    @app.post("/remote/api/play", provide_automatic_options=False)
    @app.post("/api/play")
    def api_play():
        if request.args:
            raise APIError("invalid_request", 400, "This endpoint does not accept query fields.")
        if request.content_length is not None and request.content_length > 4096:
            raise RequestEntityTooLarge()
        if request.mimetype != "application/json":
            raise APIError("unsupported_media_type", 415, "Use application/json.")
        # Limit reads even if Content-Length is absent or transfer encoding is used.
        raw_body = request.stream.read(4097)
        if len(raw_body) > 4096:
            raise RequestEntityTooLarge()
        def strict_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Repeated JSON field")
                result[key] = value
            return result
        def reject_constant(value):
            raise ValueError("Nonstandard JSON constant")
        try:
            body = json.loads(raw_body.decode("utf-8"), object_pairs_hook=strict_object,
                              parse_constant=reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise APIError("invalid_request", 400, "A valid JSON object is required.") from None
        if not isinstance(body, dict) or set(body) != {"movie_key"}:
            raise APIError("invalid_request", 400, "Provide only movie_key.")
        result = playback_service.submit_play(body["movie_key"], g.principal, request.headers.get("Idempotency-Key"),
                                              admit=lambda: limiter.consume("command", g.principal))
        response = jsonify(result)
        response.status_code = 202
        response.headers["Location"] = result["status_url"]
        return response

    @app.get("/remote/api/status", provide_automatic_options=False)
    @app.get("/api/status")
    def api_status():
        if set(request.args) - {"request_id"} or len(request.args.getlist("request_id")) > 1:
            raise APIError("invalid_request", 400, "Unexpected or repeated query fields.")
        request_id = request.args.get("request_id")
        if request_id is not None and (not request_id or len(request_id) > 128):
            raise APIError("invalid_request", 400, "Invalid request ID.")
        result = playback_service.status(request_id, g.principal)
        if g.principal != "lan-household":
            result.pop("device", None)
        return jsonify(result)

    @app.get("/health")
    def health():
        """Report web-process health without contacting or waking the TV."""
        response = jsonify({"status": "ok"})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/")
    def index():
        """Serve the existing movie poster grid."""
        csrf_token = auth.grant_session()
        api_enabled = app.config["TABLET_API_ENABLED"]
        if api_enabled:
            if movie_service.catalog_available:
                movies = movie_service.public_catalog()["movies"]
            else:
                # A broken catalog must not silently switch a POST client to legacy GET.
                movies = []
        else:
            movies = movie_service.library()
        response = app.make_response(render_template("index.html", movies=movies, tablet_api_enabled=api_enabled,
                                                     csrf_token=csrf_token))
        return response

    @app.route("/play/<video_id>")
    def play(video_id):
        """Retain the existing Disney+ playback endpoint for the iPad UI."""
        try:
            limiter.consume("request", "lan-household")
            result = playback_service.play(video_id, admit=lambda: limiter.consume("command", "lan-household"))
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        except CooldownError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 429
        except PermissionError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 403
        except RuntimeError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 500

    return app


app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5000, debug=debug)
