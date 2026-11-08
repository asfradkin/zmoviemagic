import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

# Load the repository's .env before evaluating the class attributes below.
load_dotenv(BASE_DIR / ".env")


class Config:
    FIRE_TV_IP = os.environ.get("FIRE_TV_IP", "").strip()
    FIRE_TV_PORT = int(os.environ.get("FIRE_TV_PORT", "5555"))
    ADB_TIMEOUT_SECONDS = float(os.environ.get("ADB_TIMEOUT_SECONDS", "5"))

    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
    TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

    MOVIES_FILE = os.environ.get("MOVIES_FILE", str(BASE_DIR / "movies.json"))

    FLASK_SECRET_KEY = os.environ.get(
        "FLASK_SECRET_KEY", "dev-change-in-production"
    )
    PLAYBACK_COOLDOWN_SECONDS = float(
        os.environ.get("PLAY_COOLDOWN_SECONDS", "2")
    )

    DISNEY_PACKAGE = "com.disney.disneyplus"
    INDEX_CACHE_MAX_AGE = 300
    TABLET_API_ENABLED = os.environ.get("TABLET_API_ENABLED", "false").lower() in ("1", "true", "yes")
    PLAYBACK_MAX_RECORDS = int(os.environ.get("PLAYBACK_MAX_RECORDS", "256"))
    PLAYBACK_RETENTION_SECONDS = float(os.environ.get("PLAYBACK_RETENTION_SECONDS", "900"))
    PLAYBACK_SHUTDOWN_GRACE_SECONDS = float(os.environ.get("PLAYBACK_SHUTDOWN_GRACE_SECONDS", "5"))
