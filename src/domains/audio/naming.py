"""Naming human-readable per job e media prodotti.

Gli id devono poter essere usati **a mano** (polling di un job, riferimento a un output),
quindi non usiamo uuid opachi: `<op>-<data>-<ora>-<token4>` per i job e
`<stem-sorgente>-<op>-<token4>.<ext>` per i file. Il token breve garantisce unicita' (piu'
tentativi sulla stessa sorgente producono media distinti) restando leggibile.
"""
import datetime
import re
import uuid

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def short_token() -> str:
    return uuid.uuid4().hex[:4]


def new_job_id(op: str, *, token: str | None = None, now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    return f"{op}-{now.strftime('%Y%m%d-%H%M%S')}-{token or short_token()}"


def slug(value: str) -> str:
    """Slug human-readable: minuscole, non-alfanumerici -> '-', senza estensione."""
    stem = value.rsplit(".", 1)[0] if "." in value else value
    s = _SLUG_RE.sub("-", stem.lower()).strip("-")
    return s or "audio"


def output_filename(source_filename: str, op: str, ext: str, token: str) -> str:
    return f"{slug(source_filename)}-{op}-{token}.{ext}"
