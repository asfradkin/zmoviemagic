"""Amazon's signature verifier, with bounded certificate I/O and cache.

Only this module knows about certificates. The conversation stays in skill.py.
"""
from collections import OrderedDict
import http.client
import re
import time
from urllib.parse import urlsplit

from ask_sdk_webservice_support.verifier import RequestVerifier, VerificationException


class AmazonVerifier(RequestVerifier):
    """Keep SDK signature/chain/SAN checks; replace its unbounded URL fetch/cache."""

    def __init__(self):
        super().__init__()
        self._cert_cache = OrderedDict()

    def _validate_certificate_url(self, url):
        # Strict canonical subset also avoids the SDK's OS-dependent path handling.
        parsed = urlsplit(url)
        if (len(url) > 512 or parsed.scheme != "https" or parsed.hostname != "s3.amazonaws.com"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"/echo\.api/[A-Za-z0-9_-]+\.pem", parsed.path)):
            raise VerificationException("Invalid certificate URL")

    def _load_cert_chain(self, url):
        now = time.monotonic()
        self._cert_cache = OrderedDict((key, entry) for key, entry in self._cert_cache.items()
                                       if now - entry[0] < 3600)
        if url in self._cert_cache:
            return self._cert_cache[url][1]
        certificate = self.fetch_certificate(url)
        # Validate before caching; invalid responses cannot evict the valid chain.
        self._validate_cert_chain(certificate)
        if len(self._cert_cache) >= 4:
            self._cert_cache.popitem(last=False)
        self._cert_cache[url] = (now, certificate)
        return certificate

    @staticmethod
    def fetch_certificate(url):
        """Fixed Amazon host, TLS verification, no redirects, 64 KiB, three seconds.

        The caller also bounds wall time in a single verification worker: slow DNS
        cannot tie up Flask threads or create an ever-growing work queue.
        """
        parsed = urlsplit(url)
        connection = http.client.HTTPSConnection("s3.amazonaws.com", timeout=1)
        deadline = time.monotonic() + 3
        try:
            connection.request("GET", parsed.path, headers={"Accept": "application/x-pem-file"})
            response = connection.getresponse()
            if response.status != 200:
                raise VerificationException("Certificate download failed")
            chunks, length = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Certificate deadline")
                if connection.sock:
                    connection.sock.settimeout(min(1, remaining))
                chunk = response.read1(min(4096, 65537 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > 65536:
                    raise VerificationException("Certificate response too large")
            certificate = b"".join(chunks)
            if not 1 <= certificate.count(b"-----BEGIN CERTIFICATE-----") <= 8:
                raise VerificationException("Invalid certificate chain")
            return certificate
        finally:
            connection.close()

    def verify_body(self, headers, raw_body):
        # No model deserialization is needed for the SDK's signature check.
        # The chain, signing-certificate dates/SAN and SHA256 signature are all
        # checked by the SDK, including on cache hits. Never cache an auth result.
        self.verify(headers, raw_body, None)
