from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import time

import pytest

from services.firetv_service import DeliveryError
from services.playback_service import APIError, CooldownError, PlaybackService
from tests.test_catalog_v2 import load_catalog, row


@pytest.fixture
def dispatcher(tmp_path):
    class FireTV:
        def __init__(self):
            self.entered, self.release = Event(), Event()
            self.calls = []
            self.error = None

        def launch_movie_bounded(self, provider_id, budget_seconds):
            assert budget_seconds == 15
            self.calls.append(provider_id)
            self.entered.set()
            assert self.release.wait(3)
            if self.error:
                raise self.error
            return {"connection": "connected"}

        def launch_movie(self, provider_id):
            self.launch_movie_bounded(provider_id, 15)
            return {"retried": False}

    firetv = FireTV()
    catalog = load_catalog(tmp_path, [row(), row("moana", title="Moana", id="moana-private")])
    service = PlaybackService(firetv, cooldown_seconds=0, movie_service=catalog)
    yield service, firetv
    firetv.release.set()
    service.shutdown()


def terminal(service, request_id, principal="lan-household"):
    # Bounded synchronization wait, never a real device operation.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = service.status(request_id, principal)["request"]
        if record["command_state"] not in ("queued", "dispatching"):
            return record
        time.sleep(0.001)
    pytest.fail("worker did not complete")


def test_twenty_concurrent_requests_accept_only_one(dispatcher):
    service, firetv = dispatcher
    barrier = Barrier(20)
    def submit(index):
        barrier.wait(timeout=3)
        try:
            return service.submit_play("luca", "lan-household", f"request-{index:03}")
        except APIError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(submit, range(20)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("busy") == 19
    assert firetv.entered.wait(3)
    assert len(firetv.calls) == 1


def test_original_queued_response_reused_after_terminal(dispatcher):
    service, firetv = dispatcher
    response = service.submit_play("luca", "lan-household", "same-key-001")
    assert response["command_state"] == "queued"
    assert firetv.entered.wait(3)
    assert service.status(response["request_id"])["request"]["command_state"] == "dispatching"
    assert service.submit_play("luca", "lan-household", "same-key-001") == response
    with pytest.raises(APIError) as error:
        service.submit_play("moana", "lan-household", "same-key-001")
    assert error.value.code == "idempotency_conflict"
    firetv.release.set()
    assert terminal(service, response["request_id"])["command_state"] == "command_sent"
    assert service.submit_play("luca", "lan-household", "same-key-001") == response
    assert len(firetv.calls) == 1
    assert service.status()["playback"] == {"state": "unknown", "evidence": "none"}


def test_concurrent_duplicate_requests_dispatch_once(dispatcher):
    service, firetv = dispatcher
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: service.submit_play("luca", "lan-household", "same-key-001"), range(20)))
    assert all(result == results[0] for result in results)
    assert firetv.entered.wait(3)
    assert len(firetv.calls) == 1


@pytest.mark.parametrize("legacy_first", [True, False])
def test_legacy_and_api_share_reservation(dispatcher, legacy_first):
    service, firetv = dispatcher
    if legacy_first:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.play, "unknown-valid-id")
            assert firetv.entered.wait(3)
            with pytest.raises(APIError) as error:
                service.submit_play("luca", "lan-household", "request-001")
            assert error.value.code == "busy"
            assert service._idempotency == {}
            firetv.release.set()
            assert future.result()["status"] == "success"
    else:
        service.submit_play("luca", "lan-household", "request-001")
        assert firetv.entered.wait(3)
        with pytest.raises(CooldownError, match="busy"):
            service.play("unknown-valid-id")
    assert len(firetv.calls) == 1


@pytest.mark.parametrize("error,state,code", [
    (DeliveryError("device_unauthorized", connection="unauthorized"), "failed", "device_unauthorized"),
    (DeliveryError("command_rejected", connection="connected"), "failed", "command_rejected"),
    (DeliveryError("delivery_unknown", "unknown"), "unknown", "delivery_unknown"),
    (RuntimeError("private raw diagnostic"), "unknown", "internal_error"),
])
def test_worker_survives_errors_and_releases_slot(dispatcher, error, state, code, caplog):
    service, firetv = dispatcher
    firetv.error = error
    firetv.release.set()
    first = service.submit_play("luca", "lan-household", "request-001")
    result = terminal(service, first["request_id"])
    assert result["command_state"] == state
    assert result["error"]["code"] == code
    assert "private raw diagnostic" not in str(service.status()) + caplog.text
    firetv.error = None
    second = service.submit_play("moana", "lan-household", "request-002")
    assert terminal(service, second["request_id"])["command_state"] == "command_sent"


def test_capacity_ttl_cooldown_and_active_preservation(dispatcher):
    service, firetv = dispatcher
    now = [100.0]
    service._clock = lambda: now[0]
    service.max_records = 1
    service.retention_seconds = 10
    service.cooldown_seconds = 2
    first = service.submit_play("luca", "lan-household", "request-001")
    assert firetv.entered.wait(3)
    now[0] += 20
    assert service.status(first["request_id"])["request"]["command_state"] == "dispatching"
    firetv.release.set()
    terminal(service, first["request_id"])
    with pytest.raises(APIError) as error:
        service.submit_play("moana", "lan-household", "request-002")
    assert error.value.code == "dispatcher_unavailable"
    now[0] += 10
    with pytest.raises(APIError) as error:
        service.status(first["request_id"])
    assert error.value.code == "request_not_found"
    assert not service._idempotency
    service.submit_play("moana", "lan-household", "request-002")


def test_failed_attempt_consumes_cooldown_at_dispatch(dispatcher):
    service, firetv = dispatcher
    service.cooldown_seconds = 2
    firetv.error = DeliveryError("device_unavailable")
    firetv.release.set()
    first = service.submit_play("luca", "lan-household", "request-001")
    terminal(service, first["request_id"])
    with pytest.raises(APIError) as error:
        service.submit_play("moana", "lan-household", "request-002")
    assert error.value.code == "cooldown"
    assert error.value.retry_after >= 1


def test_restart_principal_and_shutdown(dispatcher):
    service, firetv = dispatcher
    first = service.submit_play("luca", "lan-household", "request-001")
    with pytest.raises(APIError):
        service.status(first["request_id"], "someone-else")
    replacement = PlaybackService(firetv)
    assert replacement.boot_id != service.boot_id
    assert replacement.status()["request"] is None
    with pytest.raises(APIError):
        replacement.status(first["request_id"])
    firetv.release.set()
    service.shutdown()
    with pytest.raises(APIError) as error:
        service.submit_play("moana", "lan-household", "request-002")
    assert error.value.code == "dispatcher_unavailable"


def test_worker_start_failure_does_not_accept_or_consume_key(dispatcher, monkeypatch):
    service, firetv = dispatcher
    def fail(_):
        raise RuntimeError("thread unavailable")
    monkeypatch.setattr("services.playback_service.Thread.start", fail)
    with pytest.raises(APIError) as error:
        service.submit_play("luca", "lan-household", "request-001")
    assert error.value.code == "dispatcher_unavailable"
    assert service._jobs == service._idempotency == {}
    assert service._active is None
    assert not firetv.calls


def test_queued_status_precedes_dispatch_and_shutdown_keeps_active_reservation(dispatcher, monkeypatch):
    service, firetv = dispatcher
    worker_gate = Event()
    original = service._run
    def paused_worker():
        assert worker_gate.wait(3)
        original()
    monkeypatch.setattr(service, "_run", paused_worker)
    response = service.submit_play("luca", "lan-household", "request-001")
    try:
        assert service.status(response["request_id"])["request"]["command_state"] == "queued"
        assert not firetv.calls
        worker_gate.set()
        assert firetv.entered.wait(3)
        service.shutdown_grace = 0
        service.shutdown()
        assert service._active == response["request_id"]
        assert service._worker.is_alive()
        with pytest.raises(APIError) as error:
            service.submit_play("moana", "lan-household", "request-002")
        assert error.value.code == "dispatcher_unavailable"
    finally:
        worker_gate.set()
        firetv.release.set()
        service._worker.join(timeout=3)
    assert service._active is None
