"""Scan tracked source plus explicit additions; never open live secret files.

Reports only filename/line/rule, never matching values. This supplements review;
it cannot recognize every possible credential format.
"""
from pathlib import Path
import re
import subprocess
import sys


RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "backend-bearer": re.compile(r"Bearer [A-Za-z0-9_-]{1,64}\.[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"),
    "access-secret": re.compile(r"CF-Access-Client-Secret[\"']?\s*[:=]\s*[\"']?[a-f0-9]{40,}", re.I),
    "test-canary": re.compile(r"ZMM_SECRET_SCAN_CANARY_" + r"[a-f0-9]{32}"),
}


def forbidden_path(path):
    name = path.name.lower()
    return (name == ".env" or name.startswith(".env.") and name != ".env.example"
            or name in {"adbkey", "adbkey.pub"}
            or name.startswith(("api-tokens", "tunnel-credentials")) and name.endswith(".json"))


def scan_text(text):
    return [(index, rule) for index, line in enumerate(text.splitlines(), 1)
            for rule, pattern in RULES.items() if pattern.search(line)]


def main():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    additions = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root).decode().split("\0")
    failures = []
    for name in sorted(set(tracked + additions) - {""}):
        path = root / name
        if forbidden_path(path):
            failures.append((name, 0, "forbidden-secret-file"))
            continue
        if path.suffix.lower() not in {".py", ".js", ".cjs", ".json", ".md", ".html", ".yml", ".yaml", ".sh", ".example", ".service", ".txt"}:
            continue
        if path.is_file():
            # Credential signatures are ASCII; preserve coverage in legacy files
            # that contain non-UTF-8 prose without rewriting those files.
            failures.extend((name, line, rule) for line, rule in scan_text(path.read_text(encoding="utf-8", errors="replace")))
    for name, line, rule in failures:
        print(f"{name}:{line}: {rule}")
    print(f"Secret scan: {len(failures)} finding(s); live secret files were not read.")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
