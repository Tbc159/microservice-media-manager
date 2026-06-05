"""Composition root del dominio source: legge l'ambiente e assembla service+repo+storage.

E' l'unico punto che conosce le implementazioni concrete; controller e service restano
ignari del backend. Selezione via env var:

  SOURCE_DB_PATH set   -> SqliteSourceMediaRepository, altrimenti Mock (dev rapido/test).
  STORAGE_BACKEND      -> local (default) | minio | s3.

Gli import dei backend concreti sono lazy: dev/test con backend 'local' non caricano
l'SDK minio.
"""
import os

from .repositories.mock_repository import MockSourceMediaRepository
from .repositories.sqlite_repository import SqliteSourceMediaRepository
from .services.source_service import SourceService
from .storage.local_backend import LocalStorageBackend


def _build_repository():
    db_path = os.environ.get("SOURCE_DB_PATH")
    if db_path:
        return SqliteSourceMediaRepository(db_path)
    return MockSourceMediaRepository()


def _build_storage():
    backend = os.environ.get("STORAGE_BACKEND", "local").lower()
    if backend == "local":
        return LocalStorageBackend(media_dir=os.environ.get("SOURCE_MEDIA_DIR", "/data/media"))
    if backend in ("minio", "s3"):
        from .storage.minio_backend import MinioStorageBackend

        return MinioStorageBackend(
            endpoint=os.environ["STORAGE_ENDPOINT"],
            access_key=os.environ["STORAGE_ACCESS_KEY"],
            secret_key=os.environ["STORAGE_SECRET_KEY"],
            bucket=os.environ.get("STORAGE_BUCKET", "media-source"),
            secure=os.environ.get("STORAGE_SECURE", "false").lower() == "true",
        )
    raise ValueError(f"STORAGE_BACKEND non valido: {backend!r} (atteso: local|minio|s3)")


def build_components():
    """Restituisce (repository, storage) assemblati dall'ambiente.

    Esposto per riuso fuori dal percorso HTTP (es. seeding/manutenzione) senza
    duplicare la logica di selezione del backend.
    """
    return _build_repository(), _build_storage()


def build_source_service() -> SourceService:
    repo, storage = build_components()
    return SourceService(repo=repo, storage=storage)
