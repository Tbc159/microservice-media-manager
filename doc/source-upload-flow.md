# Dominio `source` — flusso di upload (API → FS → DB)

Come funziona **tecnicamente** il caricamento di un media nel dominio interno `source`:
dalla chiamata API alla scrittura dei byte sullo storage e dei metadati sul database.
La fonte di verità resta il codice in `src/domains/source/`; questa pagina lo riassume.

## Chiarimenti sui nomi (per evitare fraintendimenti)

- Il dominio interno si chiama **`source`** — non "store".
- I metadati stanno su **SQLite** (`source_media`) — non MySQL.
- Lo **storage dei byte** dipende dall'ambiente:
  - **dev/staging** → file system del container (`LocalStorageBackend`);
  - **coll/prod** → MinIO/S3 (`MinioStorageBackend`).
- `media` è il **BFF pubblico**; `source` è **interno** (marker `openapi/source/.internal`),
  raggiungibile solo sulla rete docker `mediamgr`. L'upload "pubblico" passa da `media`,
  che delega a `source`.

## Endpoint

`POST /v0/source/media` — `multipart/form-data`: `file` (binario) + `title` + `media_type`
(`audio/m4a|audio/mp3|video/mp4`) + `duration_s?`. Contratto: `openapi/source/api.yaml`.

## Flusso end-to-end

```
POST /v0/source/media (multipart)
        │
        ▼
upload_source_media(body, file)            controllers/source_controller.py
  - filename mancante? → 400
  - data = file.read()
        │
        ▼
SourceService.create(...)                  services/source_service.py
  object_key = f"{media_type}/{filename}"  # es. audio/m4a/puntata.m4a
        │
        ├─ 1) METADATI  repo.insert(...)    repositories/sqlite_repository.py
        │      INSERT INTO source_media (... size_bytes=len(data) ...)
        │      object_key UNIQUE → IntegrityError → DuplicateObjectKeyError → 409
        │
        └─ 2) BYTE      storage.put_object() storage/local_backend.py
               mkdir -p + write_bytes  →  /data/media/<object_key>
        │
        ▼
return DTO (201)  # _to_dto nasconde object_key, espone content_url/download_url
```

### Passi in dettaglio

1. **Routing**: connexion risolve l'`operationId` verso `upload_source_media(body, file)`
   (`source_controller.py`). Controller *thin*: non conosce DB né storage. Filename assente → **400**.
2. **Service**: `SourceService.create()` (`source_service.py`) calcola
   `object_key = "<media_type>/<filename>"` (namespacing per MIME type) ed esegue **due passi in
   ordine deliberato**: prima i metadati, poi i byte.
3. **Metadati (SQLite)**: `SqliteSourceMediaRepository.insert()` fa `INSERT INTO source_media`
   con `size_bytes = len(data)`. La colonna `object_key TEXT NOT NULL UNIQUE` (`schema.py`)
   garantisce l'idempotenza: un duplicato solleva `sqlite3.IntegrityError`, tradotto in
   `DuplicateObjectKeyError` e quindi in **409** dal controller. La connessione è aperta
   **per chiamata** (WAL mode): connexion 3.x esegue le view sync in un threadpool e SQLite non
   condivide connessioni tra thread.
4. **Byte (storage)**: `LocalStorageBackend.put_object()` crea la cartella e scrive
   `dest.write_bytes(data)` in `media_dir / object_key`. In coll/prod la stessa interfaccia è
   implementata da `MinioStorageBackend` (oggetto su bucket).
5. **Risposta**: il record (`repo.get(new_id)`) viene mappato in DTO da `_to_dto`, che **non espone**
   `object_key` e aggiunge `content_url` / `download_url` verso la sotto-risorsa `/content`. **201**.

## Dove finiscono fisicamente i dati (container `source`, dev)

Da `docker-compose.source.yml` + `config/source/staging.env`:

| Cosa | Path nel container | Env |
|------|--------------------|-----|
| Volume unico (host → container) | `/data` | `SOURCE_DATA_PATH` (host) |
| Metadati (DB SQLite) | `/data/source.db`, tabella `source_media` | `SOURCE_DB_PATH` |
| Byte dei media | `/data/media/<media_type>/<filename>` | `SOURCE_MEDIA_DIR` |

Il backend è scelto dal **composition root** `factory.py`:
`SOURCE_DB_PATH` valorizzato → SQLite (altrimenti `MockRepository`);
`STORAGE_BACKEND=local|minio|s3` (default `local`).

## Trade-off da conoscere: niente transazione DB↔FS

L'ordine **metadati prima, byte dopo** è voluto: rileva i duplicati senza scrivere byte orfani.
Per contro, se `put_object` fallisce **dopo** l'insert, resta una **riga di metadati senza byte**
(non c'è rollback tra DB e FS). Il caso è gestito a valle: l'endpoint `/content` ritorna **404**
("record presente ma byte assenti", `source_service.py`) invece di servire un file rotto.
È il punto debole del flusso da tenere presente per gli edge case.

## Riferimenti al codice

- `src/domains/source/controllers/source_controller.py` — `upload_source_media`
- `src/domains/source/services/source_service.py` — `SourceService.create`, `_to_dto`, `content`
- `src/domains/source/repositories/sqlite_repository.py` — `insert`, WAL, per-call connection
- `src/domains/source/repositories/schema.py` — tabella `source_media` (UNIQUE `object_key`)
- `src/domains/source/storage/local_backend.py` — `put_object`, `local_path`
- `src/domains/source/storage/base.py` — `StorageBackend` (Protocol)
- `src/domains/source/factory.py` — selezione repo/storage da env
- `openapi/source/api.yaml` — contratto `POST /v0/source/media`
