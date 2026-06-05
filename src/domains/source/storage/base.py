from typing import Optional, Protocol


class StorageBackend(Protocol):
    """Astrazione sullo storage dei byte dei media.

    Disaccoppia il dominio dal backend concreto:
      - LocalStorageBackend  -> FS del container (dev/staging)
      - MinioStorageBackend  -> MinIO self-hosted (coll/prod) e, stessa classe, S3/R2.

    Il playback dal browser usa get_stream_url() (URL pre-firmato, scade): l'API non e'
    mai nel path dei byte. Il futuro upload usera' get_upload_url() (PUT diretto dal browser).
    """

    def get_stream_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        """URL pre-firmato per il GET/streaming. None se il backend non lo supporta (local)."""
        ...

    def get_upload_url(self, object_key: str, ttl_seconds: int = 3600) -> Optional[str]:
        """URL pre-firmato per il PUT (upload diretto). None se non supportato (local)."""
        ...

    def put_object(self, object_key: str, data: bytes, content_type: str) -> None:
        """Scrive i byte lato server (seeding, upload locale in dev)."""
        ...

    def object_exists(self, object_key: str) -> bool:
        """True se l'oggetto esiste. Usato dal futuro flusso POST /confirm."""
        ...
