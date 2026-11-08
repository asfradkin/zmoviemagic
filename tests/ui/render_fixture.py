"""Render the real Jinja template with synthetic data, without importing the app."""
from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

root = Path(__file__).resolve().parents[2]
environment = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
environment.globals["url_for"] = lambda endpoint, filename, **kw: "/static/" + filename + "?v=" + kw.get("v", "5")
movies = [
    {"key": "luca", "title": "Luca", "poster": "/static/poster-fallback.svg", "available": True},
    {"key": "moana", "title": "Moana", "poster": "https://posters.invalid/missing.jpg", "available": True},
    {"key": "long-title", "title": "A very long movie title that must wrap without hiding any words", "poster": "/static/poster-fallback.svg", "available": True},
    {"key": "unavailable", "title": "Unavailable movie", "poster": "/static/poster-fallback.svg", "available": False},
    {"key": "escaped", "title": '<img src=x onerror="alert(1)"> & friends', "poster": "/static/poster-fallback.svg", "available": True},
]
sys.stdout.buffer.write(environment.get_template("index.html").render(movies=movies, tablet_api_enabled=True, csrf_token="synthetic-csrf-token").encode("utf-8"))
