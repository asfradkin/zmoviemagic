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
MOVIE_NAMES = [
    "Luca",
    "Moana",
    "Moana 2",
    "Coco",
    "Wreck it Ralph",
    "Zootopia",
    "Zenimation",
    "Greatest Showman",
    "Frozen",
    "Encanto",
    "Tangled",
    "Frozen 2",
    "The Aristocats",
    "Melody Time",
    "Wall-E",
    "Mulan",
    "Wreck it Ralph 2",
    "The Aristocats",
    "Fantasia",
    "Fantasia 2000",
    "Snow White",
    "The Lion King",
    "Elemental",
    "Wish",
    "Mary Poppins Returns",
    "The Little Mermaid",
    "Taylor Swift The Era's Tour",
    "Monsters, Inc.",
    "Aladdin",
    "Finding Nemo",
    "Toy Story",
    "Toy Story 2",
    "Toy Story 3",
    "Toy Story 4",
    "Beauty and the Beast",
    "101 Dalmatians",
    "Cars",
    "The Princess and the Frog",
    "Hercules",
    "Tarzan",
    "Cinderella",
    "Robin Hood",
    "Snow White",
    "Peter Pan",
    "Sleeping Beauty",
]

# Optional: Override TMDB poster with your own image URL (title -> URL).
# Use when TMDB returns the wrong poster for a movie.
POSTER_OVERRIDES = {
    # "Luca": "https://example.com/my-luca-poster.jpg",
}

# Optional: Disney+ content IDs for Play on Fire TV (from disneyplus.com URL).
# If a title is missing or empty here, it still shows with a poster but Play is disabled.
DISNEY_IDS = {
    "Luca": "f28b825f-c207-406b-923a-67f85e6d90e0",
    "Moana": "e8896bfa-1052-41f7-ae2e-00255d77cf05",
    "Coco": "ce1ccdca-f468-4960-b67c-026b01ba42ab",
    "Wreck it Ralph": "0cde80b0-5085-447b-b65e-c81a713a90f0",
    "Zootopia": "ee6e9e33-4b25-443f-8431-9c6eeeca0dc2",
    "Zenimation": "53dbe23f-0e40-427c-b2c7-317a873129a8",
    "Frozen": "04c97b72-504b-47f2-9c6f-fe13d9aea82f",
    "Greatest Showman": "9a387ba2-9211-4493-a994-d4b73b8eaf3c",
    "Encanto": "328b0ec7-6e50-4ead-aa7f-c8bb92e6f08a",
    "Tangled": "197d29a0-7a57-4eca-afa9-da1c050c5abe",
    "The Aristocats": "ddf5fd68-acd7-47ae-8632-22aa3b6a4ba8",
    "Frozen 2": "3f9272e2-33f1-47db-bb2e-9aa2c7c85a96",
    "The Lion King": "a3ae7371-39a5-4c0b-a1f2-29a70b372848",
    "Melody Time": "c345991d-d605-4009-81aa-2a6606000e31",
    "Peter Pan": "92d66793-7198-45de-bfb6-84915256d855",
    "Wall-E": "280395a4-d5ef-4dd0-bd09-d91c31593d3d",
    "Mulan": "a89be7cf-d4a6-41e8-9e85-2040be26f401",
    "Wreck it Ralph 2": "4f2c48ef-b3f9-4422-9feb-011a17ff2afb",
    "The Aristocats": "10008701-e963-4aca-802f-e4cf1ee57822",
    "Fantasia": "f08e9233-5325-45ac-a070-134f9725f1fd",
    "Fantasia 2000": "9d43141c-cba4-4562-bba4-30407312014f",
    "Elemental": "8b489955-d30c-45b6-90ee-ae70f92bd431",
    "Moana 2": "a21ee2fc-421e-4839-bfcc-0bf2ba815875",
    "Wish": "d376ee33-6f33-48cf-99bb-2132c3d8183f",
    "Mary Poppins Returns": "4060efe9-4f97-404d-a9d8-1f102f82f5a4",
    "The Little Mermaid": "50d2a9c6-3c88-4329-8ba8-29f87d8ee3b1",
    "Taylor Swift The Eras Tour": "48f31304-ed30-47af-8c7e-83f825129b10",
    "Monsters, Inc.": "3c90b85f-ba5e-4351-be87-e625d5706952",
    "Aladdin": "9b5b36b5-d285-4ab1-9c9d-03a1d6609433",
    "Finding Nemo": "37b62808-2368-4688-9410-2dcf7461e258",
    "Toy Story": "f6174ebf-cb92-453c-a52b-62bb3576e402",
    "Toy Story 2": "55bb8618-baac-449e-9f63-f402f41371a2",
    "Toy Story 3": "95e7b2ce-5f45-4923-976d-b7e9968a7357",
    "Toy Story 4": "97d822a3-7dad-4d85-8350-ce4f8642511e",
    "Beauty and the Beast": "97babebc-7013-455a-b377-aa3d7a6e79c1",
    "101 Dalmatians": "8eed72cc-3c4a-41cf-8e98-44a6b7f8f8d3",
    "Cars": "9c1b0ec2-2e4e-4717-89fb-bdf3a45523df",
    "The Princess and the Frog": "48fd96f1-8e02-4de0-a511-cc3f11fbfefd",
    "Hercules": "ae19dd2f-a945-442b-a18e-d57fa8f5091f",
    "Tarzan": "6246ebb7-7e52-4767-974c-5da108c6644f",
    "Cinderella": "f7272318-0b08-46f5-b89e-284b3e8a7234",
    "Robin Hood": "cd1967ec-90ec-4aa6-9476-809ba8fcf2b2",
    "Sleeping Beauty": "2f365ad5-9a65-410e-b750-947acc66d21e",
    "Snow White": "e98a054e-f385-44e4-84d8-a86d7870dee7",
    # "Frozen": "...",  # add ID from disneyplus.com if you want Play
    # "Iron Man": "...",
}
https://www.disneyplus.com/play/
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


def build_library():
    """Build LIBRARY from MOVIE_NAMES: poster from POSTER_OVERRIDES or TMDB, id from DISNEY_IDS."""
    library = []
    for title in MOVIE_NAMES:
        if title in POSTER_OVERRIDES and POSTER_OVERRIDES[title]:
            poster = POSTER_OVERRIDES[title].strip()
        else:
            poster = fetch_poster_for_title(TMDB_API_KEY, title)
        if not poster:
            poster = ""  # template can show placeholder
        movie_id = DISNEY_IDS.get(title, "")
        library.append({"title": title, "id": movie_id, "poster": poster})
    return library


# Build LIBRARY once at startup (Netflix-style grid with TMDB posters)
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