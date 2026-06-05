"""Seed idempotente del dominio source — verifica end-to-end di DB + storage.

Inserisce alcuni record demo e carica un placeholder sullo storage, cosi' che gli
stream_url pre-firmati risolvano a un oggetto reale. Rieseguibile senza effetti:
salta se esistono gia' record per il media_type.

Uso (dentro il container, dopo il deploy — es. in collaudo):
    docker compose -f docker-compose.source.yml exec source python -m src.domains.source.seed
oppure: make seed-source
"""
import sys

from src.domains.source.factory import build_components

_DEMO = [
    {
        "title": "Demo uno",
        "filename": "demo-uno.m4a",
        "media_type": "audio/m4a",
        "object_key": "audio/m4a/demo-uno.m4a",
        "duration_s": 12,
    },
    {
        "title": "Demo due",
        "filename": "demo-due.m4a",
        "media_type": "audio/m4a",
        "object_key": "audio/m4a/demo-due.m4a",
        "duration_s": 34,
    },
]


def main() -> int:
    repo, storage = build_components()
    _, existing = repo.find("audio/m4a", None, 1, 1)
    if existing:
        print(f"Seed saltato: gia' presenti record audio/m4a ({existing}).")
        return 0

    placeholder = b"\x00" * 1024  # contenuto fittizio: serve solo a far risolvere l'URL
    for d in _DEMO:
        storage.put_object(d["object_key"], placeholder, d["media_type"])
        rid = repo.insert(size_bytes=len(placeholder), **d)
        print(f"inserito id={rid} -> {d['object_key']}")
    print("Seed completato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
