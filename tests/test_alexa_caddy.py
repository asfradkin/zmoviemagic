"""Use a disposable Caddy instance, HTTP loopback and a fake upstream only."""
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
import time

import pytest
from flask import Flask, jsonify, request as flask_request
from werkzeug.serving import make_server


CADDY = shutil.which("caddy")
TEMPLATE = Path(__file__).resolve().parents[1] / "ops/caddy/Caddyfile.alexa.example"


@pytest.mark.skipif(CADDY is None, reason="Caddy absent; native edge checks remain pending")
def test_production_caddy_template_adapts_without_starting_or_issuing_certificates():
    # adapt parses the real production template but never starts listeners or ACME.
    result = subprocess.run([CADDY, "adapt", "--config", str(TEMPLATE), "--adapter", "caddyfile"],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    config = json.loads(result.stdout)
    policies = config["apps"]["tls"]["automation"]["policies"]
    api = next(policy for policy in policies if "movies-api.fradkin.net" in policy.get("subjects", []))
    assert api["issuers"][0]["module"] == "acme"
    assert api["issuers"][0]["challenges"]["http"]["disabled"] is True
    lan = next(policy for policy in policies if "moviemagic.fradkin.net" in policy.get("subjects", []))
    assert lan["issuers"][0]["module"] == "internal"


@pytest.fixture(params=[True, False], ids=["home-peer", "outside-peer"])
def caddy_edge(request, tmp_path):
    if CADDY is None:
        pytest.skip("Caddy absent; native edge checks remain pending")
    calls = []
    fake = Flask("fake-upstream")
    @fake.route("/", defaults={"path": ""}, methods=["GET", "POST"])
    @fake.route("/<path:path>", methods=["GET", "POST"])
    def echo(path):
        body = flask_request.get_data()
        calls.append((path, body))
        return jsonify({"body": body.decode(), "signature": flask_request.headers.get("Signature-256"),
                        "certificate": flask_request.headers.get("SignatureCertChainUrl"),
                        "host": flask_request.host})
    upstream = make_server("127.0.0.1", 0, fake, threaded=True)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home_peer = request.param
    template = TEMPLATE.read_text()
    template = template.replace("moviemagic.fradkin.net {", f"http://moviemagic.fradkin.net:{port} {{")
    template = template.replace("movies-api.fradkin.net {", f"http://movies-api.fradkin.net:{port} {{")
    template = template.replace("    tls internal\n", "    bind 127.0.0.1\n")
    tls = "    tls {\n        issuer acme {\n            disable_http_challenge\n        }\n    }"
    template = template.replace(tls, "    bind 127.0.0.1")
    # Only this test subnet changes: simulate an untrusted peer on loopback without
    # publishing a real listener or trusting user-supplied forwarding headers.
    if not home_peer:
        template = template.replace("192.168.68.0/22 127.0.0.1 ::1", "192.0.2.0/24")
    template = template.replace("127.0.0.1:8000", f"127.0.0.1:{upstream.server_port}")
    template = template.replace("127.0.0.1:8082", f"127.0.0.1:{upstream.server_port}")
    config = tmp_path / "Caddyfile"
    template = template.replace("{\n", "{\n    admin off\n    auto_https off\n", 1)
    config.write_text(template)
    log = tmp_path / "caddy.log"
    process = None
    def send(path, method="GET", body=None, *, host="movies-api.fradkin.net", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(method, path, body=body, headers={"Host": host, **(headers or {})})
            result = connection.getresponse()
            return result.status, result.read()
        finally:
            connection.close()
    try:
        with log.open("wb") as output:
            process = subprocess.Popen([CADDY, "run", "--config", str(config), "--adapter", "caddyfile"],
                                       stdout=output, stderr=output,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 5
            while True:
                try:
                    send("/")
                    break
                except OSError:
                    if time.monotonic() >= deadline or process.poll() is not None:
                        pytest.fail(log.read_text(errors="replace"))
                    time.sleep(.05)
            yield send, calls, home_peer
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        upstream.shutdown()
        thread.join(timeout=5)
        upstream.server_close()


def test_caddy_blocks_normalization_queries_and_other_routes(caddy_edge):
    send, calls, _ = caddy_edge
    for path in ("/", "/health", "/play/luca", "/api/play", "/remote/api/play", "/alexa/", "/alexa?",
                 "/alexa?x=1", "/%61lexa", "//alexa", "/x/../alexa", "/alexa%2f", "/ALExa"):
        assert send(path, "POST", "{}")[0] == 404, path
    for method in ("GET", "PUT", "DELETE", "OPTIONS", "HEAD"):
        assert send("/alexa", method)[0] == 404
    assert calls == []


def test_caddy_preserves_body_signature_and_upstream_host(caddy_edge):
    send, calls, _ = caddy_edge
    body = '{"request": "synthetic only", "spacing":   true}'
    status, result = send("/alexa", "POST", body,
                          headers={"Content-Type": "application/json", "Signature-256": "synthetic-signature",
                                   "SignatureCertChainUrl": "https://s3.amazonaws.com/echo.api/test.pem"})
    assert status == 200
    response = json.loads(result)
    assert response["body"] == body
    assert response["signature"] == "synthetic-signature"
    assert response["certificate"].endswith("/echo.api/test.pem")
    assert response["host"] == "movies-api.fradkin.net"
    assert len(calls) == 1


def test_existing_grid_cannot_be_published_by_forwarded_identity(caddy_edge):
    send, calls, home_peer = caddy_edge
    status, _ = send("/", host="moviemagic.fradkin.net", headers={
        "X-Forwarded-For": "192.168.68.112", "X-Real-IP": "192.168.68.112"})
    assert status == (200 if home_peer else 403)
    assert len(calls) == (1 if home_peer else 0)


def test_caddy_caps_post_body(caddy_edge):
    send, calls, _ = caddy_edge
    # Caddy 2.6 reports a streaming size failure as 502; newer versions use 413.
    # In either case, no complete body reaches the upstream handler.
    assert send("/alexa", "POST", "x" * 32769)[0] in {413, 502}
    assert calls == []
