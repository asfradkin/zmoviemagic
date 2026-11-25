"""Bound the SDK's certificate download and the dedicated proxy policy."""
from pathlib import Path
import re

import pytest

pytest.importorskip("ask_sdk_webservice_support", reason="Install requirements-alexa.txt")
from alexa.verification import AmazonVerifier
from tests.test_alexa_web import alexa_http, signing_keys
from tests.test_api import client
from tests.test_alexa_skill import movie_skill


URL = "https://s3.amazonaws.com/echo.api/test.pem"


@pytest.fixture
def transport(monkeypatch):
    import alexa.verification as module
    class Response:
        status = 200
        body = b"-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----"
        def read1(self, size):
            chunk, self.body = self.body[:size], self.body[size:]
            return chunk
    class Connection:
        sock = None
        closed = False
        response = Response()
        def request(self, method, path, headers):
            self.requested = (method, path, headers)
        def getresponse(self):
            return self.response
        def close(self):
            self.closed = True
    connection = Connection()
    def connect(host, timeout):
        assert host == "s3.amazonaws.com" and timeout == 1
        return connection
    monkeypatch.setattr(module.http.client, "HTTPSConnection", connect)
    return connection


def test_certificate_fetch_is_fixed_host_and_always_closes(transport):
    assert AmazonVerifier.fetch_certificate(URL).startswith(b"-----BEGIN CERTIFICATE-----")
    assert transport.requested[:2] == ("GET", "/echo.api/test.pem")
    assert transport.closed


@pytest.mark.parametrize("status", [301, 302, 403, 500])
def test_certificate_redirects_and_errors_are_not_followed(transport, status):
    transport.response.status = status
    with pytest.raises(Exception, match="download failed"):
        AmazonVerifier.fetch_certificate(URL)
    assert transport.closed


def test_certificate_size_and_chain_count_are_bounded(transport):
    transport.response.body = b"x" * 65537
    with pytest.raises(Exception, match="too large"):
        AmazonVerifier.fetch_certificate(URL)
    assert transport.closed
    transport.response.body = b"-----BEGIN CERTIFICATE-----" * 9
    with pytest.raises(Exception, match="Invalid certificate chain"):
        AmazonVerifier.fetch_certificate(URL)


def test_certificate_absolute_deadline(transport, monkeypatch):
    import alexa.verification as module
    ticks = iter([0, 4])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        AmazonVerifier.fetch_certificate(URL)
    assert transport.closed


def test_certificate_cache_is_capped_and_expires(monkeypatch):
    verifier = AmazonVerifier()
    now = [0]
    import alexa.verification as module
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    fetched = []
    monkeypatch.setattr(verifier, "fetch_certificate", lambda url: fetched.append(url) or b"mock certificate")
    monkeypatch.setattr(verifier, "_validate_cert_chain", lambda data: None)
    for n in range(6):
        verifier._load_cert_chain(URL + str(n))
    assert len(verifier._cert_cache) == 4
    verifier._load_cert_chain(URL + "5")
    assert len(fetched) == 6
    now[0] = 3601
    verifier._load_cert_chain(URL + "5")
    assert len(fetched) == 7 and len(verifier._cert_cache) == 1


def test_aggregate_admission_caps_verification_before_fetch(alexa_http):
    _, app, post, calls, downloads = alexa_http
    limiter = app.extensions["rate_limit_service"]
    limiter.clock = lambda: 0
    for _ in range(4):
        limiter.consume("alexa", "all-callers")
    assert post().status_code == 429
    assert calls == [] and downloads == []


def proxy_allows(uri):
    config = (Path(__file__).resolve().parents[1] / "ops/nginx/zmoviemagic-alexa.conf.example").read_text()
    return any(re.fullmatch(pattern, uri) for pattern in re.findall(r"^\s*~([^\n]+?)\s+1;", config, re.M))


@pytest.mark.parametrize("uri", ["/", "/health", "/api/play", "/remote/api/play", "/play/luca", "/alexa/",
    "/alexa?", "/alexa?x=1", "/%61lexa", "/alexa%2f", "/x/../alexa", "//alexa", "/alexa/."])
def test_proxy_denies_everything_except_exact_alexa(uri):
    assert not proxy_allows(uri)


def test_proxy_and_tunnel_keep_machine_api_isolated():
    root = Path(__file__).resolve().parents[1]
    config = (root / "ops/nginx/zmoviemagic-alexa.conf.example").read_text()
    assert proxy_allows("/alexa")
    for required in ["listen 127.0.0.1:8082", "proxy_pass_request_headers off;", "proxy_next_upstream off;",
                     "Signature-256 $http_signature_256", "SignatureCertChainUrl $http_signaturecertchainurl",
                     "if ($request_method != POST)", "limit_req", "limit_conn", "client_max_body_size 32k;",
                     "location / { return 404; }"]:
        assert required in config
    assert config.count("proxy_pass ") == 1
    assert "/remote/api/" not in config
    tunnel = (root / "ops/cloudflared/alexa-config.yml.example").read_text()
    assert "path: ^/alexa$" in tunnel and "http_status:404" in tunnel
    assert "127.0.0.1:8082" in tunnel
