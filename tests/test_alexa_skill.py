import copy
import json
import time
from threading import Event

import pytest

from alexa.skill import handle_request
from services.movie_service import MovieService
from services.playback_service import PlaybackService
from services.rate_limit_service import RateLimitService
from tests.test_dispatcher import terminal
from tools.export_alexa_model import build_model


@pytest.fixture
def movie_skill(tmp_path):
    titles = [("Luca", "luca"), ("Frozen", "frozen"), ("Tangled", "tangled"),
              ("Elemental", "elemental"), ("Robin Hood", "robin-hood"), ("Frozen II", "frozen-2")]
    rows = [{"title": title, "key": key, "id": "private-" + key,
             "aliases": ["ice movie"] if key in {"frozen", "frozen-2"} else [],
             "poster": "/static/poster-fallback.svg"} for title, key in titles]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    movies = MovieService(str(path))
    movies.load()
    class FireTV:
        def __init__(self):
            self.calls = []
        def launch_movie_bounded(self, provider_id, budget_seconds):
            self.calls.append(provider_id)
            return {"connection": "connected"}
        def launch_movie(self, provider_id):
            self.calls.append(provider_id)
            return {}
    firetv = FireTV()
    playback = PlaybackService(firetv, 0, movies)
    limiter = RateLimitService()
    yield movies, playback, limiter, firetv.calls
    playback.shutdown()


def event(title="Luca", name="PlayMovieIntent", attributes=None, request_id="voice-1", choice="1"):
    return {"request": {"type": "IntentRequest", "requestId": request_id,
                        "intent": {"name": name, "slots": {"MovieTitle": {"value": title},
                                                             "Choice": {"value": choice}}}},
            "session": {"attributes": attributes or {}}}


def say(fixture, message):
    movies, playback, limiter, _ = fixture
    return handle_request(message, movies, playback, "alexa-test", limiter)


@pytest.mark.parametrize("title,key", [("Luca", "luca"), ("Frozen", "frozen"), ("Tangled", "tangled"),
                                        ("Elemental", "elemental"), ("Robin Hood", "robin-hood")])
def test_five_titles_launch_by_backend_key(movie_skill, title, key):
    response = say(movie_skill, event(title))
    job = movie_skill[1].status(principal="alexa-test")["request"]
    terminal(movie_skill[1], job["request_id"], "alexa-test")
    assert movie_skill[3] == ["private-" + key]
    assert response["response"]["outputSpeech"] == {"type": "PlainText", "text": f"I sent a request for {title} to Fire TV."}
    assert "Playing" not in json.dumps(response)
    assert "private-" not in json.dumps(response)


def test_ambiguity_requires_number_and_rechecks_catalog(movie_skill):
    first = say(movie_skill, event("ice movie"))
    assert first["response"]["shouldEndSession"] is False
    assert movie_skill[3] == []
    keys = first["sessionAttributes"]["choices"]
    selected = say(movie_skill, event(name="ChooseMovieIntent", attributes=first["sessionAttributes"], choice="2"))
    job = movie_skill[1].status(principal="alexa-test")["request"]
    terminal(movie_skill[1], job["request_id"], "alexa-test")
    assert movie_skill[3] == ["private-" + keys[1]]
    assert selected["response"]["shouldEndSession"]


@pytest.mark.parametrize("attributes,choice", [({}, "1"), ({"choices": ["frozen", "frozen-2"], "issued_at": 0}, "1"),
    ({"choices": ["../shell", "frozen"], "issued_at": time.time()}, "1"),
    ({"choices": ["frozen", "frozen-2"], "issued_at": time.time()}, "99")])
def test_bad_or_expired_choices_never_launch(movie_skill, attributes, choice):
    say(movie_skill, event(name="ChooseMovieIntent", attributes=attributes, choice=choice))
    assert movie_skill[3] == []
    assert movie_skill[1].status(principal="alexa-test")["request"] is None


def test_removed_choice_never_launches(movie_skill):
    first = say(movie_skill, event("ice movie"))
    key = first["sessionAttributes"]["choices"][0]
    movie_skill[0]._movies = [m for m in movie_skill[0]._movies if m["key"] != key]
    movie_skill[0]._validate()
    response = say(movie_skill, event(name="ChooseMovieIntent", attributes=first["sessionAttributes"]))
    assert "no longer" in response["response"]["outputSpeech"]["text"]
    assert movie_skill[3] == []


def test_repeated_event_never_repeats_launch(movie_skill):
    first = say(movie_skill, event())
    job = movie_skill[1].status(principal="alexa-test")["request"]
    terminal(movie_skill[1], job["request_id"], "alexa-test")
    assert say(movie_skill, event()) == first
    assert movie_skill[3] == ["private-luca"]
    assert len(movie_skill[2]._buckets[("command", "alexa-test")][0]) == 1


@pytest.mark.parametrize("name", ["AMAZON.CancelIntent", "AMAZON.StopIntent", "AMAZON.HelpIntent", "AMAZON.FallbackIntent"])
def test_non_play_intents_cause_no_commands(movie_skill, name):
    say(movie_skill, event(name=name))
    assert movie_skill[1].status(principal="alexa-test")["request"] is None
    assert movie_skill[3] == []


def test_unknown_reprompts_once_and_open_does_not_launch(movie_skill):
    first = say(movie_skill, event("not a catalog title"))
    assert not first["response"]["shouldEndSession"]
    second = say(movie_skill, event("not a catalog title", attributes=first["sessionAttributes"]))
    assert second["response"]["shouldEndSession"]
    opened = event()
    opened["request"]["type"] = "LaunchRequest"
    assert not say(movie_skill, opened)["response"]["shouldEndSession"]
    opened["request"]["type"] = "SessionEndedRequest"
    assert say(movie_skill, opened)["response"] == {}
    assert movie_skill[3] == []


def test_more_than_three_does_not_offer_arbitrary_subset(movie_skill):
    for movie in movie_skill[0]._movies:
        movie["aliases"] = ["movie"]
    movie_skill[0]._validate()
    response = say(movie_skill, event("movie"))
    assert "more specific" in response["response"]["outputSpeech"]["text"]
    assert "choices" not in response["sessionAttributes"]
    assert movie_skill[3] == []


def test_failure_after_admission_is_never_retried(movie_skill, monkeypatch):
    original = movie_skill[1].submit_play
    attempts = []
    def lost_response(*args, **kwargs):
        attempts.append(1)
        original(*args, **kwargs)
        raise TimeoutError("TEST_DIAGNOSTIC_DO_NOT_SPEAK")
    monkeypatch.setattr(movie_skill[1], "submit_play", lost_response)
    response = say(movie_skill, event())
    assert "may have reached" in response["response"]["outputSpeech"]["text"]
    assert "TEST_DIAGNOSTIC" not in json.dumps(response)
    assert attempts == [1]


def test_alexa_and_legacy_share_reservation(movie_skill, monkeypatch):
    entered, release = Event(), Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {"connection": "connected"}
    monkeypatch.setattr(movie_skill[1].firetv_service, "launch_movie_bounded", slow)
    try:
        say(movie_skill, event())
        assert entered.wait(1)
        from services.playback_service import CooldownError
        with pytest.raises(CooldownError):
            movie_skill[1].play("other-id")
        response = say(movie_skill, event("Frozen", request_id="voice-2"))
        assert "busy" in response["response"]["outputSpeech"]["text"]
        assert movie_skill[3] == []
    finally:
        release.set()


def test_model_has_public_keys_and_aliases_only(movie_skill):
    before = copy.deepcopy(movie_skill[0]._movies)
    model = build_model(movie_skill[0].public_catalog())
    assert model == build_model(movie_skill[0].public_catalog())
    encoded = json.dumps(model)
    assert "private-" not in encoded and "poster" not in encoded
    assert "ice movie" in encoded
    assert movie_skill[0]._movies == before
    assert model["interactionModel"]["languageModel"]["invocationName"] == "movie magic"
