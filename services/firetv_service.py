import logging
import math
import os
import re
import shutil
import subprocess
from functools import lru_cache
from threading import Lock

from ppadb.client import Client as AdbClient


logger = logging.getLogger(__name__)


class TimeoutAdbClient(AdbClient):
    """Apply a finite socket timeout to host commands as well as shell calls."""

    def __init__(self, timeout_seconds):
        super().__init__(host="127.0.0.1", port=5037)
        self.timeout_seconds = timeout_seconds

    def create_connection(self, timeout=None):
        return super().create_connection(
            timeout=self.timeout_seconds if timeout is None else timeout
        )


class FireTVService:
    """Own the persistent ADB client, device, and Disney+ launch behavior."""

    VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(
        self, host, port=5555, disney_package="com.disney.disneyplus",
        timeout_seconds=5,
    ):
        self.host = host
        self.port = port
        self.disney_package = disney_package
        self.timeout_seconds = float(timeout_seconds)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("ADB_TIMEOUT_SECONDS must be a finite positive number")
        self._adb_client = None
        self._device = None
        self._lock = Lock()

    @staticmethod
    @lru_cache(maxsize=1)
    def find_adb():
        adb_path = shutil.which("adb")
        if adb_path:
            return adb_path

        if os.name == "nt":
            for base in [
                os.environ.get("LOCALAPPDATA", ""),
                os.environ.get("ANDROID_HOME", ""),
                os.environ.get("ANDROID_SDK_ROOT", ""),
            ]:
                if base:
                    candidate = os.path.join(
                        base, "Android", "Sdk", "platform-tools", "adb.exe"
                    )
                    if os.path.isfile(candidate):
                        return candidate
        else:
            for candidate in [
                "/usr/bin/adb",
                "/usr/local/bin/adb",
                "/opt/android-sdk/platform-tools/adb",
            ]:
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _get_adb_client(self):
        if self._adb_client:
            return self._adb_client

        adb_path = self.find_adb()
        if not adb_path:
            return None

        try:
            subprocess.run(
                [adb_path, "start-server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=self.timeout_seconds,
            )
            self._adb_client = TimeoutAdbClient(self.timeout_seconds)
            return self._adb_client
        except Exception as exc:
            raise RuntimeError(f"Could not start ADB server: {exc}") from exc

    def get_device(self, force_reconnect=False):
        with self._lock:
            if self._device and not force_reconnect:
                return self._device, None

            self._device = None

            client = self._get_adb_client()
            if not client:
                return None, "ADB not found or server failed to start."

            try:
                try:
                    client.remote_connect(self.host, self.port)
                except RuntimeError:
                    pass

                self._device = client.device(f"{self.host}:{self.port}")
                if not self._device:
                    return None, f"Could not connect to {self.host}:{self.port}"
                return self._device, None
            except Exception as exc:
                logger.warning("ADB connection failed: %s", exc)
                return None, str(exc)

    @staticmethod
    def _raise_failure(error):
        if "unauthorized" in str(error).lower():
            raise PermissionError(
                "Fire TV has not authorized this computer for ADB. "
                "On your Fire TV screen, look for an 'Allow USB debugging?' "
                "(or similar) prompt and select Allow. If you don't see it, "
                "run 'adb kill-server' in a terminal, then try again."
            )
        if isinstance(error, TimeoutError):
            raise RuntimeError("ADB operation timed out. Check the Fire TV connection.") from error
        raise RuntimeError(str(error))

    def _shell(self, device, command):
        # Own the connection so timeouts during transport/read also close the socket.
        with device.create_connection(
            set_transport=False, timeout=self.timeout_seconds
        ) as connection:
            device.transport(connection)
            connection.send(f"shell:{command}")
            return connection.read_all().decode("utf-8")

    def launch_movie(self, video_id):
        if not video_id or not self.VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValueError("Invalid video ID")

        device, error = self.get_device()
        if not device:
            self._raise_failure(error or "Could not connect to Fire TV")

        logger.info("Launching video_id=%s", video_id)
        url = f"https://www.disneyplus.com/play/{video_id}?startTime=0"
        command = (
            "input keyevent 224 && input keyevent 3 && "
            "am start -a android.intent.action.VIEW "
            f'-d "{url}" {self.disney_package}'
        )

        try:
            self._shell(device, command)
            return {"retried": False}
        except (RuntimeError, OSError) as exc:
            self._device = None
            if isinstance(exc, TimeoutError) or "unauthorized" in str(exc).lower():
                # A timed-out launch may already have run; do not launch it twice.
                self._raise_failure(exc)
            logger.warning("ADB command failed; reconnecting once: %s", exc)
            device, reconnect_error = self.get_device(force_reconnect=True)
            if device:
                try:
                    self._shell(device, command)
                    return {"retried": True}
                except Exception as retry_exc:
                    self._device = None
                    self._raise_failure(retry_exc)

            self._raise_failure(reconnect_error or exc)
