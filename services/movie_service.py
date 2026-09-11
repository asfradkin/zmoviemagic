import json
import os
import urllib.parse
import urllib.request


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

    def load(self):
        if not os.path.exists(self.movies_file):
            self._movies = []
            self._loaded = True
            return self._movies

        try:
            with open(self.movies_file, "r", encoding="utf-8") as movie_file:
                movies = json.load(movie_file)
            if not isinstance(movies, list):
                raise ValueError("Movie catalog must contain a JSON array.")
            self._movies = movies
        except Exception as exc:
            print(f"Error loading {self.movies_file}: {exc}")
            self._movies = []

        self._loaded = True
        return self._movies

    def save(self):
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
            print(f"TMDB fetch failed for '{title}': {exc}")
            return None

    def all(self):
        if not self._loaded:
            self.load()
        return list(self._movies)

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
