from flask import Flask, render_template, request, jsonify
from ppadb.client import Client as AdbClient
from dotenv import load_dotenv
import subprocess
import os
import shutil
import urllib.request
import urllib.parse
import json

load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION (from .env) ---
FIRE_TV_IP = os.environ.get("FIRE_TV_IP", "").strip()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()

if not TMDB_API_KEY:
    raise SystemExit("TMDB_API_KEY is not set. Copy .env.example to .env and add your key (see README).")

# Simple list of movie names; posters are fetched from TMDB at startup.
MOVIE_NAMES = [
    "Luca",
    "Moana",
    "Coco",
    "Wreck it Ralph",
    "Zootopia",
    "Zenimation",
    "Frozen",
    "Encanto",
    "Tangled",
    "Frozen 2",
    "Melody Time",
    "Wall-E",
    "Mulan",
    "Wreck it Ralph 2",
    "The Aristocats",
    "Fantasia",
    "Fantasia 2000",
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
    "Avengers: Endgame": "61f8UD0D6r47",
    # "Frozen": "...",  # add ID from disneyplus.com if you want Play
    # "Iron Man": "...",
}

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


def find_adb():
    """Return path to adb executable, or None if not found."""
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

@app.route('/')
def index():
    """Serves the movie poster grid"""
    return render_template('index.html', movies=LIBRARY)

@app.route('/play/<video_id>')
def play(video_id):
    """Deep links the video on Fire TV"""
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
    # Host='0.0.0.0' makes it accessible to other devices on your network
    app.run(host='0.0.0.0', port=5000)