"""URL esterno e propagazione dello schema dal proxy.

Regressione vera, vista in produzione: due proxy in fila (l'nginx di sistema che termina il TLS
e quello del media-manager), il secondo sovrascriveva `X-Forwarded-Proto` con il proprio
`$scheme` = http, e il feed usciva con `<atom:link rel="self">` in http — mentre l'URL
sottomesso a Podcast Index era in https.
"""
import pathlib

import pytest

from src.external_url import external_host, external_scheme, external_url

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Request:
    def __init__(self, headers=None, scheme="http", host="interno:8080"):
        self.headers = headers or {}
        self.scheme = scheme
        self.host = host


def test_forwarded_proto_wins_over_the_last_hop():
    req = _Request({"X-Forwarded-Proto": "https", "Host": "esterno.example"})
    assert external_scheme(req) == "https"
    assert external_url(req, "/v0/feed/x.xml") == "https://esterno.example/v0/feed/x.xml"


def test_without_the_header_the_request_scheme_is_used():
    req = _Request({"Host": "esterno.example"}, scheme="http")
    assert external_scheme(req) == "http"
    assert external_url(req, "/a") == "http://esterno.example/a"


def test_chained_proxies_leave_a_list_and_the_first_value_wins():
    """Con piu' proxy in fila l'header diventa `https, http`: vale l'hop piu' vicino al client."""
    req = _Request({"X-Forwarded-Proto": "https, http", "Host": "esterno.example"})
    assert external_scheme(req) == "https"


def test_forwarded_host_wins_over_host():
    req = _Request({"X-Forwarded-Host": "pubblico.example", "Host": "interno:8080"})
    assert external_host(req) == "pubblico.example"


def test_empty_headers_fall_back_instead_of_producing_an_empty_url():
    req = _Request({"X-Forwarded-Proto": "", "X-Forwarded-Host": " "}, scheme="https",
                   host="fallback.example")
    assert external_url(req, "/a") == "https://fallback.example/a"


# ── il proxy deve propagare, non sovrascrivere ─────────────────────────────────

@pytest.mark.parametrize("path", ["deploy/proxy/gen-nginx-conf.sh", "deploy/proxy/nginx.conf"])
def test_proxy_propagates_the_external_scheme(path):
    """Sia il generatore sia la conf generata: `$scheme` qui rimetterebbe http e il bug torna."""
    text = (ROOT / path).read_text()
    assert "X-Forwarded-Proto $scheme" not in text.replace("\\", "")
    assert "$proto_esterno" in text


def test_generated_conf_declares_the_map_that_defines_it():
    text = (ROOT / "deploy/proxy/nginx.conf").read_text()
    assert "map $http_x_forwarded_proto $proto_esterno" in text
    assert "default $http_x_forwarded_proto;" in text      # c'e' -> propaga
    assert '""      $scheme;' in text                      # non c'e' -> siamo noi il bordo
