# Domini, API e implementazioni

Documentazione funzionale degli endpoint, contratti e architettura per dominio. Lo stato runtime
attuale è descritto in [changelog.md](changelog.md).

Convenzioni comuni:
- **base path**: `/v0` (applicato da `src/app.py`).
- **auth**: header `X-API-Key` sugli endpoint protetti (vedi [development.md](development.md#sicurezza-api-key)).
- **health**: ogni dominio espone `GET /v0/<dom>/health` → `{"status":"ok"}` (no auth).

---

## Dominio `media` — BFF pubblico

`media` è il **dominio pubblico** (Backend-for-Frontend): l'unico esposto al FrontEnd. Orchestra il
dominio **interno** `source` (vedi sotto) e ri-mappa gli URL dei byte da `/v0/source/...` a
`/v0/media/...`. Contratto: `openapi/media/api.yaml`.

```
FrontEnd ──► /v0/media/*  ──►  [media BFF]  ──(rete docker: source:8080)──►  [source interno]
```

Endpoint (specchio di `source`, sul path pubblico):

| Endpoint | Cosa fa |
|----------|---------|
| `GET /v0/media?type=&title=&page=&page_size=` | lista (delega a source); URL ri-mappati su `/v0/media` |
| `GET /v0/media/{id}` | metadati del singolo media |
| `GET /v0/media/{id}/content[?download=1]` | byte: inline (play) o allegato (download) |
| `POST /v0/media` | upload (multipart, delegato a source) |

**Download/streaming — il nodo `media → source`** (`MediaService` + `SourceGateway`):
- `media` chiama `source` con `follow_redirects=False`;
- **coll/prod**: source risponde `302` → media **propaga il 302** verso lo storage; il client scarica
  diretto, media resta **fuori dal path dei byte**;
- **dev**: source risponde `200` (storage locale) → media **relaia i byte** (limite di dev accettato).

Il gateway usa **HTTP diretto** (httpx) sulla rete docker, non l'SDK generato (il runtime non usa
`generated/`). Config: `SOURCE_INTERNAL_URL` (default `http://source:8080/v0/source`), `API_KEY`.

> Evoluzione: `media` potrà arricchire i metadati con la propria business logic (es. pubblicazione)
> oltre ai dati grezzi di `source`.

---

## Dominio `source` — interno

Bridge verso file system e database dei media sorgente. **Dominio interno**: marcato
`openapi/source/.internal`, **non** instradato dal reverse-proxy pubblico (raggiungibile solo sulla
rete docker `mediamgr`, dal BFF `media`). Contratto: `openapi/source/api.yaml`.

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
| `content_url` | string | URL (relativo) dei byte **inline** per il player (`/…/{id}/content`) |
| `download_url` | string | URL (relativo) dei byte come **allegato** (`/…/{id}/content?download=1`) |
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

Risposte: `201` → `SourceMediaItem` (con `content_url`/`download_url`); `400` campi mancanti /
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

### `GET /v0/source/media/{id}`
Metadati del **singolo** record (il listing è su `GET /v0/source/media`). Protetto (`X-API-Key`).
`200` → `SourceMediaItem`; `404` se l'id non esiste. I **byte** sono sulla sotto-risorsa `/content`.

> Scelta di design: `/{id}` = **metadati** (JSON, leggero, cache-abile); i byte sono una
> sotto-risorsa esplicita. Un `GET /{id}` che restituisse i byte costringerebbe a scaricare il file
> anche solo per leggere il titolo, e a inventare un altro path per i metadati.

### `GET /v0/source/media/{id}/content`
I **byte** del media. Protetto (`X-API-Key`). Stessi byte dallo stesso storage; cambia solo la
`Content-Disposition`:
- default → **inline** (per il player);
- `?download=1|true|yes|on` → **allegato** (salva su disco).

| Ambiente | Risposta |
|----------|----------|
| coll/prod (S3/MinIO) | **`302`** con `Location` → URL pre-firmato (disposition giusta); il client scarica/streamma **diretto dallo storage**, l'API resta fuori dal path dei byte |
| dev (storage locale) | **`200`** in streaming dal FS (`flask.send_file`), con `Content-Disposition` inline/attachment e **supporto Range** (`206`, seekable/ripristinabile) |
| id assente o byte mancanti | **`404`** (nessun corpo) |

> `SourceService.content(id, download)` restituisce un `DownloadTarget` discriminato (`redirect_url`
> per i backend remoti, `local_path` per il locale). `download=True` → `get_download_url`
> (attachment); `False` → `get_stream_url` (inline). Il param `download` è gestito come **stringa
> lenita** (`1|true|yes|on`) perché la coercion boolean di connexion accetta solo `true`/`false`.

> **Inline vs attachment.** Stessi byte, stesso storage, **solo l'header `Content-Disposition`
> cambia** — è una decisione del server, non negoziabile via `Accept` (per questo i byte stanno su
> una sotto-risorsa, non sotto content negotiation di `/{id}`).

### Architettura (Clean Architecture)

Obiettivo: poter scambiare lo storage dei dati e dei byte **senza toccare service né controller**.

```
controllers/source_controller.py     thin: query param → service → (envelope, 200)
        │  (assemblato da)
factory.py  ── build_source_service() ── legge l'ambiente, sceglie repo + storage
        │
services/source_service.py           orchestrazione: repo.find() → DTO + content_url/download_url
        ├── repositories/            persistenza metadati
        │     ├── base.py            Protocol SourceMediaRepository (find, get, insert)
        │     ├── mock_repository.py statico, in-memory (dev/test)
        │     └── sqlite_repository.py  SQLite WAL (coll/prod e dev con DB)
        └── storage/                 byte dei media
              ├── base.py            Protocol StorageBackend (get_stream_url, get_upload_url, get_download_url, put_object, local_path, object_exists)
              ├── local_backend.py   FS del container (dev): nessun URL firmato
              └── minio_backend.py   MinIO/S3 (coll/prod): URL pre-firmati
```

Il `SourceService` riceve `object_key` dal repository (riferimento interno allo storage) e lo
espone come `content_url`/`download_url` (verso `/content`); `object_key` **non viene mai esposto**.

### Selezione del backend (factory)

| Env var | Effetto |
|---------|---------|
| `SOURCE_DB_PATH` impostata | repository **SQLite** su quel file; altrimenti **Mock** in-memory |
| `STORAGE_BACKEND=local` (default) | byte su FS (`SOURCE_MEDIA_DIR`); i byte si servono via `/content` |
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

- Con storage locale, ogni byte audio passa per l'API (connexion→proxy→browser): collo di
  bottiglia. Accettabile in dev.
- Con object storage, l'endpoint `/content` risponde **`302`** verso un URL pre-firmato e il browser
  scarica/streamma i byte **direttamente** dallo storage, con **Range native** (seek/resume). L'API
  resta fuori dal path dei byte.

```
Browser ─ GET /v0/source/media/{id}/content ─► API (302 → URL pre-firmato)
Browser ─ GET <url pre-firmato> ─────────────► MinIO/S3 (Range, seek)   ← l'API non è coinvolta
```

In **dev** lo storage è locale: `/content` streamma dal FS (l'API è nel path dei byte). Il redirect
si abilita in coll/prod. Runbook MinIO: [`deploy/storage/README.md`](../deploy/storage/README.md).

### Verifica end-to-end (seed)

`make seed-source` (idempotente) inserisce record demo e carica placeholder sullo storage, così i
media sono scaricabili via `/content`. Utile per validare la catena dopo un deploy. Internamente:
`docker compose -f docker-compose.source.yml exec source python -m src.domains.source.seed`.

### Implementazioni attuali vs future

| Aspetto | Oggi | Futuro |
|---------|------|--------|
| Listing `GET /v0/source/media` | ✅ SQLite + paginazione + filtri | — |
| Singolo record `GET /v0/source/media/{id}` | ✅ metadati | — |
| Storage byte | ✅ local (dev), MinIO (coll/prod) | S3/R2 (solo cambio env) |
| `content_url`/`download_url` | ✅ link verso `/content` (inline/attachment) | — |
| Upload server-side | ✅ `POST /v0/source/media` (multipart) | — |
| Upload pre-signed (browser→storage) | predisposto (`presigned_upload_url` + `get_upload_url`) | endpoint dedicato in coll/prod |
| Byte `GET /v0/source/media/{id}/content` | ✅ inline/`?download=1`, 302 in coll/prod, streaming+Range in dev | — |
| Dominio `media` come BFF pubblico | ✅ `media` espone, `source` interno (`.internal`); download via 302 passthrough (relay solo in dev) | arricchimento metadati business |
| `SqliteSourceMediaRepository` `insert`/`get` | ✅ (usati da upload e seed) | — |

---

## Aggiungere un nuovo dominio

Grazie alla discovery, basta:
1. `openapi/<nuovo>/api.yaml` (path relative, riusa `openapi/shared/`);
2. `src/domains/<nuovo>/controllers/` (operationId ri-esportati nel package `__init__`);
3. `docker-compose.<nuovo>.yml` + `config/<nuovo>/<env>.env`.

Makefile, CI e proxy si adattano da soli (wildcard sui domini). Nessun hardcoding.

Per un dominio **interno** (non esposto pubblicamente, mediato da un BFF): aggiungere il marker
`openapi/<nuovo>/.internal` → il reverse-proxy non lo instrada e lo smoke lo verifica sulla rete
docker. Vedi `media`/`source`.
