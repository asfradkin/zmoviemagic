import json
import copy
import hashlib
import logging
import os
import re
import unicodedata
import urllib.parse
import urllib.request


logger = logging.getLogger(__name__)
KEY_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]+", re.ASCII)
FALLBACK_POSTER = "/static/poster-fallback.svg"


def valid_key(value):
    return isinstance(value, str) and len(value) <= 80 and bool(KEY_PATTERN.fullmatch(value))


def valid_id(value):
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value))


def normalize_name(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def safe_poster(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return FALLBACK_POSTER
    try:
        url = urllib.parse.urlsplit(value)
        if url.scheme == "https" and url.hostname and not url.username and not url.password:
            return value
        if (not url.scheme and not url.netloc and value.startswith("/static/")
                and "\\" not in value and ".." not in urllib.parse.unquote(url.path)):
            return value
    except ValueError:
        pass
    return FALLBACK_POSTER


class MovieService:
    """Load and query the existing title/id/poster movie catalog."""

    def __init__(
        self,
        movies_file,
        tmdb_api_key="",
        tmdb_image_base="https://image.tmdb.org/t/p/w500",
        tmdb_search_url="https://api.themoviedb.org/3/search/movie",
    ):
        self.movies_file = movies_file
        self.tmdb_api_key = tmdb_api_key
        self.tmdb_image_base = tmdb_image_base
        self.tmdb_search_url = tmdb_search_url
        self._movies = []
        self._loaded = False
        self.validation_errors = ["catalog_not_loaded"]
        self.ambiguous_names = {}
        self._keys = {}
        self._names = {}

    @property
    def catalog_available(self):
        return self._loaded and not self.validation_errors

    def _validate(self):
        errors, keys, names = [], {}, {}
        for index, movie in enumerate(self._movies):
            key = movie.get("key")
            aliases = movie.get("aliases", [])
            if not valid_key(key):
                errors.append(f"row_{index + 1}:invalid_key")
                continue
            if key in keys:
                errors.append(f"row_{index + 1}:duplicate_key")
            if not isinstance(movie.get("title"), str) or not movie["title"].strip():
                errors.append(f"row_{index + 1}:invalid_title")
                continue
            if (not isinstance(aliases, list) or len(aliases) > 20
                    or any(not isinstance(a, str) or not a.strip() or len(a) > 100 for a in aliases)):
                errors.append(f"row_{index + 1}:invalid_aliases")
                continue
            keys[key] = movie
            for name in [movie["title"], *aliases]:
                normalized = normalize_name(name)
                if normalized:
                    names.setdefault(normalized, set()).add(key)
        self.validation_errors = errors
        self._keys, self._names = keys, names
        self.ambiguous_names = {name: sorted(matches) for name, matches in names.items() if len(matches) > 1}
        if self.ambiguous_names:
            logger.warning("Catalog has %d ambiguous normalized names", len(self.ambiguous_names))

    def get_by_key(self, key):
        if not self.catalog_available:
            raise ValueError("catalog_unavailable")
        return copy.deepcopy(self._keys.get(key))

    def resolve(self, name):
        if not self.catalog_available:
            raise ValueError("catalog_unavailable")
        candidates = sorted(self._names.get(normalize_name(name), set()))
        return {"state": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "unknown",
                "candidates": candidates}

    def public_catalog(self):
        if not self.catalog_available:
            raise ValueError("catalog_unavailable")
        movies = [{"key": m["key"], "title": m["title"], "poster": safe_poster(m.get("poster")),
                   "aliases": list(m.get("aliases", [])), "available": valid_id(m.get("id"))}
                  for m in self._movies]
        canonical = json.dumps(movies, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return {"schema_version": 2, "catalog_revision": "sha256:" + hashlib.sha256(canonical).hexdigest(),
                "movies": movies}

    def load(self):
        if not os.path.exists(self.movies_file):
            self._movies = []
            self._loaded = True
            self.validation_errors = ["catalog_missing"]
            return self._movies

        try:
            with open(self.movies_file, "r", encoding="utf-8") as movie_file:
                movies = json.load(movie_file)
            if not isinstance(movies, list):
                raise ValueError("Movie catalog must contain a JSON array.")
            if any(not isinstance(movie, dict) for movie in movies):
                raise ValueError("Movie catalog rows must be objects.")
            self._movies = movies
            self._validate()
        except Exception as exc:
            logger.warning("Catalog load failed (%s)", type(exc).__name__)
            self._movies = []
            self.validation_errors = ["catalog_invalid"]
            self._keys, self._names = {}, {}

        self._loaded = True
        return self._movies

    def save(self):
        if self.validation_errors in (["catalog_invalid"], ["catalog_missing"]):
            raise ValueError("Cannot save an unreadable catalog")
        try:
            with open(self.movies_file, "w", encoding="utf-8") as movie_file:
                json.dump(self._movies, movie_file, indent=2)
        except Exception as exc:
            print(f"Error saving {self.movies_file}: {exc}")

    def refresh_missing_posters(self):
        """Fetch and cache missing posters, preserving startup behavior."""
        if not self._loaded:
            self.load()

        updated = False
        for movie in self._movies:
            title = movie.get("title")
            if movie.get("poster"):
                continue

            print(f"Fetching poster for: {title}")
            poster = self.fetch_poster_for_title(title)
            if poster:
                movie["poster"] = poster
                updated = True
            else:
                movie["poster"] = ""

        if updated:
            print("Updating movies.json with new posters...")
            self.save()

    def fetch_poster_for_title(self, title):
        try:
            query = urllib.parse.urlencode(
                {"api_key": self.tmdb_api_key, "query": title}
            )
            request = urllib.request.Request(
                f"{self.tmdb_search_url}?{query}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())

            results = data.get("results") or []
            if not results or not results[0].get("poster_path"):
                return None
            return self.tmdb_image_base + results[0]["poster_path"]
        except Exception as exc:
            logger.warning("Poster fetch failed (%s)", type(exc).__name__)
            return None

    def all(self):
        if not self._loaded:
            self.load()
        return copy.deepcopy(self._movies)

    def get_by_id(self, disney_id):
        return next(
            (movie for movie in self.all() if movie.get("id") == disney_id),
            None,
        )

    def library(self):
        return [
            {
                "title": movie.get("title"),
                "id": movie.get("id", ""),
                "poster": movie.get("poster", ""),
            }
            for movie in self.all()
        ]
