# Domini, API e implementazioni

Documentazione funzionale degli endpoint, contratti e architettura per dominio. Lo stato runtime
attuale è descritto in [changelog.md](changelog.md).

Convenzioni comuni:
- **base path**: `/v0` (applicato da `src/app.py`).
- **auth**: header `X-API-Key` sugli endpoint protetti (vedi [development.md](development.md#sicurezza-api-key)).
- **health**: ogni dominio espone `GET /v0/<dom>/health` → `{"status":"ok"}` (no auth).

---

## Dominio `media`

Gestione dei file media auto-scaricati. Contratto: `openapi/media/api.yaml`.

### `GET /v0/media`
Lista di tutti i file media. Protetto (`X-API-Key`).

Risposta `200`: array di `MediaItem`.

| Campo | Tipo | Note |
|-------|------|------|
| `id` | int | id univoco |
| `name` | string | nome file (es. `data_NomeFile.m4a`) |
| `creation_date_s` | int | timestamp Unix (s) |
| `download_link` | string(uri) | link di download |
| `status` | enum | `draft` \| `processing` \| `published` |
| `pubblicazione` | object\|null | `titolo`, `description`, `cover_image`, `publishing_date_s` (tutti nullable) |

**Implementazione attuale:** risposta **statica** da `MediaService.list_all()` (3 item di esempio),
conforme allo schema (`validate_responses=True`). Sostituibile con persistenza reale senza toccare
controller né contratto.

---

## Dominio `source`

Bridge verso file system e database dei media sorgente; pensato per essere interrogato da un
FrontEnd (media management e **play da browser** / streaming audio). Contratto:
`openapi/source/api.yaml`.

### `GET /v0/source/media`
Recupera media sorgente filtrati. Protetto (`X-API-Key`). Restituisce **sempre** un envelope
paginato (anche vuoto: non è un errore).

Query parameter:

| Param | Obblig. | Tipo | Default | Note |
|-------|---------|------|---------|------|
| `type` | sì | enum | — | `audio/m4a` \| `audio/mp3` \| `video/mp4` |
| `title` | no | string | — | match **esatto**; omesso → tutti i record del tipo |
| `page` | no | int ≥1 | 1 | pagina (1-based) |
| `page_size` | no | int 1..100 | 20 | risultati per pagina |

Risposta `200`: `SourceMediaPagedResponse` = `{ items: SourceMediaItem[], pagination: PaginationMeta }`.

`SourceMediaItem`:

| Campo | Tipo | Note |
|-------|------|------|
| `id` | int | id record DB |
| `title` | string | titolo |
| `filename` | string | nome file originale |
| `media_type` | string | MIME type |
| `size_bytes` | int\|null | dimensione |
| `duration_s` | int\|null | durata media (s) |
| `created_at_s` | int | timestamp creazione |
| `status` | enum | `ready` \| `processing` \| `error` |
| `stream_url` | string(uri)\|null | URL pre-firmato per streaming diretto (vedi sotto); `null` con storage locale |
| `metadata` | object\|null | campi estensibili |

> Scelta REST: filtri in **query string** (non body), `GET` idempotente e cacheable. Il MIME type
> è un filtro di dati → query param `type`, non header `Content-Type` (riservato al body). La
> risposta è sempre un envelope (mai schema biforcato all/single).

### `POST /v0/source/media`
Carica un nuovo media. Protetto (`X-API-Key`). **Upload server-side multipart**: l'API riceve il
file, ne salva i byte nello storage e inserisce i metadati nel DB; risponde `201` col record creato.

Request `multipart/form-data`:

| Campo | Obblig. | Tipo | Note |
|-------|---------|------|------|
| `file` | sì | binary | contenuto del media (il nome file diventa parte dell'`object_key`) |
| `title` | sì | string | titolo |
| `media_type` | sì | enum | `audio/m4a` \| `audio/mp3` \| `video/mp4` |
| `duration_s` | no | integer | durata in secondi |

Risposte: `201` → `SourceMediaItem` (con `stream_url`, `null` in dev locale); `400` campi mancanti /
`media_type` fuori enum; `409` media già presente (stesso `media_type`/`filename` → `object_key`
duplicato); `401` senza chiave.

> connexion passa i campi non-file in `body` (dict) e il file come `FileStorage`
> (`.filename`, `.read()`). Il service inserisce **prima** il metadato (così un duplicato è
> rilevato senza scrivere byte orfani), **poi** i byte.

**Flusso pre-signed (predisposto, coll/prod).** L'upload server-side funziona ovunque (i byte vanno
su MinIO/S3 in coll/prod). In più, per non far transitare i byte dall'API, è predisposto il flusso
pre-signed: `SourceService.presigned_upload_url()` restituisce un URL PUT firmato dallo storage
(`None` con storage locale/dev). Attivazione futura come endpoint dedicato (`POST` che crea un
record `processing` + URL, poi conferma).

### Architettura (Clean Architecture)

Obiettivo: poter scambiare lo storage dei dati e dei byte **senza toccare service né controller**.

```
controllers/source_controller.py     thin: query param → service → (envelope, 200)
        │  (assemblato da)
factory.py  ── build_source_service() ── legge l'ambiente, sceglie repo + storage
        │
services/source_service.py           orchestrazione: repo.find() → DTO + stream_url
        ├── repositories/            persistenza metadati
        │     ├── base.py            Protocol SourceMediaRepository (find, get, insert)
        │     ├── mock_repository.py statico, in-memory (dev/test)
        │     └── sqlite_repository.py  SQLite WAL (coll/prod e dev con DB)
        └── storage/                 byte dei media
              ├── base.py            Protocol StorageBackend (get_stream_url, get_upload_url, put_object, object_exists)
              ├── local_backend.py   FS del container (dev): nessun URL firmato
              └── minio_backend.py   MinIO/S3 (coll/prod): URL pre-firmati
```

Il `SourceService` riceve `object_key` dal repository (riferimento interno allo storage) e lo
traduce in `stream_url` chiamando lo storage backend; `object_key` **non viene mai esposto**.

### Selezione del backend (factory)

| Env var | Effetto |
|---------|---------|
| `SOURCE_DB_PATH` impostata | repository **SQLite** su quel file; altrimenti **Mock** in-memory |
| `STORAGE_BACKEND=local` (default) | byte su FS (`SOURCE_MEDIA_DIR`); `stream_url=null` |
| `STORAGE_BACKEND=minio` \| `s3` | `MinioStorageBackend` con `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_BUCKET`, `STORAGE_SECURE` |

Gli import dei backend concreti sono **lazy**: dev/test con backend `local` non caricano l'SDK
`minio`.

### Persistenza SQLite

`SqliteSourceMediaRepository`: WAL mode (lettori concorrenti + 1 scrittore), connessione
**per-chiamata** (sicura col threadpool di connexion), schema idempotente creato all'avvio.

Schema (`src/domains/source/repositories/schema.py`):
```sql
CREATE TABLE IF NOT EXISTS source_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    size_bytes INTEGER, duration_s INTEGER,
    created_at_s INTEGER NOT NULL DEFAULT (unixepoch()),
    status TEXT NOT NULL DEFAULT 'ready', metadata TEXT
);
-- indici su media_type, title, status
```

### Storage e streaming da browser

Scelta strategica: **object storage S3-compatible** (MinIO self-hosted in coll/prod, S3/R2
opzione futura). Motivo legato al **play da browser**:

- Con storage locale, ogni byte audio passerebbe per l'API (connexion→proxy→browser): collo di
  bottiglia, niente Range request native.
- Con object storage, l'API restituisce nel JSON uno **`stream_url` pre-firmato** (scade 1h) e il
  browser scarica i byte **direttamente** dallo storage, con **Range request native** (seek/resume
  dell'audio). L'API resta fuori dal path dei byte.

```
Browser ─ GET /v0/source/media ─► API (SQLite + genera stream_url)
Browser ─ GET stream_url ───────► MinIO/S3 (Range, seek)   ← l'API non è coinvolta
```

In **dev** gestiamo solo l'upload locale (`STORAGE_BACKEND=local`): `stream_url=null`, lo streaming
da browser si abilita in coll/prod. Runbook MinIO: [`deploy/storage/README.md`](../deploy/storage/README.md).

### Verifica end-to-end (seed)

`make seed-source` (idempotente) inserisce record demo e carica placeholder sullo storage, così gli
`stream_url` risolvono. Utile per validare la catena dopo un deploy. Internamente:
`docker compose -f docker-compose.source.yml exec source python -m src.domains.source.seed`.

### Implementazioni attuali vs future

| Aspetto | Oggi | Futuro |
|---------|------|--------|
| Listing `GET /v0/source/media` | ✅ SQLite + paginazione + filtri | — |
| Storage byte | ✅ local (dev), MinIO (coll/prod) | S3/R2 (solo cambio env) |
| `stream_url` | ✅ pre-firmato (MinIO/S3), null in local | — |
| Upload server-side | ✅ `POST /v0/source/media` (multipart) | — |
| Upload pre-signed (browser→storage) | predisposto (`presigned_upload_url` + `get_upload_url`) | endpoint dedicato in coll/prod |
| `SqliteSourceMediaRepository` `insert`/`get` | ✅ (usati da upload e seed) | — |

---

## Aggiungere un nuovo dominio

Grazie alla discovery, basta:
1. `openapi/<nuovo>/api.yaml` (path relative, riusa `openapi/shared/`);
2. `src/domains/<nuovo>/controllers/` (operationId ri-esportati nel package `__init__`);
3. `docker-compose.<nuovo>.yml` + `config/<nuovo>/<env>.env`.

Makefile, CI e proxy si adattano da soli (wildcard sui domini). Nessun hardcoding.
