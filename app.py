from flask import Flask, render_template, request, jsonify
from ppadb.client import Client as AdbClient
from dotenv import load_dotenv
import subprocess
import os
import re
import shutil
import urllib.request
import urllib.parse
import json
import time
from functools import lru_cache

load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION (from .env) ---
FIRE_TV_IP = os.environ.get("FIRE_TV_IP", "").strip()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()

# Flask secret for session/signing (set in .env for production)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-change-in-production")

if not TMDB_API_KEY:
    raise SystemExit("TMDB_API_KEY is not set. Copy .env.example to .env and add your key (see README).")

# Disney+ content IDs are alphanumeric, hyphen, underscore; reject anything else to avoid injection
VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Optional: minimum seconds between /play requests (0 = disabled)
PLAY_COOLDOWN_SECONDS = int(os.environ.get("PLAY_COOLDOWN_SECONDS", "2"))
_last_play_time = 0.0

# Simple list of movie names; posters are fetched from TMDB at startup.

# JSON file for movie data (title, id, poster)
MOVIES_JSON = "movies.json"

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"


def fetch_poster_for_title(api_key, title):
    """Query TMDB search and return poster URL for the first result, or None."""
    try:
        url = f"{TMDB_SEARCH_URL}?api_key={api_key}&query={urllib.parse.quote(title)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results") or []
        if not results:
            return None
        poster_path = results[0].get("poster_path")
        if not poster_path:
            return None
        return TMDB_IMAGE_BASE + poster_path
    except Exception as e:
        print(f"TMDB fetch failed for '{title}': {e}")
        return None

def load_movies():
    """Load movies from JSON file."""
    if not os.path.exists(MOVIES_JSON):
        return []
    try:
        with open(MOVIES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {MOVIES_JSON}: {e}")
        return []

def save_movies(movies):
    """Save movies to JSON file."""
    try:
        with open(MOVIES_JSON, "w", encoding="utf-8") as f:
            json.dump(movies, f, indent=2)
    except Exception as e:
        print(f"Error saving {MOVIES_JSON}: {e}")

def build_library():
    """
    Load library from JSON.
    If a movie has no poster, fetch it from TMDB and update the JSON file (caching).
    """
    movies = load_movies()
    updated = False
    
    library = []
    
    for movie in movies:
        title = movie.get("title")
        poster = movie.get("poster")
        
        # If no poster is cached, fetch it
        if not poster:
            print(f"Fetching poster for: {title}")
            poster = fetch_poster_for_title(TMDB_API_KEY, title)
            if poster:
                movie["poster"] = poster
                updated = True
            else:
                 movie["poster"] = "" # Avoid re-fetching failed ones immediately or handle as needed
        
        library.append({
            "title": title,
            "id": movie.get("id", ""),
            "poster": movie.get("poster", "")
        })
    
    if updated:
        print("Updating movies.json with new posters...")
        save_movies(movies)
        
    return library


# Build LIBRARY once at startup (loads from JSON, fetches missing posters, saves back to JSON)
LIBRARY = build_library()


@lru_cache(maxsize=1)
def find_adb():
    """Return path to adb executable, or None if not found. Cached after first call."""
    # First try PATH
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path
    # Common Windows locations for Android SDK platform-tools
    if os.name == "nt":
        for base in [
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ANDROID_HOME", ""),
            os.environ.get("ANDROID_SDK_ROOT", ""),
        ]:
            if base:
                candidate = os.path.join(base, "Android", "Sdk", "platform-tools", "adb.exe")
                if os.path.isfile(candidate):
                    return candidate
    return None

def get_device():
    """Connects to ADB and returns (device, None) or (None, error_message)."""
    adb_path = find_adb()
    if not adb_path:
        msg = "ADB not found. Install Android Platform Tools and add adb to PATH (or set ANDROID_HOME)."
        print(f"ADB Error: {msg}")
        return None, msg

    try:
        # Start ADB server if not running (use full path so subprocess can find it)
        subprocess.run([adb_path, "start-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        client = AdbClient(host="127.0.0.1", port=5037)
        device = client.device(f"{FIRE_TV_IP}:5555")

        if not device:
            client.remote_connect(FIRE_TV_IP, 5555)
            device = client.device(f"{FIRE_TV_IP}:5555")

        return device, None
    except Exception as e:
        print(f"ADB Error: {e}")
        return None, str(e)

# Allow browsers to cache the index page briefly (library is static until app restart)
INDEX_CACHE_MAX_AGE = 300  # seconds

@app.route('/')
def index():
    """Serves the movie poster grid"""
    resp = app.make_response(render_template('index.html', movies=LIBRARY))
    resp.headers["Cache-Control"] = f"public, max-age={INDEX_CACHE_MAX_AGE}"
    return resp

@app.route('/play/<video_id>')
def play(video_id):
    """Deep links the video on Fire TV"""
    global _last_play_time
    if not video_id or not VIDEO_ID_PATTERN.match(video_id):
        return jsonify({"status": "error", "message": "Invalid video ID"}), 400

    if PLAY_COOLDOWN_SECONDS > 0:
        now = time.monotonic()
        if now - _last_play_time < PLAY_COOLDOWN_SECONDS:
            return jsonify({
                "status": "error",
                "message": f"Please wait {PLAY_COOLDOWN_SECONDS} seconds between plays.",
            }), 429
        _last_play_time = now

    device, err = get_device()

    if not device:
        return jsonify({"status": "error", "message": err or "Could not connect to Fire TV"}), 500

    print(f"Launching ID: {video_id}")

    try:
        # Wake up TV
        device.shell("input keyevent 224")  # Wake
        device.shell("input keyevent 3")    # Home

        # Launch Deep Link (startTime=0 asks to start from beginning; app may ignore if unsupported)
        url = f"https://www.disneyplus.com/play/{video_id}?startTime=0"
        cmd = f'am start -a android.intent.action.VIEW -d "{url}" com.disney.disneyplus'
        device.shell(cmd)

        return jsonify({"status": "success", "message": f"Playing video {video_id}"})
    except RuntimeError as e:
        err_msg = str(e)
        if "unauthorized" in err_msg.lower():
            message = (
                "Fire TV has not authorized this computer for ADB. "
                "On your Fire TV screen, look for an 'Allow USB debugging?' (or similar) prompt and select Allow. "
                "If you don't see it, run 'adb kill-server' in a terminal, then try again."
            )
            return jsonify({"status": "error", "message": message}), 403
        return jsonify({"status": "error", "message": err_msg}), 500

if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    # Host='0.0.0.0' makes it accessible to other devices on your network
    app.run(host='0.0.0.0', port=5000, debug=debug)