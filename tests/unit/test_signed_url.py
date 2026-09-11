"""Token di lettura firmato: legame col media, scadenza, fail-closed.

Sono le tre proprieta' che tengono in piedi la scelta di mettere un permesso nella query
string: se una salta, l'URL firmato diventa un modo per rendere pubblici i byte.
"""
import pytest

from src import signed_url


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setenv("MEDIA_URL_SIGNING_KEY", "chiave-di-test")
    monkeypatch.delenv("MEDIA_URL_TTL_S", raising=False)


def _token(url: str) -> str:
    return url.split("token=", 1)[1]


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("MEDIA_URL_SIGNING_KEY", raising=False)
    assert signed_url.enabled() is False
    assert signed_url.mint(1) is None
    # fail-closed: senza chiave nessun token e' valido, nemmeno uno formalmente corretto
    assert signed_url.verify("v1.99999999999.abc", 1) is False
    assert signed_url.decorate({"id": 1}, 1) == {"id": 1}


def test_mint_and_verify(key):
    url, exp = signed_url.mint(7)
    assert url.startswith("/v0/media/7/content?token=v1.")
    assert signed_url.verify(_token(url), 7) is True
    assert signed_url.verify(_token(url), 7, now=exp - 1) is True


def test_token_is_bound_to_its_media(key):
    """L'id e' dentro la firma: spostare il token su un altro media la invalida."""
    url, _ = signed_url.mint(7)
    assert signed_url.verify(_token(url), 8) is False
    assert signed_url.verify(_token(url), 70) is False


def test_token_expires(key):
    url, exp = signed_url.mint(7)
    assert signed_url.verify(_token(url), 7, now=exp) is True
    assert signed_url.verify(_token(url), 7, now=exp + 1) is False


def test_token_is_not_forgeable(key, monkeypatch):
    url, exp = signed_url.mint(7)
    token = _token(url)
    assert signed_url.verify(token.replace("v1.", "v2."), 7) is False   # versione diversa
    assert signed_url.verify(f"v1.{exp + 3600}.{token.split('.')[2]}", 7) is False  # exp manomessa
    assert signed_url.verify("v1.abc.def", 7) is False                  # exp non numerica
    assert signed_url.verify("nonsense", 7) is False
    assert signed_url.verify(None, 7) is False
    # firmato con un'altra chiave -> non vale
    monkeypatch.setenv("MEDIA_URL_SIGNING_KEY", "altra-chiave")
    assert signed_url.verify(token, 7) is False


def test_ttl_is_configurable_and_clamped(key, monkeypatch):
    assert signed_url.ttl_s() == 900
    monkeypatch.setenv("MEDIA_URL_TTL_S", "60")
    assert signed_url.ttl_s() == 60
    monkeypatch.setenv("MEDIA_URL_TTL_S", "1")          # sotto il minimo
    assert signed_url.ttl_s() == 30
    monkeypatch.setenv("MEDIA_URL_TTL_S", "999999")     # sopra il massimo
    assert signed_url.ttl_s() == 86400
    monkeypatch.setenv("MEDIA_URL_TTL_S", "x")          # non numerico -> default
    assert signed_url.ttl_s() == 900


def test_decorate_adds_both_fields(key):
    item = signed_url.decorate({"id": 3, "content_url": "/v0/media/3/content"}, 3)
    assert item["signed_url"].startswith("/v0/media/3/content?token=")
    assert item["signed_url_expires_at_s"] > 0
