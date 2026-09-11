import re
import time
from threading import Lock


class CooldownError(RuntimeError):
    """Raised when playback is requested before the cooldown expires."""


class PlaybackService:
    """Serialize playback requests and own the process-local cooldown state."""

    VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(self, firetv_service, cooldown_seconds=2):
        self.firetv_service = firetv_service
        self.cooldown_seconds = float(cooldown_seconds)
        self._last_play_time = 0.0
        self._lock = Lock()

    def play(self, video_id):
        if not video_id or not self.VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValueError("Invalid video ID")

        with self._lock:
            now = time.monotonic()
            if (
                self.cooldown_seconds > 0
                and now - self._last_play_time < self.cooldown_seconds
            ):
                raise CooldownError(
                    f"Please wait {self.cooldown_seconds:g} seconds between plays."
                )

            # Failed ADB attempts also consume the cooldown, matching the old route.
            self._last_play_time = now
            result = self.firetv_service.launch_movie(video_id)

        message = f"Playing video {video_id}"
        if result.get("retried"):
            message += " (retried)"
        return {"status": "success", "message": message}
