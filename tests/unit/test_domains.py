"""Test della discovery dei domini (non richiede connexion)."""
from pathlib import Path

OPENAPI_DIR = Path(__file__).resolve().parents[2] / "openapi"


def _discover():
    return sorted(p.parent.name for p in OPENAPI_DIR.glob("*/api.yaml"))


def test_media_domain_is_discovered():
    assert "media" in _discover()
