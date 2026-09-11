import os
import re
import shutil
import subprocess
from functools import lru_cache
from threading import Lock

from ppadb.client import Client as AdbClient


class FireTVService:
    """Own the persistent ADB client, device, and Disney+ launch behavior."""

    VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(self, host, port=5555, disney_package="com.disney.disneyplus"):
        self.host = host
        self.port = port
        self.disney_package = disney_package
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
                check=False,
            )
            self._adb_client = AdbClient(host="127.0.0.1", port=5037)
            return self._adb_client
        except Exception as exc:
            print(f"Error initializing ADB client: {exc}")
            return None

    def get_device(self, force_reconnect=False):
        with self._lock:
            if self._device and not force_reconnect:
                return self._device, None

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
                print(f"ADB Connection Error: {exc}")
                return None, str(exc)

    def launch_movie(self, video_id):
        if not video_id or not self.VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValueError("Invalid video ID")

        device, error = self.get_device()
        if not device:
            raise RuntimeError(error or "Could not connect to Fire TV")

        print(f"Launching ID: {video_id}")
        url = f"https://www.disneyplus.com/play/{video_id}?startTime=0"
        command = (
            "input keyevent 224 && input keyevent 3 && "
            "am start -a android.intent.action.VIEW "
            f'-d "{url}" {self.disney_package}'
        )

        try:
            device.shell(command)
            return {"retried": False}
        except RuntimeError as exc:
            print(f"Command failed, retrying connection: {exc}")
            device, reconnect_error = self.get_device(force_reconnect=True)
            if device:
                try:
                    device.shell(command)
                    return {"retried": True}
                except Exception as retry_exc:
                    raise RuntimeError(str(retry_exc)) from retry_exc

            message = str(exc)
            if "unauthorized" in message.lower():
                raise PermissionError(
                    "Fire TV has not authorized this computer for ADB. "
                    "On your Fire TV screen, look for an 'Allow USB debugging?' "
                    "(or similar) prompt and select Allow. If you don't see it, "
                    "run 'adb kill-server' in a terminal, then try again."
                ) from exc
            raise RuntimeError(reconnect_error or message) from exc
