# zmoviemagic

A simple web app that shows a Netflix-style grid of movies and can launch them on Fire TV via Disney+ deep links (ADB).

## Setup

1. **Python 3** with Flask and ppadb: `pip install -r requirements.txt`
2. **ADB** (Android Platform Tools) installed and on your PATH
3. **TMDB API key** – get a free key at [themoviedb.org](https://www.themoviedb.org/settings/api)
4. Edit `app.py`:
   - Set `FIRE_TV_IP` to your Fire TV’s IP
   - Set `TMDB_API_KEY` to your key
   - Adjust `MOVIE_NAMES` and optionally `DISNEY_IDS` and `POSTER_OVERRIDES`

## Installing on Ubuntu Server

```bash
# 1. System packages (Python 3, venv, pip, ADB)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip android-tools-adb

# 2. Clone or copy the project, then in the project directory:
cd zmoviemagic

# 3. Create a virtual environment and install Python deps
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. If pip install fails on pure-python-adb, try without version pin:
#    pip install Flask pure-python-adb

# 5. Run the app
python app.py
```

**If ADB is not found** (e.g. older Ubuntu): install Android Platform Tools manually and add to PATH:

```bash
# Download and unzip from https://developer.android.com/studio/releases/platform-tools
# Then e.g.:
export PATH="$PATH:/path/to/platform-tools"
```

**Run on a specific host/port** (e.g. for remote access):

```bash
python app.py
# Listens on 0.0.0.0:5000 by default. Use a reverse proxy (nginx) or firewall as needed.
```

### Start on boot and restart on failure (systemd)

1. Edit `zmoviemagic.service` in the project: set `User`, `WorkingDirectory`, and `ExecStart` to your username and full path to the project (e.g. `/home/andre/zmoviemagic`). The `ExecStart` line must point to your venv’s Python: `.../zmoviemagic/venv/bin/python app.py`.

2. Install and enable the service:

```bash
sudo cp zmoviemagic.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zmoviemagic   # start on boot
sudo systemctl start zmoviemagic    # start now
sudo systemctl status zmoviemagic   # check it’s running
```

3. Useful commands:

```bash
sudo systemctl stop zmoviemagic     # stop
sudo systemctl restart zmoviemagic  # restart
journalctl -u zmoviemagic -f        # follow logs
```

The service is set to `Restart=always` with `RestartSec=5`, so it will come back up after a crash or reboot.

## Fire TV

- Enable **Developer options** and **ADB debugging** (over network) on the Fire TV
- Connect from PC: `adb connect YOUR_FIRE_TV_IP:5555`
- Accept the “Allow USB debugging?” prompt on the TV when you first connect

## Run

```bash
python app.py
```

Open http://localhost:5000 (or your machine’s IP). Click a movie to send it to the Fire TV.
