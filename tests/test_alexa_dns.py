"""DNS changes use a fake API throughout; never contact real GoDaddy or ipify."""
import copy
import os
from urllib.error import HTTPError, URLError

import pytest

from tools import update_alexa_dns as dns


@pytest.fixture
def api(monkeypatch):
    state = {
        "record": {"recordId": "opaque_record-id", "name": "movies-api", "type": "A",
                   "data": "8.8.8.8", "ttl": 600},
        "ip": "1.1.1.1", "calls": [], "count": 1,
    }

    def fake(url, token=None, payload=None):
        state["calls"].append((url, token, copy.deepcopy(payload)))
        if url == dns.LOOKUP_URL:
            return {"items": [copy.deepcopy(state["record"])], "totalItems": state["count"]}
        if url == dns.PUBLIC_IP_URL:
            return {"ip": state["ip"]}
        if url == dns.RECORDS_URL + "/opaque_record-id":
            return dict(payload)
        pytest.fail("Unexpected URL: " + url)

    monkeypatch.setattr(dns, "http_json", fake)
    return state


def test_check_mode_never_writes_or_sends_token_to_ip_service(api):
    assert "CHECK ONLY" in dns.sync_dns("private-test-token")
    assert api["calls"] == [(dns.LOOKUP_URL, "private-test-token", None),
                            (dns.PUBLIC_IP_URL, None, None)]


def test_apply_changes_one_existing_record_and_preserves_ttl(api):
    api["record"]["ttl"] = 3600
    assert "Updated" in dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 3
    assert api["calls"][-1] == (dns.RECORDS_URL + "/opaque_record-id", "private-test-token",
                                 {"name": "movies-api", "type": "A", "data": "1.1.1.1", "ttl": 3600})


def test_unchanged_record_is_not_written_even_with_apply(api):
    api["ip"] = "8.8.8.8"
    assert "already current" in dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 2


@pytest.mark.parametrize("change", [
    {"name": "@"}, {"name": "www"}, {"type": "MX"}, {"type": "CNAME"},
    {"recordId": "../other-record"}, {"recordId": None}, {"ttl": True}, {"ttl": 599},
    {"data": "192.168.68.106"},
])
def test_unexpected_record_cannot_be_modified(api, change):
    api["record"].update(change)
    with pytest.raises(dns.DNSUpdateError):
        dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 1


@pytest.mark.parametrize("count", [0, 2, 100])
def test_missing_duplicate_or_paginated_record_refuses_update(api, count):
    api["count"] = count
    with pytest.raises(dns.DNSUpdateError):
        dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 1


@pytest.mark.parametrize("ip", [None, "", "bad", "::1", "192.168.1.1", "127.0.0.1",
                                   "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255"])
def test_ip_detection_failure_never_writes(api, ip):
    api["ip"] = ip
    with pytest.raises(dns.DNSUpdateError):
        dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 2


def test_ambiguous_write_is_not_immediately_retried(api, monkeypatch):
    fake = dns.http_json

    def timeout_on_write(url, token=None, payload=None):
        result = fake(url, token, payload)
        if payload is not None:
            raise dns.DNSUpdateError("Network request failed; no immediate retry was sent")
        return result

    monkeypatch.setattr(dns, "http_json", timeout_on_write)
    with pytest.raises(dns.DNSUpdateError):
        dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 3


@pytest.mark.parametrize("failure", [HTTPError(dns.LOOKUP_URL, 401, "private-test-token", {}, None),
                                    URLError("private-test-token")])
def test_transport_errors_hide_private_details(monkeypatch, failure):
    class FakeOpener:
        def open(self, request, timeout):
            assert timeout == 5
            raise failure

    monkeypatch.setattr(dns, "build_opener", lambda *args: FakeOpener())
    with pytest.raises(dns.DNSUpdateError) as error:
        dns.http_json(dns.LOOKUP_URL, "private-test-token")
    assert "private-test-token" not in str(error.value)


def test_redirect_is_refused():
    with pytest.raises(dns.DNSUpdateError):
        dns.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example/")


@pytest.mark.parametrize("body", [b"not json", b"[]", b"x" * (dns.MAX_RESPONSE + 1)])
def test_invalid_response_is_bounded_and_refused(monkeypatch, body):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == dns.MAX_RESPONSE + 1
            return body[:size]

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr(dns, "build_opener", lambda *args: FakeOpener())
    with pytest.raises(dns.DNSUpdateError):
        dns.http_json(dns.LOOKUP_URL, "private-test-token")


def test_private_token_file(tmp_path):
    path = tmp_path / "token"
    path.write_text("private-test-token\n", encoding="ascii")
    path.chmod(0o600)
    assert dns.read_token(path) == "private-test-token"
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(dns.DNSUpdateError):
            dns.read_token(path)


def test_cli_defaults_to_check_and_does_not_leak_token(api, tmp_path, capsys):
    path = tmp_path / "token"
    path.write_text("private-test-token", encoding="ascii")
    path.chmod(0o600)
    assert dns.main(["--token-file", str(path)]) == 0
    assert "CHECK ONLY" in capsys.readouterr().out
    assert len(api["calls"]) == 2


@pytest.mark.parametrize("listing", [{}, {"items": [], "totalItems": 0},
                                    {"items": [{}, {}], "totalItems": 2},
                                    {"items": [{}], "totalItems": 1, "totalPages": 2}])
def test_bad_listing_cannot_trigger_any_further_network_work(monkeypatch, listing):
    calls = []

    def fake(url, token=None, payload=None):
        calls.append(url)
        return listing

    monkeypatch.setattr(dns, "http_json", fake)
    with pytest.raises(dns.DNSUpdateError):
        dns.sync_dns("private-test-token", apply=True)
    assert calls == [dns.LOOKUP_URL]


def test_unconfirmed_put_response_is_not_repeated(api, monkeypatch):
    fake = dns.http_json

    def wrong_response(url, token=None, payload=None):
        result = fake(url, token, payload)
        return {} if payload is not None else result

    monkeypatch.setattr(dns, "http_json", wrong_response)
    with pytest.raises(dns.DNSUpdateError, match="unconfirmed"):
        dns.sync_dns("private-test-token", apply=True)
    assert len(api["calls"]) == 3


@pytest.mark.parametrize("value", ["", "token with spaces", "token\nsecond-token", "x" * 4097])
def test_invalid_token_file_never_contacts_network(api, tmp_path, value):
    path = tmp_path / "token"
    path.write_text(value, encoding="ascii")
    path.chmod(0o600)
    assert dns.main(["--token-file", str(path)]) == 1
    assert api["calls"] == []
