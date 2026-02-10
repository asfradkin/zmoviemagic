# Zach's Movie Magic

A simple web app that shows a Netflix-style grid of movies and can launch them on Fire TV via Disney+ deep links (ADB).  This was designed for my son Zach, who cannot use a standard remote control.  This allows him to control the movies he wants to watch on the TV by touching pictures of them on his iPad or any other device with a web browser.  I run this locally on an old laptop running Ubuntu.  The Fire TV stick is the player and it is a simple and adaptable framework.  I also use TMDB to get the movie posters dynamically from the free API and service they provide.

My only mission is to make it easy for Zach and other kids like him to control a part of their lives.  Please use this code, modify it as you please and share.  Per the license, this is not designed to make a profit or be sold - this is meant to help families and children - not make money.  If your intent is to make money, please go do that on your own.  Thank you for your understanding and respecting my wishes of helping people over profit.  

## Setup

1. **Python 3** with Flask and ppadb: `pip install -r requirements.txt`
2. **ADB** (Android Platform Tools) installed and on your PATH
3. **Environment variables** – copy `.env.example` to `.env` and set:
   - `TMDB_API_KEY` – get a free key at [themoviedb.org](https://www.themoviedb.org/settings/api)
   - `FIRE_TV_IP` – your Fire TV’s IP address
   ```bash
   cp .env.example .env
   # Edit .env and add your values (do not commit .env)
   ```
4. In `app.py` you can still adjust `MOVIE_NAMES`, `DISNEY_IDS`, and `POSTER_OVERRIDES`

**Optional .env:** `FLASK_SECRET_KEY` (for production), `FLASK_DEBUG=1` (dev only), `PLAY_COOLDOWN_SECONDS` (default 2, min seconds between Play requests).

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

# 5. Create .env from the example and add your TMDB key and Fire TV IP
cp .env.example .env
# Edit .env (nano .env) and set TMDB_API_KEY and FIRE_TV_IP

# 6. Run the app
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

### Deploy pipeline (GitHub → server on push)

A GitHub Actions workflow (`.github/workflows/deploy.yml`) deploys to your Ubuntu server on every push to `main`: it SSHs in, updates the repo, and restarts the service.

**One-time setup on the Ubuntu server**

1. Clone the repo (if not already) and set up the app (venv, systemd) as above.
2. Allow your deploy user to restart the service without a password:

   ```bash
   sudo visudo
   # Add a line (replace USER with the user that will SSH from GitHub):
   # USER ALL=(ALL) NOPASSWD: /bin/systemctl restart zmoviemagic
   ```

3. Ensure the server can be reached by GitHub’s runners: either your server has a public IP and you open the SSH port (e.g. 22), or you use a self-hosted runner on the same network.

**One-time setup in GitHub**

1. In the repo: **Settings → Secrets and variables → Actions**.
2. Add these repository secrets:

   | Secret           | Description |
   |------------------|-------------|
   | `SERVER_HOST`    | Ubuntu server hostname or IP (e.g. `myserver.example.com` or `123.45.67.89`) |
   | `SERVER_USER`    | SSH username on the server (e.g. `afradkin`) |
   | `SSH_PRIVATE_KEY`| Full contents of the private key that can SSH as that user (paste the entire key including `-----BEGIN ... KEY-----` and `-----END ... KEY-----`) |
   | `REPO_PATH`      | Full path to the repo on the server (e.g. `/home/afradkin/zmoviemagic`) |
   | `SERVER_PORT`    | Optional. SSH port if not 22 (e.g. `22`). If you don’t add it and use port 22, you can omit this. |

3. On the server, the repo’s `origin` should be the GitHub URL (HTTPS or SSH). If you use SSH, the server’s SSH key must have access to the repo (e.g. add the server’s public key as a deploy key in GitHub).

**What runs on push**

- On every push to `main`, the workflow runs: SSH → `cd REPO_PATH` → `git fetch origin main` → `git reset --hard origin/main` → `sudo systemctl restart zmoviemagic`.
- You can also run the workflow manually: **Actions** tab → **Deploy to server** → **Run workflow**.

## Fire TV

- Enable **Developer options** and **ADB debugging** (over network) on the Fire TV
- Connect from PC: `adb connect YOUR_FIRE_TV_IP:5555`
- Accept the “Allow USB debugging?” prompt on the TV when you first connect. **Check "Always allow from this computer"** to avoid repeated prompts.
- If you don't see the prompt, try running `adb kill-server` and `adb connect YOUR_FIRE_TV_IP:5555` again.

## Run

```bash
python app.py
```

Open http://localhost:5000 (or your machine’s IP). Click a movie to send it to the Fire TV.


## Adding Movies & Custom Posters

The application loads movies from `movies.json`. It automatically fetches posters from TMDB if the `poster` field is empty.

To add a movie with a custom poster (or one not in TMDB):
1.  Open `movies.json`.
2.  Add a new entry with the `title`, `id` (Disney+ content ID), and `poster`.
3.  For `poster`, you can use any valid image URL.
    -   **Remote URL:** `"poster": "https://example.com/poster.jpg"`
    -   **Local File:**
        1.  Create a folder named `static` in the project root.
        2.  Place your image there (e.g., `my_poster.jpg`).
        3.  Use the path: `"poster": "/static/my_poster.jpg"`
4.  Restart the application (`sudo systemctl restart zmoviemagic` or restart the python script) to load the changes.

## Troubleshooting

### "device unauthorized" Error
If you see an error like `ERROR: 'FAIL' 00a7device unauthorized`:
1.  Look at your Fire TV screen.
2.  You should see a prompt "Allow USB debugging?".
3.  Select **Always allow from this computer** and click **Allow**.
4.  If the prompt doesn't appear, run `adb kill-server` on your server/PC and try to connect again.

### "adb server not found" (Linux)
If `adb` cannot be found even though it is installed:
1.  Ensure you have installed `android-tools-adb` (`apt install android-tools-adb`).
2.  The application tries to find `adb` in common locations (`/usr/bin/adb`, etc.).
3.  If running as a systemd service, ensure the `PATH` variable in `zmoviemagic.service` includes `/usr/bin`:
    ```ini
    Environment="PATH=/path/to/venv/bin:/usr/bin:/bin"
    ```

### Playback Latency
The application uses persistent ADB connections and batched shell commands to minimize delay. If playback feels slow:
-   Ensure your server and Fire TV are on the same Wi-Fi/network (5GHz recommended).
-   The first launch after server restart might take slightly longer to establish the initial connection.
