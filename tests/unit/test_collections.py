"""Guard sul generatore dei bundle (tools/build_collections.py).

Il drift-check (`make collections-check`) verifica solo che i file committati combacino con
l'output del generatore: NON cattura un bug del generatore (il file committato rispecchierebbe
l'output sbagliato). Questi test verificano invece le proprieta' che un bundle condivisibile
deve avere: niente $ref esterni o auto-referenziali, schema di sicurezza risolto.
"""
import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_collections", ROOT / "tools" / "build_collections.py")
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)

_SHARED = yaml.safe_load(bc.SHARED.read_text())
_DOMAINS = bc._discover_domains()


def _all_refs(node):
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            yield node["$ref"]
        for v in node.values():
            yield from _all_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_refs(v)


def _bundles():
    return {d: bc._build_one(d, _SHARED) for d in _DOMAINS}


def test_no_external_refs():
    # gli importer (Bruno/Postman) non risolvono i $ref verso file esterni
    for domain, spec in _bundles().items():
        externals = [r for r in _all_refs(spec) if "shared/components.yaml" in r]
        assert externals == [], f"{domain}: $ref esterni residui {externals}"


def test_no_selfreferential_components():
    # un componente definito-come-$ref non deve restare un puntatore a se stesso
    for domain, spec in _bundles().items():
        for category, members in spec.get("components", {}).items():
            for name, body in members.items():
                ref = body.get("$ref") if isinstance(body, dict) else None
                assert ref != f"#/components/{category}/{name}", f"{domain}: {category}/{name} auto-referenziale"
                assert ref is None, f"{domain}: {category}/{name} e' ancora un $ref ({ref}) invece del contenuto"


def test_apikey_scheme_resolved():
    # il nome esatto dell'header deve essere desumibile dalla spec
    for domain, spec in _bundles().items():
        scheme = spec["components"]["securitySchemes"]["ApiKeyAuth"]
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-API-Key"
        assert "x-apikeyInfoFunc" not in scheme  # wiring server-side non esposto ai consumer


def test_servers_absolute_and_no_prod_host():
    for domain, spec in _bundles().items():
        urls = [s["url"] for s in spec["servers"]]
        assert urls, f"{domain}: nessun server"
        assert all(u.startswith("http://") or u.startswith("https://") for u in urls), f"{domain}: server non assoluti {urls}"
        assert not any("prod" in u.lower() for u in urls), f"{domain}: host di produzione nel bundle {urls}"
