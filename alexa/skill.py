"""The conversation: find a movie, clarify if necessary, request a launch."""
from hashlib import sha256
import time

from services.movie_service import valid_key
from services.playback_service import APIError


HELP = 'Say, Alexa, ask Movie Magic to play Luca. I can start movies, but cannot pause or stop them.'


def reply(text, *, attributes=None, keep_open=False, reprompt="Please say the movie title, or cancel."):
    """Use plain speech, so movie names cannot introduce SSML markup."""
    response = {"outputSpeech": {"type": "PlainText", "text": text},
                "shouldEndSession": not keep_open}
    if keep_open:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText",
                                                "text": reprompt}}
    return {"version": "1.0", "sessionAttributes": attributes or {}, "response": response}


def ask_again(text, attributes):
    """Allow one extra attempt, then end instead of trapping someone in a loop."""
    attempts = attributes.get("attempts", 0)
    if type(attempts) is not int or not 0 <= attempts <= 1:
        attempts = 1
    return reply(text, attributes={"attempts": attempts + 1}, keep_open=attempts == 0)


def slot_value(intent, name):
    slots = intent.get("slots", {})
    if not isinstance(slots, dict):
        return None
    slot = slots.get(name, {})
    return slot.get("value") if isinstance(slot, dict) else None


def handle_request(event, movies, playback, principal, limiter, *, now=None):
    """Called only after web.py verifies the Amazon request and household identity."""
    now = time.time() if now is None else now
    request = event["request"]
    request_type = request["type"]
    attributes = event.get("session", {}).get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}

    if request_type == "SessionEndedRequest":
        return {"version": "1.0", "response": {}}
    if request_type == "LaunchRequest":
        return reply(HELP, keep_open=True)

    intent = request.get("intent", {})
    name = intent.get("name")
    if name in {"AMAZON.CancelIntent", "AMAZON.StopIntent"}:
        return reply("Okay.")
    if name == "AMAZON.HelpIntent":
        return reply(HELP, keep_open=True)

    try:
        if name == "PlayMovieIntent":
            title = slot_value(intent, "MovieTitle")
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
                return ask_again("Which movie? Please say its full title.", attributes)
            match = movies.resolve(title.strip())
            keys = match["candidates"]
            if not keys:
                return ask_again("I couldn't find that movie. Please say its full title.", attributes)
            if len(keys) > 3:
                return ask_again("Several movies have that name. Please say a more specific title.", attributes)
            if len(keys) > 1:
                titles = [movies.get_by_key(key)["title"] for key in keys]
                choices = ". ".join(f"Number {index}: {title}" for index, title in enumerate(titles, 1))
                return reply("Which movie? " + choices + ". Say the number, or cancel.",
                             attributes={"choices": keys, "issued_at": now}, keep_open=True,
                             reprompt="Please say one of the listed numbers, or cancel.")
            movie_key = keys[0]
        elif name == "ChooseMovieIntent":
            keys = attributes.get("choices")
            issued_at = attributes.get("issued_at")
            choice = slot_value(intent, "Choice")
            if (not isinstance(keys, list) or not 2 <= len(keys) <= 3
                    or any(not valid_key(key) for key in keys) or len(set(keys)) != len(keys)
                    or type(issued_at) not in (int, float) or not 0 <= now - issued_at <= 120):
                return reply("That choice has expired. Please ask Movie Magic to play the full title.")
            if not isinstance(choice, str) or choice not in {str(n) for n in range(1, len(keys) + 1)}:
                # Keep the choices for one correction, but never guess a number.
                if attributes.get("choice_retry") is True:
                    return reply("Please ask Movie Magic again with the full movie title.")
                return reply("Please say one of the listed numbers, or cancel.",
                             attributes={"choices": keys, "issued_at": issued_at, "choice_retry": True},
                             keep_open=True, reprompt="Please say one of the listed numbers, or cancel.")
            movie_key = keys[int(choice) - 1]
        else:
            return ask_again("I didn't understand. " + HELP, attributes)

        # Recheck the current catalog even when Alexa's saved choices are old.
        movie = movies.get_by_key(movie_key)
        if movie is None:
            return reply("That movie is no longer in Movie Magic.")
        request_key = "alexa-" + sha256(request["requestId"].encode("utf-8")).hexdigest()
        playback.submit_play(movie_key, principal, request_key,
                             admit=lambda: limiter.consume("command", principal))
        return reply(f"I sent a request for {movie['title']} to Fire TV.")
    except ValueError:
        return reply("The movie catalog is unavailable. Please ask a caregiver for help.")
    except APIError as error:
        if error.status == 429:
            return reply("Movie Magic is busy. Please wait a moment before asking again.")
        if error.code in {"movie_unavailable", "movie_not_found"}:
            return reply("That movie isn't available in Movie Magic.")
        return reply("Movie Magic couldn't accept that request. Please ask a caregiver for help.")
    except Exception:
        # A failed response never licenses another launch: admission may have happened.
        return reply("The request may have reached the TV. Please check the screen before asking again.")
