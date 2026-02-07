# zmoviemagic

A simple web app that shows a Netflix-style grid of movies and can launch them on Fire TV via Disney+ deep links (ADB).

## Setup

1. **Python 3** with Flask and ppadb: `pip install flask pure-python-adb`
2. **ADB** (Android Platform Tools) installed and on your PATH
3. **TMDB API key** – get a free key at [themoviedb.org](https://www.themoviedb.org/settings/api)
4. Edit `app.py`:
   - Set `FIRE_TV_IP` to your Fire TV’s IP
   - Set `TMDB_API_KEY` to your key
   - Adjust `MOVIE_NAMES` and optionally `DISNEY_IDS` and `POSTER_OVERRIDES`

## Fire TV

- Enable **Developer options** and **ADB debugging** (over network) on the Fire TV
- Connect from PC: `adb connect YOUR_FIRE_TV_IP:5555`
- Accept the “Allow USB debugging?” prompt on the TV when you first connect

## Run

```bash
python app.py
```

Open http://localhost:5000 (or your machine’s IP). Click a movie to send it to the Fire TV.
