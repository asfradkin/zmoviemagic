import socket
import subprocess

import pytest

from services.firetv_service import FireTVService, TimeoutAdbClient


def test_firetv_preserves_disney_deep_link_command(monkeypatch):
    class FakeDevice:
        def __init__(self):
            self.commands = []

    device = FakeDevice()
    service = FireTVService(host="192.0.2.1")
    monkeypatch.setattr(service, "get_device", lambda force_reconnect=False: (device, None))
    monkeypatch.setattr(service, "_shell", lambda device, command: device.commands.append(command))

    assert service.launch_movie("luca-id") == {"retried": False}
    assert device.commands == [
        "input keyevent 224 && input keyevent 3 && "
        "am start -a android.intent.action.VIEW "
        '-d "https://www.disneyplus.com/play/luca-id?startTime=0" '
        "com.disney.disneyplus"
    ]


def test_timeout_does_not_repeat_a_possibly_delivered_launch(monkeypatch):
    service = FireTVService("192.0.2.1")
    device = object()
    calls = []
    monkeypatch.setattr(service, "get_device", lambda force_reconnect=False: (device, None))

    def shell(device, command):
        calls.append(command)
        raise TimeoutError("socket timed out")

    monkeypatch.setattr(service, "_shell", shell)
    with pytest.raises(RuntimeError, match="timed out"):
        service.launch_movie("luca-id")
    assert len(calls) == 1
    assert service._device is None


def test_broken_connection_retries_once(monkeypatch):
    service = FireTVService("192.0.2.1")
    reconnects = []
    commands = []

    def get_device(force_reconnect=False):
        reconnects.append(force_reconnect)
        return object(), None

    def shell(device, command):
        commands.append(command)
        if len(commands) == 1:
            raise RuntimeError("connection closed")

    monkeypatch.setattr(service, "get_device", get_device)
    monkeypatch.setattr(service, "_shell", shell)
    assert service.launch_movie("luca-id") == {"retried": True}
    assert reconnects == [False, True]
    assert commands[0] == commands[1]


def test_authorization_failure_on_retry_is_preserved(monkeypatch):
    service = FireTVService("192.0.2.1")
    attempts = []
    monkeypatch.setattr(service, "get_device", lambda force_reconnect=False: (object(), None))

    def shell(device, command):
        attempts.append(command)
        raise RuntimeError("connection closed" if len(attempts) == 1 else "device unauthorized")

    monkeypatch.setattr(service, "_shell", shell)
    with pytest.raises(PermissionError, match="has not authorized"):
        service.launch_movie("luca-id")
    assert len(attempts) == 2


def test_adb_startup_is_bounded_and_checks_exit_status(monkeypatch):
    service = FireTVService("192.0.2.1", timeout_seconds=3)
    monkeypatch.setattr(service, "find_adb", lambda: "adb")

    def run(args, **kwargs):
        assert args == ["adb", "start-server"]
        assert kwargs["timeout"] == 3
        assert kwargs["check"] is True
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Could not start ADB server"):
        service._get_adb_client()
    assert service._adb_client is None


def test_shell_closes_connection_after_read_timeout():
    class Connection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def send(self, command):
            assert command == "shell:test"

        def read_all(self):
            raise TimeoutError()

    connection = Connection()

    class Device:
        def create_connection(self, set_transport, timeout):
            assert set_transport is False
            assert timeout == 3
            return connection

        def transport(self, conn):
            assert conn is connection

    with pytest.raises(TimeoutError):
        FireTVService("192.0.2.1", timeout_seconds=3)._shell(Device(), "test")
    assert connection.closed


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        FireTVService("192.0.2.1", timeout_seconds=timeout)


def test_adb_host_command_times_out_against_unresponsive_server():
    # A listening TCP socket accepts the connection but sends no ADB response.
    # This exercises the installed ppadb library, not a mocked timeout keyword.
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = TimeoutAdbClient(timeout_seconds=0.1)
        client.port = server.getsockname()[1]
        with pytest.raises(TimeoutError):
            client.devices()
        connection, _ = server.accept()
        connection.close()
