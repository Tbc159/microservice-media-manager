"""Backend storage su file system locale del container (dev/staging).

In dev gestiamo solo l'upload locale: i byte stanno sul FS montato a `media_dir`.
Non esiste un URL pre-firmato (niente MinIO/S3), quindi get_stream_url/get_upload_url/
get_download_url restituiscono None: i byte si servono dall'endpoint /content (streaming
dal FS), mentre in coll/prod il backend MinIO usa i redirect agli URL pre-firmati.
"""
from pathlib import Path
from typing import Optional


class LocalStorageBackend:
    def __init__(self, media_dir: str = "/data/media") -> None:
        self._media_dir = Path(media_dir)

    def _path_for(self, object_key: str) -> Path:
        return self._media_dir / object_key

    def get_stream_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        return None

    def get_upload_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        return None

    def get_download_url(
        self, object_key: str, filename: str, ttl_seconds: int = 3600
    ) -> Optional[str]:
        return None

    def local_path(self, object_key: str) -> Optional[str]:
        p = self._path_for(object_key)
        return str(p) if p.is_file() else None

    def put_object(self, object_key: str, data: bytes, content_type: str) -> None:
        dest = self._path_for(object_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def object_exists(self, object_key: str) -> bool:
        return self._path_for(object_key).is_file()
