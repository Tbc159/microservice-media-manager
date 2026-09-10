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
| `GET /v0/media?type=&title=&page=&page_size=` | lista (delega a source); URL ri-mappati su `/v0/media`. **`type` e `title` opzionali**: senza `type` elenca tutto l'archivio |
| `GET /v0/media/{id}` | metadati del singolo media |
| `GET /v0/media/{id}/content[?download=1]` | byte: inline (play) o allegato (download) |
| `POST /v0/media` | upload (multipart, delegato a source) |
| `POST /v0/media/from-url` | crea un media scaricando un URL lato server (difese SSRF; delega a source) |

> **`media_type` — MIME e normalizzazione.** L'enum di **upload** accetta `audio/m4a`, `audio/mpeg`,
> `audio/mp3` (**alias legacy** di `audio/mpeg`, normalizzato: archiviato e filtrabile come
> `audio/mpeg`), `audio/wav`, `video/mp4`, `image/png|jpeg|webp`. Filtrare per `audio/mp3` o
> `audio/mpeg` restituisce lo stesso insieme. `GET /v0/media` **senza `type`** elenca ogni tipo.
> Il **filtro** `GET /v0/media?type=` accetta anche `font/ttf`/`font/otf` (i font sono **elencabili**),
> ma l'**upload pubblico di font non esiste**: i font si caricano solo dalla rete interna (`source`).

**Download/streaming — il nodo `media → source`** (`MediaService` + `SourceGateway`):
- `media` chiama `source` con `follow_redirects=False`;
- **coll/prod**: source risponde `302` → media **propaga il 302** verso lo storage; il client scarica
  diretto, media resta **fuori dal path dei byte**;
- **dev**: source risponde `200` (storage locale) → media **relaia i byte** (limite di dev accettato).

Il gateway usa **HTTP diretto** (httpx) sulla rete docker, non l'SDK generato (il runtime non usa
`generated/`). Config: `SOURCE_INTERNAL_URL` (default `http://source:8080/v0/source`), `API_KEY`.

> Evoluzione: `media` potrà arricchire i metadati con la propria business logic (es. pubblicazione)
> oltre ai dati grezzi di `source`.

### `POST /v0/media/from-url`
Crea un media **scaricandolo lato server** da un URL, così il client (es. un browser che tiene i file
su Blossom, archivio a contenuto indirizzato per hash) evita il doppio transito
download + re-upload di file grandi. Protetto (`X-API-Key`). Body JSON:
`{ url, title, media_type?, duration_s? }`. Il server scarica i byte e **delega la creazione a
source** (`POST /source/media`, stesso storage e stessa dedup dell'upload multipart).

- **`media_type`**: opzionale. Se assente è **dedotto dal `Content-Type`** della risposta. Se il tipo
  (fornito o rilevato) non è fra quelli accettati → **`400`** che indica il tipo rilevato (non un `500`).
- **Difese SSRF** (l'URL è esterno, `src/domains/media/fetcher.py`): solo **http/https**; l'host non
  deve risolvere su indirizzi **privati/loopback/link-local/riservati** (blocca la rete interna e il
  metadata endpoint `169.254.169.254`); **limite di dimensione** (`413`), **timeout** e **max N
  redirect rivalidati a ogni hop** (`502`). Configurabili: `MEDIA_FETCH_MAX_BYTES`,
  `MEDIA_FETCH_TIMEOUT`, `MEDIA_FETCH_MAX_REDIRECTS`.
- **Filename**: dedotto dal path dell'URL (per Blossom = l'hash) → stesso contenuto ⇒ stesso
  `object_key` ⇒ **`409`** come `POST /v0/media`, così il client riusa il record invece di trattarlo
  come errore.

| Esito | Codice |
|-------|--------|
| Creato | `201` → `MediaItem` (URL su `/v0/media`) |
| URL non consentito (schema/host non pubblico) o `media_type` non accettato | `400` |
| Contenuto già presente | `409` |
| Oltre il limite di dimensione | `413` |
| Download fallito (irraggiungibile, errore remoto, troppi redirect) | `502` |

> Nota SSRF: il controllo DNS e la connessione sono in momenti distinti (finestra di DNS-rebinding).
> La rivalidazione a ogni redirect e un solo host per richiesta riducono il rischio; il pinning
> sull'IP validato è l'irrigidimento successivo se servisse.

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
| `type` | **no** | enum | — | `audio/m4a` \| `audio/mpeg` \| `audio/mp3` (alias→mpeg) \| `audio/wav` \| `video/mp4` \| `image/png` \| `image/jpeg` \| `image/webp` \| `font/ttf` \| `font/otf`. **Omesso → tutti i tipi** |
| `title` | no | string | — | match **esatto**; combinabile con `type` |
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
| `media_type` | sì | enum | `audio/m4a` \| `audio/mpeg` \| `audio/mp3` (alias→mpeg) \| `audio/wav` \| `video/mp4` \| `image/png` \| `image/jpeg` \| `image/webp` \| `font/ttf` \| `font/otf`. `audio/mp3` viene **normalizzato** a `audio/mpeg` (storage + `object_key`) |
| `duration_s` | no | integer | durata in secondi |

> Gli `image/*` sono stati aggiunti per gli **asset** (logo, avatar) usati dal dominio
> `content`; i `font/*` per i **font personalizzati**. Si caricano come un media qualsiasi e
> si referenziano poi per id o nome file. **Nota**: i font si caricano **solo internamente**
> (questo upload multipart su `source`, oppure `POST /source/media/from-url`); non esiste un
> upload pubblico di font su `media`.

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

### `POST /v0/source/media/from-url`
Variante **interna** dell'upload: invece del file multipart, il server **scarica** il contenuto da
un URL e lo salva come gli altri media. Protetto (`X-API-Key`). Pensato per il provisioning di asset
dalla rete interna — in particolare i **font personalizzati** (l'upload pubblico di font non esiste).

Request `application/json`:

| Campo | Obblig. | Tipo | Note |
|-------|---------|------|------|
| `url` | sì | string (uri) | URL da cui scaricare il contenuto |
| `title` | sì | string | titolo |
| `media_type` | sì | enum | stesso enum dell'upload (incl. `font/ttf`/`font/otf`) |
| `filename` | no | string | nome file per l'`object_key`; se omesso, **dedotto dall'URL** |
| `duration_s` | no | integer | durata in secondi |

Risposte: `201` → `SourceMediaItem`; `400` campi mancanti / `media_type` fuori enum / filename non
deducibile; `409` `object_key` duplicato; **`502`** download fallito (URL irraggiungibile, errore
remoto o oltre il cap); `401` senza chiave.

> **Sicurezza leggera** (il dominio è già interno, `.internal`): il download
> (`src/domains/source/downloader.py`) ha **timeout** e **dimensione massima ~50 MB** (streaming con
> abort), ma **nessun** vincolo di scheme o blocco IP. Il controller scarica i byte e riusa lo stesso
> `SourceService.create()` dell'upload multipart (stesso ordine metadati→byte, stessi 409).

### `GET /v0/source/media/{id}`
Metadati del **singolo** record (il listing è su `GET /v0/source/media`). Protetto (`X-API-Key`).
`200` → `SourceMediaItem`; `404` se l'id non esiste. I **byte** sono sulla sotto-risorsa `/content`.

> Scelta di design: `/{id}` = **metadati** (JSON, leggero, cache-abile); i byte sono una
> sotto-risorsa esplicita. Un `GET /{id}` che restituisse i byte costringerebbe a scaricare il file
> anche solo per leggere il titolo, e a inventare un altro path per i metadati.

### `GET /v0/source/media/by-filename/{name}`
Risolve i metadati di un media per **nome** (uso **interno**: il dominio `content` referenzia gli
asset per id *o* per nome). Protetto (`X-API-Key`). `200` → `SourceMediaItem`; `404` se nessun record
corrisponde. La risoluzione è **tollerante**: prima il match **esatto** sul filename, poi un match
**normalizzato** che ignora maiuscole, estensione e separatore — `Montserrat-Bold.ttf` ≡
`montserrat-bold` ≡ `montserrat bold`. Il filename non è univoco (l'unicità è su
`media_type/filename`): in caso di più match vince il **più recente**.

> Implementato da `repo.find_by_name()` (esatto via indice, poi fallback normalizzato con
> `normalize_asset_name`) e `SourceService.get_item_by_filename()`. Endpoint a 4 segmenti
> (`.../by-filename/{name}`), distinto da `.../{id}` (3 segmenti, id intero): nessuna collisione di
> routing.

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
        │     ├── base.py            Protocol SourceMediaRepository (find, get, find_by_filename, insert)
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
| Upload interno via URL | ✅ `POST /v0/source/media/from-url` (download timeout + cap 50 MB) | allowlist host in coll/prod se serve |
| Upload pre-signed (browser→storage) | predisposto (`presigned_upload_url` + `get_upload_url`) | endpoint dedicato in coll/prod |
| Byte `GET /v0/source/media/{id}/content` | ✅ inline/`?download=1`, 302 in coll/prod, streaming+Range in dev | — |
| Dominio `media` come BFF pubblico | ✅ `media` espone, `source` interno (`.internal`); download via 302 passthrough (relay solo in dev) | arricchimento metadati business |
| `SqliteSourceMediaRepository` `insert`/`get` | ✅ (usati da upload e seed) | — |

---

## Dominio `content` — generazione immagini (BFF pubblico)

`content` genera **immagini** (copertine, social) a partire da asset già caricati su `/v0/media`.
È un **BFF pubblico** come `media`: legge gli asset da `source` sulla rete interna, produce
l'immagine con **Pillow**, la **salva come media** (`image/*`) e ne restituisce gli URL pubblici
(ri-mappati su `/v0/media`). Contratto: `openapi/content/api.yaml`. Il rendering è portato da
`microservices-media` (`ytmedia/slide_processor.py`) e reso framework-agnostic.

```
Client ─► POST /v0/content/image ─► [content] ─(source:8080)─► risolve asset + salva risultato
                                                  └─► risposta: GeneratedImage (content_url su /v0/media)
```

### `POST /v0/content/image`
Genera un'immagine e la salva come media. Protetto (`X-API-Key`). Body **JSON polimorfico**: il
campo `tipo` (discriminatore) seleziona il generatore e **quali campi** sono ammessi.

| `tipo` | Stato | Campi propri |
|--------|-------|--------------|
| `copertina` | ✅ attivo | template fisso "21milioni di chiacchiere": `titolo`*, `testo_centrale`*, `logo_host`*, `ospiti[≤5]`, `colore_sfondo`, `tipo_sfondo` (`unicolor`\|`sfumato-up`\|`sfumato-down`), `colore_sfumato`, `formato`, `font_titolo`, `font_testo` |
| `composita` | ✅ attivo | **motore a layer** (1920×1080): `layers[]`* (vedi sotto), `formato` |
| `social` | ✅ attivo | **preset** quadrato (1080×1080): `logo_top`*, `logo_bottom`, `testo`, `testo_bottom`, `colore_sfondo`, `colore_testo`, `font`, `formato` |
| `slide` | ✅ attivo | **preset** 16:9 da copertina video (1920×1080): `titolo`*, `sottotitolo`, `sfondo`, `fit`, `persone[≤3]`, `logo`, `colore_sfondo`, `colore_velo`, `velo`, `colore_testo`, `dimensione_titolo`, `allineamento`, `font_titolo`, `font_testo`, `formato` |

(*) obbligatorio. `formato` ∈ `image/png` (default) \| `image/jpeg` \| `image/webp`.

**Asset (`MediaRef`)**: `logo_host`, `ospiti`, `logo_top`/`logo_bottom`, `font_titolo`/`font_testo`,
`layers[].media`, `layers[].font` accettano un **id media** (intero) **oppure** il **`filename`**
(stringa). Un ospite non trovato → **avatar placeholder** (non è un errore); il **logo** mancante → `400`.

> ⚠️ **`filename`, non `title`.** `MediaItem` ha due campi testuali: `title` (quello che *invii* a
> `POST /v0/media`) e `filename` (**generato dal servizio**). La risoluzione per stringa usa **solo il
> `filename`**, che va **riletto dalla risposta** di `POST /v0/media`. Passare il `title` produce `400`.
> Il match sul filename è tollerante (case/estensione/separatore).
>
> **Perché non risolviamo per `title`.** I title non sono univoci: risolverli imporrebbe o una scelta
> silenziosa (il footgun) o un `409` su ogni ambiguità. Teniamo un'unica chiave stabile (`filename`) e
> rendiamo l'errore *diagnostico*: il `400` indica **`field`** (es. `logo_host`, `layers[2].media`),
> **`value`** ricevuto, **`searched_by`** (`filename`|`id`) e — se il valore coincide col `title` di un
> media esistente — **suggerisce il `filename`** giusto. Corpo (schema `Error` esteso):
>
> ```json
> { "detail": "asset non trovato per il campo 'logo_host': 'Logo Bianco' (ricerca per filename). Esiste però un media con quel *title* (id 60 -> filename 'logo-bianco.png'): i riferimenti usano il filename, non il title.",
>   "field": "logo_host", "value": "Logo Bianco", "searched_by": "filename" }
> ```

**Font (`font_titolo`/`font_testo`)**: catena di fallback per ogni ruolo — font personalizzato (byte
da `source`) → **Montserrat bundle** → **default Pillow**. Un font **richiesto ma non trovato** (o
byte non validi) **non blocca**: si usa il predefinito e si aggiunge una voce a `warnings` (la
risposta resta `201`). Asimmetria voluta: **logo mancante = `400`** (hard), **font mancante = warning
+ `201`** (soft).

Risposte: `201` → `GeneratedImage` `{ id, tipo, media_type, size_bytes, created_at_s, content_url,
download_url, warnings[] }` (gli URL puntano a `/v0/media/{id}/content`; `warnings` elenca i fallback
non bloccanti); `400` parametri invalidi o asset **obbligatorio** non trovato (corpo **diagnostico**:
`field`/`value`/`searched_by`, vedi sopra); `501` `tipo` senza generatore associato (contratto
riservato ai tipi futuri: oggi nessuno lo restituisce); `401` senza chiave.

**Esempio (Bruno / curl).** Prima carica gli asset come media `image/*` per ottenerne gli id:

```bash
# 1) carica il logo host (ripeti per gli avatar ospiti) -> annota "id" dalla risposta
curl -X POST http://mediamanager-dev.duckdns.org/v0/media \
  -H "X-API-Key: <chiave>" \
  -F "file=@logo-host.png" -F "title=Logo host" -F "media_type=image/png"

# 2) genera la copertina (logo_host/ospiti per id OPPURE per nome file)
curl -X POST http://mediamanager-dev.duckdns.org/v0/content/image \
  -H "X-API-Key: <chiave>" -H "Content-Type: application/json" \
  -d '{
        "tipo": "copertina",
        "titolo": "Bitcoin Radio",
        "testo_centrale": "è lieto di ospitare",
        "logo_host": "logo-host.png",
        "ospiti": [21, 22],
        "colore_sfondo": "#ff751f",
        "tipo_sfondo": "unicolor",
        "formato": "image/png"
      }'
# -> 201 { "id": 101, "content_url": "/v0/media/101/content", ... }
# scarica l'immagine: GET http://mediamanager-dev.duckdns.org/v0/media/101/content
```

### `tipo: composita` — motore a layer

Mentre `copertina` è un template fisso, `composita` compone una **lista ordinata di layer** su una
canvas **1920×1080** (HD YouTube). `layers` è un array: il **primo elemento è il fondo**, i
successivi si impilano sopra (**z-order = ordine nell'array**), **senza numero massimo**. Ogni layer
ha un `type` e i propri campi; gli asset (sfondi, persone, loghi, font) si referenziano per **id o
nome file** (`MediaRef`).

> **Nota lingua**: l'envelope (`tipo`, `formato`) resta in italiano come `copertina`/`social`; i
> **campi dei layer sono in inglese** (motore generico). Il codice del compositor è in inglese.

**Tipi di layer (`type`):**

| `type` | A cosa serve | Campi principali |
|--------|--------------|------------------|
| `background` | immagine/colore a piena canvas | `media`, `fit` (`cover`\|`contain`\|`stretch`), `fallback_color`, `overlay` |
| `person` | persona PNG **scontornata**, N affiancabili | `media`*, `x`, `y`, `size`, `opacity`, `mask`, `required` |
| `text` | testo (titolo/dettagli), `\n` multi-riga | `content`*, `font`, `font_size`, `color`, `align`, `x`, `y`, `max_width`, `stroke`, `box` |
| `image` | logo/inserto/grafica sovrapposta | `media`*, `x`, `y`, `size`, `opacity`, `mask`, `required` |

**Posizionamento (`x`/`y`)** — tre forme, semantica unica:

| Forma | Esempio | Significato |
|-------|---------|-------------|
| keyword | `x: left`\|`center`\|`right` · `y: top`\|`center`\|`bottom` | ancore (zucchero delle percentuali) |
| percentuale | `x: "75%"` | **posizione nello spazio libero**: `0%` a filo, `100%` a filo opposto, `50%` centrato |
| pixel | `x: "640"` / `"640px"` | coordinata assoluta del bordo del layer |

`size` (`{width, height}`) accetta `%` o px; una sola → aspetto preservato; nessuna → naturale
(clampata alla canvas, mai ingrandita).

**Ritaglio (`mask: circle`)** su `person`/`image`: il layer diventa un **cerchio** del diametro
richiesto in `size` (se sono date entrambe le dimensioni vince la minore). L'immagine viene
riempita a `cover` e ritagliata al centro, quindi **il diametro non dipende dalle proporzioni della
sorgente**: un logo 3:1 e uno quadrato producono lo stesso tondo, senza deformarsi.

**Velo sullo sfondo (`overlay`)** su `background`: `{color, opacity}` steso sopra l'immagine (sotto
agli altri layer). È il modo standard per rendere leggibile un titolo su una foto complessa —
`{ "color": "#000000", "opacity": 0.45 }` è quello che usa il preset `slide`.

**Stile del testo** (è ciò che rende le copertine "da YouTube"):
- `stroke`: `{width, color}` — bordo del testo (nativo Pillow).
- `box`: `{color, radius, padding, opacity}` — riquadro arrotondato colorato dietro al testo
  (i tipici box gialli/scuri con la scritta in grassetto).
- `shadow`: `{color, offset{x,y}, blur, opacity}` — ombra o **glow/neon**: `offset {0,0}` + `blur`
  alto = alone luminoso (es. "LIVE"); offset valorizzato + `blur` basso = ombra portata.
- `max_width`: se valorizzato, va a capo automatico sulle parole.

**Asset mancante**: di default il layer viene **saltato con un `warning`** (la composizione non
fallisce); con `required: true` invece → `400`. Lo sfondo mancante cade su `fallback_color`. I
`font` seguono la stessa catena di `copertina` (custom → Montserrat → default Pillow + warning).

**Standardizzazione**: lo schema è a **N layer** (nessun massimo); il template tipico è
`background → person/e → testo titolo → testi/loghi di dettaglio`, ma resta libero di crescere.

**Esempio** (riproduce una copertina tipo "Rassegna Stampa"):

```jsonc
{
  "tipo": "composita",
  "formato": "image/png",
  "layers": [
    { "type": "background", "media": 100, "fit": "cover" },
    { "type": "person", "media": 101, "x": "right", "y": "bottom",
      "size": { "height": "95%" } },
    { "type": "text", "content": "RASSEGNA\nSTAMPA", "x": "left", "y": "12%",
      "font": 30, "font_size": 150, "color": "#ff751f",
      "stroke": { "width": 6, "color": "#000000" } },
    { "type": "text", "content": "UFFICIALE!\nBINANCE FUORI LEGGE",
      "x": "70%", "y": "55%", "font_size": 48, "color": "#000000",
      "box": { "color": "#ffd200", "radius": 18, "padding": 16 } },
    { "type": "text", "content": "EP. 26/2026", "x": "left", "y": "bottom",
      "font_size": 60, "color": "#ffffff" }
  ]
}
```

### `tipo: social` e `tipo: slide` — preset del motore a layer

Un **preset** non è un secondo motore: è una funzione pura che espande i propri campi nei **layer**
di `composita` e passa dallo **stesso renderer**. Conseguenza pratica: stessa risoluzione degli
asset, stessi `warnings`, stessi `400` diagnosticabili, un solo percorso di codice da mantenere.
Serve un layout diverso da quello del preset? Si usa `composita` e si scrivono i layer a mano.

> I `400` dei preset citano il **campo della richiesta** (`logo_top`, `sfondo`, `persone`), non
> `layers[2].media`: chi chiama vede il proprio contratto, non l'espansione interna.

**`social` — quadrato 1080×1080.** Dall'alto: sfondo a tinta unita (`colore_sfondo`) → `logo_top`
(vincolato in **altezza**, 170 px, a 70 px dal bordo: la fascia che occupa non dipende dalle sue
proporzioni, così il testo non gli finisce mai sopra) → `testo` reso in **MAIUSCOLO** e centrato
verticalmente → `logo_bottom` ritagliato **a cerchio** di 260 px → `testo_bottom` in fondo.
`logo_top` è obbligatorio (non risolvibile → `400`); `logo_bottom` degrada a warning.

```jsonc
{ "tipo": "social", "logo_top": "logo-radio.png", "logo_bottom": 42,
  "testo": "è lieto di ospitare", "testo_bottom": "Alice Rossi",
  "colore_sfondo": "#ff751f", "colore_testo": "#ffffff" }
```

**`slide` — 16:9 1920×1080, copertina di un video** (il caso d'uso finora scritto a mano con
`composita`). Dallo sfondo in su: `sfondo` a piena canvas (`fit`, fallback `colore_sfondo`) + un
**velo** (`colore_velo` + `velo`, default nero 0.45) che rende leggibile il testo → fino a 3
`persone` scontornate allineate in basso → `logo` in alto a sinistra (260 px) → `titolo` con glow →
`sottotitolo`.

`allineamento` decide l'impaginazione:

| valore | titolo/sottotitolo | ospiti |
|---|---|---|
| `left` (default) | a sinistra, 80 px dal bordo, larghezza max 920 px | fascia di destra |
| `center` | centrati | distribuiti su tutta la larghezza |

Due accorgimenti che rendono il preset robusto: l'**altezza degli ospiti si adatta al numero**
(1 → 70% della canvas, 2 → 62%, 3 → 55%) e titolo/sottotitolo sono posizionati **nello spazio
libero** (`y: "55%"`/`"80%"`), quindi un titolo che va a capo su più righe sale da solo senza mai
sovrapporsi al sottotitolo.

```jsonc
{ "tipo": "slide", "titolo": "Bitcoin è denaro,\nnon un investimento",
  "sottotitolo": "Puntata 42 — con Alice e Bob",
  "sfondo": "studio.jpg", "logo": "logo-radio.png", "persone": [21, 22],
  "velo": 0.5, "allineamento": "left", "formato": "image/jpeg" }
```

**Aggiungere un preset**: un builder in `services/presets.py` (richiesta → `(canvas, layers)`, senza
I/O) + il suo schema `<Nome>Request` in `openapi/content/api.yaml` (voce nel `discriminator` e nella
`mapping`, e il nuovo valore in `GeneratedImage.tipo`). Il service e il renderer non cambiano.

### `GET /v0/content/fonts` — catalogo font

Elenco dei font caricati su `source` (`font/ttf`/`font/otf`), referenziabili nei layer `text`
(campo `font`) o in `copertina` per **id** o **nome** (risoluzione tollerante). Protetto
(`X-API-Key`). `200` → array di `FontInfo` `{ id, name, filename, media_type, size_bytes?, created_at_s }`.

**Kit font consigliato** (free, Google Fonts, incorporabili) per riprodurre lo stile dei canali:

| Nome canonico | Uso | Famiglia |
|---|---|---|
| `montserrat-black` / `-extrabold` / `-bold` / `-regular` | titoli e testi | Montserrat |
| `bebas-neue` | display condensato ("LIVE", titoli punchy) | Bebas Neue |
| `great-vibes` | script elegante (firme "con … ") | Great Vibes |
| `pacifico` | brush/firma | Pacifico |

Si caricano una volta sola **dalla rete interna** con `POST /v0/source/media/from-url` (i Google
Fonts hanno URL `.ttf` diretti), scegliendo il `filename` canonico; poi si referenziano per nome.

### Architettura

```
controllers/content_controller.py    thin: body → service → (201 | 400 | 501)
        │  (assemblato da)
factory.py  ── build_image_service() ── SOURCE_INTERNAL_URL, API_KEY
        │
services/image_service.py            orchestrazione: risolve MediaRef → byte, dispatch su `tipo`,
        │                            salva su source, ri-mappa URL /v0/source → /v0/media
        │                            (`composita` e i preset condividono `_generate_layered`)
        ├── services/copertina_renderer.py   Pillow puro (copertina 2560×1440), niente rete/framework
        ├── services/presets.py              social/slide → (canvas, layers): funzione pura, niente I/O
        ├── services/layer_compositor.py     Pillow puro, canvas parametrica, compositing a layer
        └── gateway.py               SourceGateway: resolve_filename, get_bytes (segue il 302), upload_image
```

> A differenza del gateway di `media` (che **propaga** il 302 nel relay), qui `get_bytes`
> **segue i redirect**: a `content` servono i byte veri dell'asset per darli a Pillow.

**Font**: il renderer usa i Montserrat (`ExtraBold`/`Light`), **non versionati**. Vanno messi in
`FONTS_DIR` (default `/app/fonts`, montabile come volume — vedi `docker-compose.content.yml`). Se
mancano, il renderer **non fallisce**: degrada al font di default di Pillow e logga un warning.

### Implementazioni attuali vs future

| Aspetto | Oggi | Futuro |
|---------|------|--------|
| `POST /v0/content/image` `tipo: copertina` | ✅ Pillow, asset per id/nome file, output png/jpeg/webp | — |
| `tipo: composita` (motore a layer, canvas parametrica) | ✅ `layer_compositor.py`: `background`/`person`/`text`/`image`, posizione keyword/%/px, `size`, `stroke`/`box`/`shadow`, `mask: circle`, `overlay`, N layer | template/preset salvabili |
| `tipo: social` (1080×1080) | ✅ **preset** sul motore a layer (`presets.py`), non un secondo renderer | — |
| `tipo: slide` (16:9 copertina video) | ✅ **preset**: sfondo+velo, ≤3 ospiti, titolo/sottotitolo, logo, `allineamento` | preset salvabili lato utente |
| Salvataggio risultato | ✅ come media `image/*` via `source`, recupero via `/v0/media` | — |
| Font personalizzati (`font_titolo`/`font_testo`) | ✅ caricati su `source` (`font/ttf`/`otf`), referenziati per id/nome file | — |
| Font mancante | ✅ fallback (custom → Montserrat → Pillow) + `warnings[]` nella risposta | — |
| Font Montserrat bundle | ⚠️ fallback al default se assenti | TTF montati in `FONTS_DIR` |

---

## Dominio `audio` — elaborazione audio (BFF pubblico)

Porta le capacita' del vecchio servizio `ffmpeg` (microservices-media) **senza i suoi vincoli**.
Contratto: `openapi/audio/api.yaml`. Pubblico → CORS/HTTPS come `media`/`content`.

**Input = riferimento** (`MediaRef`: id o filename) a un media in archivio, risolto via `source`,
**non un upload dentro l'operazione**: la stessa sorgente si riusa fra piu' tentativi. **Ogni
operazione produce un NUOVO media e non distrugge l'ingresso.** Ordine libero e formati
indifferenti (ogni operazione risolve il riferimento allo stesso modo; niente cartelle-per-op,
niente "solo mp3": **anche i wav** passano da `silence`).

### Operazioni (modello a job)
Le lavorazioni sono lunghe: `POST` risponde **`202`** con `{ job_id, status, op, poll_url }`; si
segue con `GET /v0/audio/job/{id}` (`queued` → `running` → `succeeded`|`failed`). I job sono
**persistenti** (SQLite): sopravvivono al riavvio (i `running` interrotti tornano `queued`).

| Endpoint | Cosa fa | Output |
|----------|---------|--------|
| `POST /v0/audio/normalize` | livella le voci (EBU R128) | nuovo media audio (default mp3) |
| `POST /v0/audio/silence` | accorcia i silenzi (incl. iniziale/finale) | nuovo media (default wav) |
| `POST /v0/audio/convert` | cambia contenitore/codec | nuovo media nel `format` |
| `POST /v0/audio/analyze` | **misura** e non modifica nulla | `result.analysis` (riusabile) |
| `POST /v0/audio/split` | divide in segmenti | N nuovi media |
| `POST /v0/audio/concat` | sigla + corpo + coda | un nuovo media |
| `GET /v0/audio/job/{id}` | stato del job | `result.media[]` o `result.analysis` |

A `succeeded`, `result.media[]` elenca `{ id, media_type, content_url, download_url }` (URL su
`/v0/media`); per `analyze`, `result.analysis` (associata al media, non ricalcolata).

### Scelte DSP (misurate)
- **normalize**: `dynaudnorm=f=250:g=11:m=<maxgain>` + `loudnorm`. **`maxgain` e' il tetto di
  correzione** (dB = 20·log10(maxgain)); il default 10 di ffmpeg (+20 dB) lascia i parlanti
  disallineati — qui **default 80**. Misurato su due parlanti a 18 LU di scarto: catena vecchia
  ~non allinea; con `maxgain` alto lo scarto scende **< 1 LU** e il file va a **-16 LUFS**.
  `two_pass` (misura+applica) e' piu' preciso ma raddoppia il tempo; una passata basta.
- **silence**: `silenceremove` con `start_periods` (**taglia il silenzio iniziale lungo**, nuovo
  requisito) + `stop_periods=-1`, lasciando `keep_silence_s` (pausa udibile, non stacchi netti).
  Soglia con **unita' dB** (`-40dB`, non ampiezza lineare).
- **Intermedi senza perdita**: `silence`/`split` producono wav di default; la compressione avviene
  dove il chiamante sceglie il `format` (`normalize`/`convert`/`concat`). Cosi' una catena di
  operazioni non ricomprime a ogni passaggio.
- **Raccomandazione di qualita'** (nell'endpoint, non imposta dall'infrastruttura): **prima
  `silence`, poi `normalize`** — normalizzare prima alza il rumore di fondo sopra la soglia di
  silenzio e il taglio non lo riconosce piu'.
- **Limite dichiarato**: due voci sovrapposte nello stesso canale non si separano; con tracce
  separate per parlante, normalizzarle prima del mix e' meglio.

### Contratto errori & formati
- Formati input accettati: `audio/m4a`, `audio/mpeg` (`audio/mp3` alias), `audio/wav`. Output:
  `audio/mpeg`|`audio/m4a`|`audio/wav`. Dichiarati nell'OAS **per operazione**.
- Errori **diagnostici** (`400`): riferimento non risolto → `field`/`value`/`searched_by`; formato
  non supportato → il tipo rilevato + i formati accettati. (Il client non deve piu' "sapere" da se'
  che i wav non si possono tagliare: e' falso, e comunque l'errore lo direbbe.)

### Naming human-readable
Gli id sono usabili **a mano**: job `normalize-20260910-153000-a3f9`, media prodotti
`<stem-sorgente>-<op>-<token>.<ext>` (es. `puntata-pilota-normalize-a3f9.mp3`). Niente uuid opachi.

### Architettura
```
controllers/audio_controller.py   thin: valida/accoda -> (202 job | 400 diagnostico)
factory.py  build_service()/build_worker()/maybe_start_background_worker()
services/audio_service.py          risolve MediaRef, valida formati, crea job (persistente)
worker.py                          rivendica un job, scarica input(source), ffmpeg, carica output
repositories/job_store.py          SQLite: job + cache analisi; claim atomico; recovery al riavvio
processors/ffmpeg_processor.py     command-builder puri (misurati) + runner + parsing analyze
gateway.py                         verso source: resolve/get_bytes/upload (byte reali, 302-follow)
```
Il worker gira in background nel container (`AUDIO_START_WORKER=1`); `AUDIO_DB_PATH` e' su volume
persistente. ffmpeg e' installato nell'immagine **solo** per `DOMAIN=audio` (Dockerfile parametrico).

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
