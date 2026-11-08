from pathlib import Path

from tools.scan_secrets import forbidden_path, scan_text


def test_scanner_detects_canary_and_reports_no_values():
    canary = "ZMM_SECRET_SCAN_CANARY_" + "1" * 32
    assert scan_text("innocent\n" + canary) == [(2, "test-canary")]
    assert scan_text("Authorization: Bearer token-id." + "A" * 43) == [(1, "backend-bearer")]
    assert scan_text("Authorization: Bearer <backend-token>") == []


def test_live_credentials_are_flagged_by_filename_without_reading():
    for name in (".env", ".env.production", "adbkey", "adbkey.pub", "api-tokens.json", "tunnel-credentials-example.json"):
        assert forbidden_path(Path(name))
    assert not forbidden_path(Path(".env.example"))
