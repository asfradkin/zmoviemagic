"""Opt-in native Nginx lint and loopback HTTP checks; no edge/device access."""
import http.client
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
import time

import pytest
from werkzeug.serving import make_server

from tests.test_api import client
from tests.test_api_v2 import api_client
from tests.test_auth import remote


@pytest.mark.skipif(shutil.which("nginx") is None, reason="Nginx is not installed; native proxy verification remains pending")
def test_native_proxy_lint_and_isolated_http(remote, tmp_path):
    _, app, calls, headers = remote
    origin = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    template = (Path(__file__).resolve().parents[1] / "ops/nginx/zmoviemagic-remote.conf.example").read_text()
    template = template.replace("127.0.0.1:8081", f"127.0.0.1:{port}")
    template = template.replace("127.0.0.1:8000", f"127.0.0.1:{origin.server_port}")
    template = template.replace("/var/log/nginx/zmm-remote-error.log", (tmp_path / "error.log").as_posix())
    config = tmp_path / "nginx.conf"
    config.write_text(f"pid {(tmp_path / 'nginx.pid').as_posix()};\nevents {{}}\nhttp {{\n{template}\n}}\n")
    (tmp_path / "logs").mkdir()
    app.extensions["auth_service"].hosts |= {"zmm-origin.internal"}
    executable = shutil.which("nginx")
    argv = [executable, "-p", tmp_path.as_posix() + "/", "-c", config.as_posix()]
    process = None
    def request(path, method="GET", body=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request(method, path, body=body, headers={"Host": "movies-api.example.net", **(extra or {})})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()
    try:
        lint = subprocess.run(argv + ["-t"], capture_output=True, timeout=10)
        assert lint.returncode == 0, lint.stderr.decode(errors="replace")
        process = subprocess.Popen(argv + ["-g", "daemon off;"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.monotonic() + 5
        while True:
            try:
                request("/")
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("Isolated proxy did not start")
                time.sleep(0.05)
        for path in ("/", "/health", "/play/luca-id", "/static/tablet.js", "/remote/api/movies",
                     "/api%2fmovies", "/api%252fmovies", "/api//movies", "/api/./movies",
                     "/x/../api/movies", "/api/movies?x=1", "/api/control", "/api/resolve"):
            assert request(path, extra=headers)[0] == 404
        assert request("/api/movies")[0] == 401
        assert request("/api/movies", extra=headers)[0] == 200
        assert request("/api/play", extra=headers)[0] == 405
        assert request("/api/play", "POST", " " * 4097, headers)[0] == 413
        assert calls == []
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=5)
        origin.shutdown()
        thread.join(timeout=5)
        origin.server_close()
