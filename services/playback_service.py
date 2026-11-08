import atexit
import copy
from datetime import datetime, timezone
import logging
import math
from queue import Queue, Empty
from threading import Lock, Thread
import re
import time
from uuid import uuid4

from services.firetv_service import DeliveryError
from services.movie_service import valid_id, valid_key

logger = logging.getLogger(__name__)


class CooldownError(RuntimeError):
    """Legacy busy/cooldown response."""


class APIError(RuntimeError):
    def __init__(self, code, status, message, retry_after=0):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message
        self.retry_after = retry_after

    def body(self):
        error = {"code": self.code, "message": self.message,
                 "retryable": self.status in (429, 503)}
        if self.retry_after:
            error["retry_after_seconds"] = self.retry_after
        return {"error": error}


class PlaybackService:
    """One reservation shared by synchronous legacy and asynchronous API calls."""

    IDEMPOTENCY_PATTERN = re.compile(r"[\x20-\x7e]{8,128}", re.ASCII)

    def __init__(self, firetv_service, cooldown_seconds=2, movie_service=None,
                 max_records=256, retention_seconds=900, shutdown_grace=5, clock=time.monotonic):
        self.firetv_service = firetv_service
        self.movie_service = movie_service
        self.cooldown_seconds = float(cooldown_seconds)
        if not math.isfinite(self.cooldown_seconds) or self.cooldown_seconds < 0:
            raise ValueError("Cooldown must be finite and nonnegative")
        if not isinstance(max_records, int) or not 1 <= max_records <= 256:
            raise ValueError("Record limit must be between 1 and 256")
        if not math.isfinite(retention_seconds) or not 0 < retention_seconds <= 900:
            raise ValueError("Retention must be positive and at most 900 seconds")
        if not math.isfinite(shutdown_grace) or not 0 <= shutdown_grace <= 15:
            raise ValueError("Shutdown grace must be between 0 and 15 seconds")
        self.max_records, self.retention_seconds = max_records, retention_seconds
        self.shutdown_grace = shutdown_grace
        self._clock = clock
        self._last_play_time = None
        self._lock = Lock()
        self._active = None
        self._jobs, self._idempotency = {}, {}
        self._handoff = Queue(maxsize=1)
        self._worker = None
        self._closed = False
        self.boot_id = str(uuid4())
        self._device = {"connection": "unknown", "last_checked_at": None}
        self._legacy_counts = {"accepted": 0, "rejected": 0}

    @staticmethod
    def _utc():
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _retry_after(self):
        if self._last_play_time is None:
            return 0
        return max(0, math.ceil(self.cooldown_seconds - (self._clock() - self._last_play_time)))

    def _check_admission(self):
        if self._closed:
            raise APIError("dispatcher_unavailable", 503, "Command dispatcher is unavailable.")
        if self._active is not None:
            raise APIError("busy", 429, "The TV is handling another request.", max(1, self._retry_after()))
        if self._retry_after():
            raise APIError("cooldown", 429, "Please wait before another movie request.", self._retry_after())

    def _expire(self):
        expired = {rid for rid, entry in self._jobs.items()
                   if entry["terminal_at"] is not None
                   and self._clock() - entry["terminal_at"] >= self.retention_seconds}
        for rid in expired:
            del self._jobs[rid]
        self._idempotency = {key: value for key, value in self._idempotency.items() if value["request_id"] not in expired}

    def _ensure_worker(self):
        if self._worker is not None and self._worker.is_alive():
            return
        try:
            worker = Thread(target=self._run, name="playback-dispatcher", daemon=True)
            worker.start()
            self._worker = worker
            atexit.register(self.shutdown)
        except Exception:
            raise APIError("dispatcher_unavailable", 503, "Command dispatcher is unavailable.") from None

    def submit_play(self, movie_key, principal, idempotency_key, admit=None):
        if not valid_key(movie_key):
            raise APIError("invalid_movie_key", 400, "A valid movie key is required.")
        if not isinstance(idempotency_key, str) or not self.IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise APIError("invalid_idempotency_key", 400, "Idempotency-Key must contain 8–128 printable ASCII characters.")
        with self._lock:
            self._expire()
            scope = (principal, idempotency_key)
            previous = self._idempotency.get(scope)
            if previous:
                if previous["movie_key"] != movie_key:
                    raise APIError("idempotency_conflict", 409, "This idempotency key belongs to another request.")
                return copy.deepcopy(previous["response"])
            if self.movie_service is None or not self.movie_service.catalog_available:
                raise APIError("catalog_unavailable", 503, "The movie catalog is unavailable.")
            movie = self.movie_service.get_by_key(movie_key)
            if movie is None:
                raise APIError("movie_not_found", 404, "Movie not found.")
            if not valid_id(movie.get("id")):
                raise APIError("movie_unavailable", 409, "This movie is unavailable.")
            self._check_admission()
            if len(self._jobs) >= self.max_records or len(self._idempotency) >= self.max_records:
                raise APIError("dispatcher_unavailable", 503, "Request history is full; try again after records expire.")
            if admit is not None:
                admit()
            self._ensure_worker()
            request_id = str(uuid4())
            response = {"request_id": request_id, "movie_key": movie_key, "command_state": "queued",
                        "playback": {"state": "unknown", "evidence": "none"},
                        "status_url": "/api/status?request_id=" + request_id}
            public = {"request_id": request_id, "action": "play", "movie_key": movie_key,
                      "command_state": "queued", "accepted_at": self._utc(), "completed_at": None, "error": None}
            self._jobs[request_id] = {"public": public, "principal": principal, "terminal_at": None}
            self._idempotency[scope] = {"movie_key": movie_key, "request_id": request_id, "response": response}
            self._active = request_id
            self._handoff.put_nowait((request_id, movie["id"]))
            logger.info("Command accepted request_id=%s movie_key=%s action=play", request_id, movie_key)
            return copy.deepcopy(response)

    def _run(self):
        while True:
            try:
                request_id, provider_id = self._handoff.get(timeout=0.1)
            except Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            started = self._clock()
            state, error, connection = "failed", None, "unknown"
            try:
                with self._lock:
                    self._last_play_time = self._clock()
                    self._jobs[request_id]["public"]["command_state"] = "dispatching"
                result = self.firetv_service.launch_movie_bounded(provider_id, budget_seconds=15)
                state, connection = "command_sent", result.get("connection", "unknown")
            except DeliveryError as exc:
                state, connection = exc.state, exc.connection
                error = {"code": exc.code, "message": self._error_message(exc.code)}
            except Exception:
                state = "unknown"
                error = {"code": "internal_error", "message": "Delivery could not be established. Check the TV."}
            finally:
                with self._lock:
                    entry = self._jobs[request_id]
                    entry["public"].update(command_state=state, completed_at=self._utc(), error=error)
                    entry["terminal_at"] = self._clock()
                    if connection != "unknown":
                        self._device = {"connection": connection, "last_checked_at": self._utc()}
                    self._active = None
                self._handoff.task_done()
                logger.info("Command completed request_id=%s action=play state=%s code=%s elapsed=%.3fs",
                            request_id, state, error["code"] if error else "none", self._clock() - started)

    @staticmethod
    def _error_message(code):
        return {"device_unauthorized": "The Fire TV needs caregiver authorization.",
                "device_unavailable": "The Fire TV is unavailable.",
                "command_rejected": "The Fire TV rejected the launch command.",
                "delivery_unknown": "The request may have reached the TV. Check the screen before trying again."}.get(
                    code, "Delivery could not be established. Check the TV.")

    def status(self, request_id=None, principal="lan-household"):
        with self._lock:
            self._expire()
            if request_id is not None:
                entry = self._jobs.get(request_id)
                if entry is None or entry["principal"] != principal:
                    raise APIError("request_not_found", 404, "Request not found; delivery cannot be established.")
            else:
                entries = [entry for entry in self._jobs.values() if entry["principal"] == principal]
                entry = entries[-1] if entries else None
            return {"boot_id": self.boot_id, "request": copy.deepcopy(entry["public"]) if entry else None,
                    "device": dict(self._device), "playback": {"state": "unknown", "evidence": "none"},
                    "retry_after_seconds": self._retry_after()}

    def shutdown(self):
        with self._lock:
            self._closed = True
            worker = self._worker
        if worker is not None:
            worker.join(timeout=self.shutdown_grace)
        atexit.unregister(self.shutdown)

    def legacy_usage(self):
        with self._lock:
            return dict(self._legacy_counts)

    def play(self, video_id, admit=None):
        if not valid_id(video_id):
            raise ValueError("Invalid video ID")
        with self._lock:
            try:
                self._check_admission()
            except APIError as exc:
                self._legacy_counts["rejected"] += 1
                if exc.code == "cooldown":
                    raise CooldownError(f"Please wait {self.cooldown_seconds:g} seconds between plays.") from None
                raise CooldownError("Playback is busy. Please try again shortly.") from None
            if admit is not None:
                admit()
            self._active = "legacy"
            self._last_play_time = self._clock()
            self._legacy_counts["accepted"] += 1
        started = self._clock()
        try:
            result = self.firetv_service.launch_movie(video_id)
        finally:
            with self._lock:
                self._active = None
            logger.info("Legacy command attempt action=play elapsed=%.3fs", self._clock() - started)
        message = f"Playing video {video_id}"
        if result.get("retried"):
            message += " (retried)"
        return {"status": "success", "message": message}
