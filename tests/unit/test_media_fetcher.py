"""Unit test del fetcher SSRF-guarded (src/domains/media/fetcher.py).

Nessuna rete reale: gli host sono IP letterali (getaddrinfo offline) e le risposte HTTP
arrivano da httpx.MockTransport.
"""
import httpx
import pytest

from src.domains.media import fetcher
from src.domains.media.fetcher import (
    ContentTooLarge,
    FetchFailed,
    UrlNotAllowed,
    assert_public_url,
    fetch,
)


# ── assert_public_url: difese SSRF ──────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "ftp://example.com/x",          # schema non http/https
    "file:///etc/passwd",           # schema locale
    "http://127.0.0.1/x",           # loopback
    "http://10.0.0.5/x",            # privato
    "http://192.168.1.10/x",        # privato
    "http://172.16.0.1/x",          # privato
    "http://169.254.169.254/latest/meta-data",  # link-local (metadata cloud!)
    "http://[::1]/x",               # loopback ipv6
    "https://[fe80::1]/x",          # link-local ipv6
    "http://0.0.0.0/x",             # unspecified
    "https:///nohost",              # senza host
])
def test_assert_public_url_rejects(url):
    with pytest.raises(UrlNotAllowed):
        assert_public_url(url)


@pytest.mark.parametrize("url", [
    "https://1.1.1.1/blob.png",
    "http://8.8.8.8/x",
])
def test_assert_public_url_allows_public(url):
    assert_public_url(url)  # non solleva


# ── fetch: redirect, size cap, errori ───────────────────────────────────────────

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_fetch_returns_bytes_and_content_type():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "image/png; charset=binary"}, content=b"PNGDATA")

    data, ctype = fetch("https://1.1.1.1/blob.png", client=_client(handler))
    assert data == b"PNGDATA"
    assert ctype == "image/png"          # parametri rimossi, minuscolo


def test_fetch_follows_one_redirect_revalidated():
    def handler(req):
        if req.url.host == "1.1.1.1":
            return httpx.Response(302, headers={"location": "https://8.8.8.8/final.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"OK")

    data, ctype = fetch("https://1.1.1.1/x", client=_client(handler), max_redirects=3)
    assert data == b"OK" and ctype == "image/png"


def test_fetch_redirect_to_private_is_blocked():
    def handler(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})

    with pytest.raises(UrlNotAllowed):
        fetch("https://1.1.1.1/x", client=_client(handler), max_redirects=3)


def test_fetch_too_many_redirects():
    def handler(req):
        return httpx.Response(302, headers={"location": "https://1.1.1.1/loop"})

    with pytest.raises(FetchFailed):
        fetch("https://1.1.1.1/x", client=_client(handler), max_redirects=2)


def test_fetch_size_cap():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=b"x" * 5000)

    with pytest.raises(ContentTooLarge):
        fetch("https://1.1.1.1/big.mp4", client=_client(handler), max_bytes=1000)


def test_fetch_remote_error_is_fetchfailed():
    def handler(req):
        return httpx.Response(503)

    with pytest.raises(FetchFailed):
        fetch("https://1.1.1.1/x", client=_client(handler))


def test_defaults_present():
    assert fetcher.MAX_BYTES > 0 and fetcher.TIMEOUT_S > 0 and fetcher.MAX_REDIRECTS >= 1
