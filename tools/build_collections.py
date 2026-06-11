#!/usr/bin/env python3
"""Genera collection API condivisibili (bundle OpenAPI self-contained) dai contratti.

Per ogni dominio `openapi/<dom>/api.yaml` produce `api-collections/<dom>.openapi.yaml`:
  * i `$ref` esterni verso `openapi/shared/components.yaml` vengono **inlineati**
    (gli importer come Bruno/Postman non risolvono i $ref relativi a file esterni);
  * il `servers:` relativo (`/v0`) viene sostituito con server **assoluti** per gli
    ambienti dev e coll (nessun host di produzione), cosi' gli endpoint risultano
    corretti subito dopo l'import in qualsiasi tool.

Domini **interni** (`openapi/<dom>/.internal`): il bundle viene comunque generato ma
marcato come interno (server = rete docker / port-forward, niente host pubblico).

Uso:
    python3 tools/build_collections.py            # (ri)genera i bundle
    python3 tools/build_collections.py --check    # verifica drift (CI): exit!=0 se disallineati

I bundle sono **rigenerati**, non editati a mano: la fonte di verita' resta openapi/<dom>/api.yaml.
"""
from __future__ import annotations

import argparse
import copy
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPENAPI_DIR = ROOT / "openapi"
SHARED = OPENAPI_DIR / "shared" / "components.yaml"
OUT_DIR = ROOT / "api-collections"

# Marker che indica un riferimento al file condiviso (qualunque sia il path relativo usato).
SHARED_REF_MARKER = "shared/components.yaml#/"

# --- Ambienti -----------------------------------------------------------------
# Solo dev e coll: nessun host di produzione finisce mai nel repo.
PUBLIC_SERVERS = [
    {
        "url": "http://mediamanager-dev.duckdns.org/v0",
        "description": "dev (staging) - reverse-proxy esterno duckdns. Usa http: l'https ha cert self-signed.",
    },
    {
        "url": "https://{coll_host}/v0",
        "description": "coll (collaudo) - imposta coll_host (host pubblico dell'ambiente di collaudo).",
        "variables": {
            "coll_host": {
                "default": "REPLACE_WITH_COLL_HOST",
                "description": "Host pubblico dell'ambiente collaudo (vive nei secret, non versionato).",
            }
        },
    },
]

INTERNAL_SERVERS = [
    {
        "url": "http://{service}:8080/v0",
        "description": "INTERNO - raggiungibile SOLO sulla rete docker 'mediamgr' (service-to-service). Non instradato dal proxy pubblico.",
        "variables": {
            "service": {
                "default": "source",
                "description": "Nome del service docker del dominio interno.",
            }
        },
    },
    {
        "url": "http://{local_forward}/v0",
        "description": "INTERNO via port-forward locale (docker compose port / ssh tunnel) per test diretti.",
        "variables": {
            "local_forward": {
                "default": "localhost:8081",
                "description": "host:porta di un forward verso il container del dominio interno.",
            }
        },
    },
]

INTERNAL_NOTE = (
    "\n\n> **Dominio INTERNO**: non esposto dal reverse-proxy pubblico. Raggiungibile solo "
    "sulla rete docker `mediamgr` (tramite il BFF) o via port-forward locale. I server qui "
    "sotto riflettono questo: non esiste un host pubblico."
)


def _discover_domains() -> list[str]:
    return sorted(p.parent.name for p in OPENAPI_DIR.glob("*/api.yaml"))


def _is_internal(domain: str) -> bool:
    return (OPENAPI_DIR / domain / ".internal").exists()


def _split_shared_ref(ref: str) -> str | None:
    """Da un $ref ritorna il puntatore JSON locale se punta al file condiviso, altrimenti None.

    Es: '../shared/components.yaml#/components/schemas/Health' -> '#/components/schemas/Health'.
    """
    idx = ref.find(SHARED_REF_MARKER)
    if idx == -1:
        return None
    # tutto cio' che segue il '#'
    return "#" + ref.split("#", 1)[1]


def _resolve_pointer(doc: dict, pointer: str):
    """Risolve un JSON pointer '#/a/b/c' dentro doc."""
    node = doc
    for part in pointer.lstrip("#/").split("/"):
        node = node[part]
    return node


def _inline_shared(spec: dict, shared: dict) -> None:
    """Inlinea ricorsivamente i $ref verso il file condiviso dentro spec['components']."""
    spec.setdefault("components", {})
    pending: list[str] = []  # pointer locali ('#/components/...') da garantire presenti

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                local = _split_shared_ref(ref)
                if local is not None:
                    node["$ref"] = local
                    pending.append(local)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)

    # Copia i componenti referenziati (e quelli che essi stessi referenziano) dentro lo spec.
    copied: set[str] = set()
    while pending:
        pointer = pending.pop()
        if pointer in copied:
            continue
        copied.add(pointer)
        # pointer = '#/components/<categoria>/<nome>'
        parts = pointer.lstrip("#/").split("/")
        category, name = parts[1], parts[2]
        component = copy.deepcopy(_resolve_pointer(shared, pointer))
        # Sovrascrive: se il componente era *definito* come $ref al file condiviso
        # (es. securitySchemes.ApiKeyAuth), il placeholder riscritto sarebbe diventato
        # auto-referenziale. Qui lo rimpiazziamo col contenuto reale.
        spec["components"].setdefault(category, {})[name] = component
        walk(component)  # eventuali $ref annidati nel componente copiato


def _build_one(domain: str, shared: dict) -> dict:
    spec = yaml.safe_load((OPENAPI_DIR / domain / "api.yaml").read_text())
    _inline_shared(spec, shared)

    # Estensione di wiring server-side (connexion): irrilevante e fuorviante per i consumer.
    for scheme in spec.get("components", {}).get("securitySchemes", {}).values():
        if isinstance(scheme, dict):
            scheme.pop("x-apikeyInfoFunc", None)

    internal = _is_internal(domain)
    spec["servers"] = copy.deepcopy(INTERNAL_SERVERS if internal else PUBLIC_SERVERS)
    if internal:
        info = spec.setdefault("info", {})
        info["description"] = (info.get("description", "").rstrip() + INTERNAL_NOTE).strip()
    return spec


def _dump(spec: dict) -> str:
    header = (
        "# GENERATO da tools/build_collections.py - NON editare a mano.\n"
        "# Fonte di verita': openapi/<dominio>/api.yaml. Rigenera con `make collections`.\n"
    )
    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100)
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verifica drift senza riscrivere")
    args = parser.parse_args()

    shared = yaml.safe_load(SHARED.read_text())
    OUT_DIR.mkdir(exist_ok=True)

    domains = _discover_domains()
    drift = False
    for domain in domains:
        spec = _build_one(domain, shared)
        out = _dump(spec)
        target = OUT_DIR / f"{domain}.openapi.yaml"
        if args.check:
            current = target.read_text() if target.exists() else ""
            if current != out:
                print(f"DRIFT: {target.relative_to(ROOT)} non allineato alla spec")
                drift = True
            else:
                print(f"ok: {target.relative_to(ROOT)}")
        else:
            target.write_text(out)
            tag = "interno" if _is_internal(domain) else "pubblico"
            print(f"scritto {target.relative_to(ROOT)} ({tag})")

    if args.check and drift:
        print("\nDisallineamento: esegui `make collections` e committa i bundle.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
