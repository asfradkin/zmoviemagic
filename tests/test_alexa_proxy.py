"""Native proxy verification when Nginx is available; all upstream work is fake."""
import base64
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
from werkzeug.serving import make_server

pytest.importorskip("ask_sdk_webservice_support", reason="Install requirements-alexa.txt")
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from tests.test_alexa_web import alexa_http, signing_keys, alexa_event, CERT_URL
from tests.test_api import client
from tests.test_alexa_skill import movie_skill


@pytest.mark.skipif(shutil.which("nginx") is None, reason="Nginx absent; native Alexa proxy validation pending")
def test_native_alexa_proxy_denials_and_signature_transport(alexa_http, signing_keys, tmp_path):
    _, app, _, calls, _ = alexa_http
    origin = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app.extensions["auth_service"].hosts |= {"zmm-origin.internal"}
    root = Path(__file__).resolve().parents[1]
    template = (root / "ops/nginx/zmoviemagic-alexa.conf.example").read_text()
    template = template.replace("127.0.0.1:8082", f"127.0.0.1:{port}")
    template = template.replace("127.0.0.1:8000", f"127.0.0.1:{origin.server_port}")
    template = template.replace("/var/log/nginx/zmm-alexa-error.log", (tmp_path / "error.log").as_posix())
    # Avoid test bursts obscuring the method/path/signature checks. Separate tests
    # assert the production template's actual rate/connection directives.
    template = template.replace("rate=1r/s", "rate=100r/s").replace("burst=4", "burst=100")
    config = tmp_path / "nginx.conf"
    config.write_text(f"pid {(tmp_path / 'nginx.pid').as_posix()};\nevents {{}}\nhttp {{\n{template}\n}}\n")
    (tmp_path / "logs").mkdir()
    argv = [shutil.which("nginx"), "-p", tmp_path.as_posix() + "/", "-c", config.as_posix()]
    process = None
    def request(path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(method, path, body=body, headers={"Host": "movies-api.fradkin.net", **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()
    try:
        lint = subprocess.run(argv + ["-t"], capture_output=True, timeout=10)
        assert lint.returncode == 0, lint.stderr.decode(errors="replace")
        process = subprocess.Popen(argv + ["-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.monotonic() + 5
        while True:
            try:
                request("/")
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("Isolated Alexa proxy did not start")
                time.sleep(.05)
        for path in ("/", "/health", "/api/play", "/remote/api/play", "/play/luca", "/%61lexa",
                     "/alexa/", "/x/../alexa", "/alexa?", "/alexa?x=1"):
            assert request(path, "POST", "{}")[0] == 404
        assert request("/alexa")[0] == 405
        assert request("/alexa", "POST", " " * 32769)[0] == 413
        assert request("/alexa", "POST", "{}", {"Content-Type": "application/json"})[0] == 400
        event = alexa_event(type="LaunchRequest")
        raw = json.dumps(event).encode()
        signature = base64.b64encode(signing_keys[1].sign(raw, padding.PKCS1v15(), hashes.SHA256())).decode()
        status, body = request("/alexa", "POST", raw, {"Content-Type": "application/json",
                              "Signature-256": signature, "SignatureCertChainUrl": CERT_URL})
        assert status == 200
        assert "Movie Magic" in json.loads(body)["response"]["outputSpeech"]["text"]
        assert calls == []
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        origin.shutdown()
        thread.join(timeout=5)
        origin.server_close()
