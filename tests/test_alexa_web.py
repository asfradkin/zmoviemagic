"""Signed synthetic Alexa events; certificate downloads and TV calls are mocked."""
import base64
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from functools import partial
import importlib
import json
from threading import Event
from types import SimpleNamespace

import pytest

pytest.importorskip("ask_sdk_webservice_support", reason="Install requirements-alexa.txt for Alexa verification tests")
from ask_sdk_webservice_support import verifier as amazon_sdk
from certvalidator import ValidationContext
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from alexa.verification import AmazonVerifier
from alexa.web import authorized, read_event, validate_settings
from tests.test_api import client
from tests.test_alexa_skill import movie_skill
from tests.test_dispatcher import terminal


SKILL = "amzn1.ask.skill.test-skill"
OWNER = "amzn1.ask.account.test-owner"
CERT_URL = "https://s3.amazonaws.com/echo.api/test-cert.pem"


@pytest.fixture(scope="module")
def signing_keys():
    """Create a test CA and signing leaf. No production key is read or stored."""
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Only Root")])
    root = (x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
            .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .sign(root_key, hashes.SHA256()))
    def leaf(domain="echo-api.amazon.com", expired=False):
        return (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
                .issuer_name(root_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(hours=2))
                .not_valid_after(now - timedelta(hours=1) if expired else now + timedelta(hours=2))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
                .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
                .sign(root_key, hashes.SHA256()))
    return root, leaf_key, leaf


def alexa_event(title="Luca", **overrides):
    identity = {"application": {"applicationId": SKILL}, "user": {"userId": OWNER}}
    event = {"version": "1.0", "context": {"System": identity},
             "session": {**identity, "attributes": {}},
             "request": {"type": "IntentRequest", "locale": "en-US", "requestId": "voice-event-1",
                         "timestamp": datetime.now(timezone.utc).isoformat(),
                         "intent": {"name": "PlayMovieIntent", "slots": {"MovieTitle": {"value": title}}}}}
    event["request"].update(overrides)
    return event


@pytest.fixture
def alexa_http(client, movie_skill, signing_keys, monkeypatch):
    module = importlib.import_module("app")
    settings = SimpleNamespace(**{name: getattr(module.Config, name) for name in dir(module.Config) if name.isupper()})
    settings.ALEXA_ENABLED, settings.ALEXA_SKILL_ID, settings.ALEXA_USER_ID = True, SKILL, OWNER
    settings.MOVIES_FILE = movie_skill[0].movies_file
    app = module.create_app(settings)
    app.testing = True
    fake = movie_skill[1].firetv_service
    monkeypatch.setattr(app.extensions["firetv_service"], "launch_movie_bounded", fake.launch_movie_bounded)
    monkeypatch.setattr(app.extensions["firetv_service"], "launch_movie", fake.launch_movie)
    root, key, leaf = signing_keys
    root_bytes = root.public_bytes(serialization.Encoding.DER)
    context = ValidationContext(trust_roots=[root_bytes], allow_fetching=False)
    monkeypatch.setattr(amazon_sdk, "CertificateValidator", partial(amazon_sdk.CertificateValidator, validation_context=context))
    chain = leaf().public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM)
    downloads = []
    def download(url):
        downloads.append(url)
        return chain
    monkeypatch.setattr(app.extensions["alexa_verifier"], "fetch_certificate", download)
    http = app.test_client()
    def post(event=None, *, raw=None, headers=None, **kwargs):
        raw = json.dumps(event if event is not None else alexa_event()) if raw is None else raw
        signed = base64.b64encode(key.sign(raw.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()
        return http.post("/alexa", data=raw, content_type="application/json",
                         headers={"Signature-256": signed, "SignatureCertChainUrl": CERT_URL, **(headers or {})}, **kwargs)
    yield http, app, post, movie_skill[3], downloads
    app.extensions["playback_service"].shutdown()
    app.extensions["alexa_executor"].shutdown(wait=True)


def test_signed_request_works_without_remote_api_or_lan_trust(alexa_http):
    http, app, post, calls, downloads = alexa_http
    result = post(environ_overrides={"REMOTE_ADDR": "192.0.2.99"})
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in result.headers
    principal = next(iter(app.extensions["playback_service"]._jobs.values()))["principal"]
    assert principal.startswith("alexa-") and OWNER not in principal
    job = app.extensions["playback_service"].status(principal=principal)["request"]
    terminal(app.extensions["playback_service"], job["request_id"], principal)
    assert calls == ["private-luca"]
    assert post().json == result.json
    assert calls == ["private-luca"]
    assert downloads == [CERT_URL]
    assert http.get("/remote/api/movies").status_code == 404
    assert http.get("/api/status", environ_overrides={"REMOTE_ADDR": "192.0.2.99"}).status_code == 403


@pytest.mark.parametrize("where,field,value", [("context", "application", "wrong-skill"),
    ("session", "application", "wrong-skill"), ("context", "user", "wrong-user"), ("session", "user", "wrong-user")])
def test_signed_wrong_identity_never_launches(alexa_http, where, field, value):
    _, _, post, calls, _ = alexa_http
    event = alexa_event()
    event = json.loads(json.dumps(event))
    container = event["context"]["System"] if where == "context" else event["session"]
    container[field]["applicationId" if field == "application" else "userId"] = value
    assert post(event).status_code == 403
    assert calls == []


def test_tampering_invalid_signature_and_missing_headers_rejected(alexa_http):
    http, _, post, calls, _ = alexa_http
    assert post(headers={"Signature-256": "not-base64"}).status_code == 400
    assert post(headers={"Signature-256": ""}).status_code == 400
    assert http.post("/alexa", json=alexa_event(), headers={"Authorization": "Bearer ignored"}).status_code == 400
    assert calls == []


def test_signature_for_another_body_is_rejected(alexa_http, signing_keys):
    _, _, post, calls, _ = alexa_http
    raw = json.dumps(alexa_event("Luca"))
    signature = base64.b64encode(signing_keys[1].sign(raw.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    assert post(raw=raw.replace("Luca", "Frozen"), headers={"Signature-256": signature}).status_code == 400
    assert calls == []


@pytest.mark.parametrize("seconds,accepted", [(-150, True), (150, True), (-150.001, False), (150.001, False)])
def test_exact_timestamp_boundaries(monkeypatch, seconds, accepted):
    import alexa.web as web
    fixed = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed
    monkeypatch.setattr(web, "datetime", Clock)
    event = alexa_event(timestamp=(fixed + timedelta(seconds=seconds)).isoformat())
    if accepted:
        assert read_event(json.dumps(event))["request"]["requestId"] == "voice-event-1"
    else:
        with pytest.raises(ValueError):
            read_event(json.dumps(event))


def test_disabled_settings_do_not_import_optional_packages(monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "alexa.verification":
            pytest.fail("Disabled Alexa imported verification dependencies")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    validate_settings(SimpleNamespace(ALEXA_ENABLED=False))


@pytest.mark.parametrize("seconds", [-151, 151])
def test_expired_or_future_request_rejected_without_fetch(alexa_http, seconds):
    _, _, post, calls, downloads = alexa_http
    stamp = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    assert post(alexa_event(timestamp=stamp)).status_code == 400
    assert calls == [] and downloads == []


@pytest.mark.parametrize("url", ["http://s3.amazonaws.com/echo.api/test.pem", "https://evil.example/echo.api/test.pem",
    "https://s3.amazonaws.com:444/echo.api/test.pem", "https://user@s3.amazonaws.com/echo.api/test.pem",
    "https://s3.amazonaws.com/echo.api/../secret.pem", CERT_URL + "?x=1", CERT_URL + "#fragment",
    "https://s3.amazonaws.com/echo.api/%2e%2e/test.pem"])
def test_certificate_urls_are_allowlisted_before_fetch(alexa_http, url):
    _, _, post, calls, downloads = alexa_http
    assert post(headers={"SignatureCertChainUrl": url}).status_code == 400
    assert calls == [] and downloads == []


@pytest.mark.parametrize("kind", ["untrusted", "wrong-domain", "expired"])
def test_real_certificate_validation_failures(alexa_http, signing_keys, monkeypatch, kind):
    _, app, post, calls, _ = alexa_http
    root, _, leaf = signing_keys
    if kind == "untrusted":
        # Remove the test CA. A self-issued certificate must not become trusted.
        monkeypatch.setattr(amazon_sdk, "CertificateValidator", partial(
            amazon_sdk.CertificateValidator.func, validation_context=ValidationContext(trust_roots=[], allow_fetching=False)))
    chain = leaf("wrong.example" if kind == "wrong-domain" else "echo-api.amazon.com",
                 expired=kind == "expired").public_bytes(serialization.Encoding.PEM)
    chain += root.public_bytes(serialization.Encoding.PEM)
    monkeypatch.setattr(app.extensions["alexa_verifier"], "fetch_certificate", lambda url: chain)
    assert post().status_code == 400
    assert calls == []


@pytest.mark.parametrize("body", ['{}', '[]', '{"version":"1.0","version":"1.0"}', '{"x":NaN}', '"' + 'x' * 32769 + '"'])
def test_invalid_json_and_body_limits_no_verification(alexa_http, body):
    _, _, post, calls, downloads = alexa_http
    assert post(raw=body).status_code in {400, 413}
    assert calls == [] and downloads == []


def test_read_only_or_alternate_routes_do_not_verify(alexa_http):
    http, _, post, calls, downloads = alexa_http
    for path in ("/alexa/", "/remote/alexa", "/api/alexa"):
        assert http.post(path, json=alexa_event()).status_code in {403, 404}
    assert http.get("/alexa").status_code == 405
    assert http.open("/alexa", method="OPTIONS").status_code == 405
    assert post(environ_overrides={"RAW_URI": "/%61lexa"}).status_code == 400
    assert post(environ_overrides={"RAW_URI": "/alexa?"}).status_code == 400
    assert calls == [] and downloads == []


def test_disabled_does_not_register_or_trust_cookie(client):
    http, app = client
    assert http.post("/alexa", json=alexa_event()).status_code == 404
    assert "alexa_verifier" not in app.extensions


@pytest.mark.parametrize("skill,user", [("", OWNER), (SKILL, ""), ("wrong", OWNER), (SKILL, "amzn1.ask.account.REPLACE_ME")])
def test_enabled_settings_fail_closed(skill, user):
    with pytest.raises(ValueError):
        validate_settings(SimpleNamespace(ALEXA_ENABLED=True, ALEXA_SKILL_ID=skill, ALEXA_USER_ID=user))


def test_timeout_keeps_single_slot_and_late_verification_cannot_launch(alexa_http, monkeypatch):
    _, app, post, calls, _ = alexa_http
    entered, release = Event(), Event()
    def blocked(*args):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(app.extensions["alexa_verifier"], "verify_body", blocked)
    executor = app.extensions["alexa_executor"]
    real_submit = executor.submit
    futures = []
    def submit(*args):
        future = real_submit(*args)
        futures.append(future)
        def immediate_timeout(timeout=None):
            assert entered.wait(1)
            raise FutureTimeout()
        monkeypatch.setattr(future, "result", immediate_timeout)
        return future
    monkeypatch.setattr(executor, "submit", submit)
    try:
        assert post().status_code == 503
        assert post().status_code == 503
        assert len(futures) == 1 and calls == []
    finally:
        release.set()


def test_verification_error_never_leaks_details(alexa_http, monkeypatch, caplog):
    _, app, post, calls, _ = alexa_http
    def fail(*args):
        raise RuntimeError("TEST_PRIVATE_DIAGNOSTIC")
    monkeypatch.setattr(app.extensions["alexa_verifier"], "verify_body", fail)
    response = post()
    assert response.status_code == 400
    assert "TEST_PRIVATE_DIAGNOSTIC" not in response.text + caplog.text
    assert OWNER not in response.text + caplog.text
    assert calls == []
