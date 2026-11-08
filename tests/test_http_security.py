"""Real loopback HTTP against the app; all catalog/device operations are fake."""
import http.client
import json
import re
from threading import Thread

from werkzeug.serving import make_server

from tests.test_api import client
from tests.test_api_v2 import api_client
from tests.test_auth import remote
from tests.test_dispatcher import terminal


def test_loopback_session_machine_and_legacy_boundaries(remote):
    _, app, calls, bearer = remote
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, method="GET", body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers={"Host": "localhost", **(headers or {})})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            conn.close()
    try:
        assert request("/remote/api/movies")[0] == 401
        assert request("/remote/api/movies", headers={"CF-Connecting-IP": "127.0.0.1"})[0] == 401
        assert request("/remote/api/movies", headers=bearer)[0] == 200
        status, headers, html = request("/")
        assert status == 200 and headers["Cache-Control"] == "private, no-store"
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)[1]
        command_headers = {"Cookie": cookie, "Content-Type": "application/json", "Idempotency-Key": "http-test-one"}
        body = json.dumps({"movie_key": "luca"})
        assert request("/api/play", "POST", body, command_headers)[0] == 403
        accepted = request("/api/play", "POST", body, {**command_headers, "X-CSRF-Token": csrf})
        assert accepted[0] == 202
        request_id = json.loads(accepted[2])["request_id"]
        terminal(app.extensions["playback_service"], request_id)
        assert request("/remote/api/status?request_id=" + request_id, headers=bearer)[0] == 404
        assert request("/play/not-in-catalog")[0] == 200
        assert calls == ["luca-id"]
        assert app.extensions["test_launched"] == ["not-in-catalog"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
