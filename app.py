import os

from flask import Flask, jsonify, render_template

from config import Config
from services.firetv_service import FireTVService
from services.movie_service import MovieService
from services.playback_service import CooldownError, PlaybackService


def create_app(config=Config):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY

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
    )
    playback_service = PlaybackService(
        firetv_service=firetv_service,
        cooldown_seconds=config.PLAYBACK_COOLDOWN_SECONDS,
    )

    app.extensions["movie_service"] = movie_service
    app.extensions["firetv_service"] = firetv_service
    app.extensions["playback_service"] = playback_service

    @app.route("/")
    def index():
        """Serve the existing movie poster grid."""
        response = app.make_response(
            render_template("index.html", movies=movie_service.library())
        )
        response.headers["Cache-Control"] = (
            f"public, max-age={config.INDEX_CACHE_MAX_AGE}"
        )
        return response

    @app.route("/play/<video_id>")
    def play(video_id):
        """Retain the existing Disney+ playback endpoint for the iPad UI."""
        try:
            result = playback_service.play(video_id)
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
