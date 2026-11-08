import pytest

from services.firetv_service import BudgetAdbClient, BudgetConnection, CommandBudget, DeliveryError, FireTVService


class FakeConnection:
    def __init__(self, output=b"Starting: Intent", error=None):
        self.output, self.error = output, error
        self.commands = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def send(self, command):
        self.commands.append(command)
        if self.error:
            raise self.error

    def read_all(self):
        return self.output


class FakeDevice:
    def __init__(self, connection):
        self.connection = connection

    def create_connection(self, **kwargs):
        return self.connection

    def transport(self, connection):
        pass


@pytest.mark.parametrize("output,code", [(b"Starting: Intent", None), (b"", None),
    (b"Error: Activity not started", "command_rejected"),
    (b"java.lang.Exception: private diagnostic", "command_rejected"),
    (b"unable to resolve Intent", "command_rejected")])
def test_launch_output_classification_and_exact_template(monkeypatch, output, code):
    service = FireTVService("192.0.2.1")
    connection = FakeConnection(output)
    monkeypatch.setattr(service, "_get_budget_device", lambda *a, **k: FakeDevice(connection))
    if code:
        with pytest.raises(DeliveryError) as error:
            service.launch_movie_bounded("luca-id")
        assert error.value.code == code
    else:
        assert service.launch_movie_bounded("luca-id") == {"connection": "connected"}
    assert connection.closed
    assert connection.commands == ['shell:input keyevent 224 && input keyevent 3 && '
        'am start -a android.intent.action.VIEW -d "https://www.disneyplus.com/play/luca-id?startTime=0" '
        'com.disney.disneyplus']


@pytest.mark.parametrize("failure,code,state", [(OSError("broken"), "delivery_unknown", "unknown"),
    (TimeoutError(), "delivery_unknown", "unknown"), (RuntimeError("unauthorized"), "device_unauthorized", "failed")])
def test_no_replay_after_send(monkeypatch, failure, code, state):
    service = FireTVService("192.0.2.1")
    connection, setups = FakeConnection(error=failure), []
    def setup(*a, **k):
        setups.append(k)
        return FakeDevice(connection)
    monkeypatch.setattr(service, "_get_budget_device", setup)
    with pytest.raises(DeliveryError) as error:
        service.launch_movie_bounded("luca-id")
    assert (error.value.code, error.value.state) == (code, state)
    assert len(connection.commands) == len(setups) == 1
    assert connection.closed


def test_one_safe_setup_reconnect(monkeypatch):
    service = FireTVService("192.0.2.1")
    connection, setups = FakeConnection(), []
    def setup(budget, force_reconnect):
        setups.append(force_reconnect)
        if not force_reconnect:
            raise OSError("before shell")
        return FakeDevice(connection)
    monkeypatch.setattr(service, "_get_budget_device", setup)
    service.launch_movie_bounded("luca-id")
    assert setups == [False, True]
    assert len(connection.commands) == 1


def test_slow_trickle_deadline_and_output_cap():
    now = [0.0]
    budget = CommandBudget(1, 0.5, lambda: now[0])
    connection = BudgetConnection(budget)
    class SlowSocket:
        def settimeout(self, timeout):
            assert 0 < timeout <= 0.5
        def recv(self, length):
            now[0] += 0.3
            return b"x"
    connection.socket = SlowSocket()
    with pytest.raises(TimeoutError):
        connection.read_all()
    assert now[0] < 1.5
    now[0] = 0
    connection.socket.recv = lambda size: b"x" * size
    with pytest.raises(RuntimeError, match="output limit"):
        connection.read_all()


def test_budget_expiry_closes_connection_without_reconnect(monkeypatch):
    service = FireTVService("192.0.2.1")
    connection, setups = FakeConnection(), []
    def setup(budget, **kwargs):
        setups.append(1)
        def read():
            budget.deadline = 0
            budget.remaining()
        connection.read_all = read
        return FakeDevice(connection)
    monkeypatch.setattr(service, "_get_budget_device", setup)
    with pytest.raises(DeliveryError) as error:
        service.launch_movie_bounded("luca-id")
    assert error.value.state == "unknown"
    assert connection.closed
    assert len(setups) == 1


def test_new_path_does_not_cache_expiring_client_for_legacy(monkeypatch):
    service = FireTVService("192.0.2.1")
    legacy_client = object()
    service._adb_client = legacy_client
    monkeypatch.setattr(BudgetAdbClient, "remote_connect", lambda *a: True)
    monkeypatch.setattr(BudgetAdbClient, "device", lambda *a: object())
    bounded_device = service._get_budget_device(CommandBudget(15, 5))
    assert isinstance(bounded_device.client, BudgetAdbClient)
    cached, error = service.get_device()
    assert error is None
    assert cached.client is legacy_client


def test_fragmented_status_and_full_send_without_raw_debug_log(caplog):
    connection = BudgetConnection(CommandBudget(15, 5))
    class Socket:
        def __init__(self):
            self.chunks = iter([b"O", b"K", b"A", b"Y"])
            self.sent = []
        def settimeout(self, value):
            assert 0 < value <= 5
        def sendall(self, value):
            self.sent.append(value)
        def recv(self, size):
            return next(self.chunks)
    connection.socket = Socket()
    with caplog.at_level("DEBUG"):
        assert connection.send("shell:private-provider-id")
    assert connection.socket.sent == [b"0019shell:private-provider-id"]
    assert "private-provider-id" not in caplog.text
