"""Backend storage S3-compatible (coll/prod).

Stessa classe per MinIO self-hosted e per S3/R2: cambia solo l'endpoint/secure passati
dal factory. L'SDK 'minio' e' importato qui: il modulo viene caricato solo quando
STORAGE_BACKEND != local (vedi factory), cosi' dev/test non richiedono la dipendenza.

Il playback dal browser sfrutta gli URL pre-firmati: supportano nativamente le Range
request (seek/resume dell'audio) e scaricano i byte direttamente dallo storage, senza
passare dall'API.
"""
import io
from datetime import timedelta
from typing import Optional

from minio import Minio
from minio.error import S3Error


class MinioStorageBackend:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        self._bucket = bucket

    def get_stream_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        return self._client.presigned_get_object(
            self._bucket, object_key, expires=timedelta(seconds=ttl_seconds)
        )

    def get_upload_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        return self._client.presigned_put_object(
            self._bucket, object_key, expires=timedelta(seconds=ttl_seconds)
        )

    def put_object(self, object_key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def object_exists(self, object_key: str) -> bool:
        try:
            self._client.stat_object(self._bucket, object_key)
            return True
        except S3Error:
            return False
