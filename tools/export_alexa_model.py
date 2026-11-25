"""Export public movie names for Alexa; never change the catalog or contact TMDB."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.movie_service import MovieService


def build_model(catalog):
    values = []
    for movie in catalog["movies"]:
        if movie["available"]:
            name = {"value": movie["title"]}
            if movie["aliases"]:
                name["synonyms"] = movie["aliases"]
            values.append({"id": movie["key"], "name": name})
    return {"interactionModel": {"languageModel": {
        "invocationName": "movie magic",
        "intents": [
            {"name": "PlayMovieIntent", "slots": [{"name": "MovieTitle", "type": "MOVIE_TITLE"}],
             "samples": ["play {MovieTitle}", "watch {MovieTitle}", "put on {MovieTitle}"]},
            {"name": "ChooseMovieIntent", "slots": [{"name": "Choice", "type": "AMAZON.NUMBER"}],
             "samples": ["number {Choice}", "option {Choice}", "{Choice}"]},
            *({"name": name, "samples": []} for name in ["AMAZON.HelpIntent", "AMAZON.CancelIntent",
                                                        "AMAZON.StopIntent", "AMAZON.FallbackIntent"]),
        ],
        "types": [{"name": "MOVIE_TITLE", "values": values}],
    }}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.catalog.resolve() == args.output.resolve():
        parser.error("Output must not replace the catalog")
    movies = MovieService(str(args.catalog))
    movies.load()
    if not movies.catalog_available:
        parser.error("The catalog is unavailable or invalid")
    model = build_model(movies.public_catalog())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Exported movie names and aliases. The catalog was not changed.")


if __name__ == "__main__":
    main()
