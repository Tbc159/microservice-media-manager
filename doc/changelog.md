# Changelog del progetto

Cosa è stato **realmente implementato o predisposto** dall'ultimo allineamento del README fino
alle attività odierne. Ordine tematico/cronologico. Per i dettagli tecnici rimanda agli altri
documenti in `doc/`.

> Lo stato precedente del README descriveva: `base_path=/<dominio>`, solo dominio `media`, nessuna
> security, nessuna persistenza. Tutto ciò che segue è il **delta** rispetto a quel punto.

---

## 1. Schema URL unificato sotto `/v0`

- `src/app.py`: `base_path` cambiato da `/<dominio>` a **`/v0`**. URL effettivi: `/v0/media`,
  `/v0/media/health`, `/v0/source/media`, `/v0/source/health`.
- Reverse-proxy: `gen-nginx-conf.sh` genera **due** location per dominio
  (`location = /v0/<dom>` exact + `location /v0/<dom>/` prefix) per evitare il redirect loop
  301↔307 tra path con/senza slash finale.
- Fix correlati: `d043485` (redirect loop `/v0/media`), `580f68f` (location proxy).

## 2. Sicurezza: API key per connexion 3.x

- `src/security.py` con `api_key_info` registrato via estensione OAS
  `x-apikeyInfoFunc: src.security.api_key_info` (connexion 3.x non usa il routing Flask).
- Header `X-API-Key`; in container la chiave deve combaciare con il secret `API_KEY`, in dev
  qualunque chiave non vuota è accettata. Commit `2ef3d9d`.

## 3. Dominio `media`: `GET /v0/media`

- Endpoint di listing con schema `MediaItem` esteso (campo `pubblicazione`, `publishing_date_s`).
- Implementazione **statica** (`MediaService`, 3 item) conforme allo schema. Commit `a923cd6`.

## 4. Deploy reale su host (self-hosted runner + reverse-proxy)

- `generate-api.yml` ristrutturato: `detect` → `verify` (runner cloud) → `deploy` (self-hosted,
  label = environment). Build **sull'host**, nessun registry.
- Reverse-proxy nginx per host (`deploy/proxy/`), rete docker `mediamgr`, config generata dai
  domini. Runbook in `deploy/README.md`. Commit `35f6720`, merge `49f09d7`.

## 5. Dominio `source`: `GET /v0/source/media`

- Nuovo dominio (branch `infrastructure/source`): listing **paginato** con filtro `type` (enum) e
  `title` (esatto), envelope `{items, pagination}`. Commit `f24a0a8`.
- **Componenti OAS condivisi** estratti in `openapi/shared/components.yaml` (`ApiKeyAuth`,
  `Health`, `Error`, `PaginationMeta`); `media` e `source` li referenziano via `$ref`.
- Trigger `api-draft.yaml` esteso a `infrastructure/**`.

## 6. `source`: persistenza SQLite + storage S3-ready

Commit `1386d86`, merge PR #3 `fc9abe2`.

- **SQLite** (`SqliteSourceMediaRepository`): WAL, connessione per-chiamata, schema idempotente,
  `find()` paginato + `insert()`.
- **Storage astratto** (`StorageBackend` Protocol): `LocalStorageBackend` (dev, FS, `stream_url`
  null) e `MinioStorageBackend` (coll/prod, URL pre-firmati; stessa classe per S3/R2). Import
  `minio` lazy.
- **Clean Architecture**: `factory.py` (composition root) sceglie repo+storage da env; controller e
  service ignari del backend.
- **Contratto**: `SourceMediaItem` con `stream_url`, `duration_s`, `status`; rimosso `file_path`
  interno.
- **Infra**: `deploy/storage/` (MinIO compose + init bucket idempotente + runbook);
  `docker-compose.source.yml` con volume `/data`; `config/source/<env>.env`
  (staging=local, coll/prod=minio); step MinIO in `generate-api.yml`; `seed.py` + `make seed-source`.
- **Test**: 33 verdi (unit mock/sqlite/storage/factory + integration connexion con
  `validate_responses`). `minio>=7.2` in `requirements.txt`.

## 7. Attività odierne (2026-06-05)

- **PR #3** `infrastructure/source → develop` aperta, CI verde, merge manuale eseguito.
- **Deploy staging verificato end-to-end**: dopo merge il container `source` parte correttamente
  (uvicorn, SQLite, storage local); listing, paginazione, filtro `title`, 401 senza chiave e seed
  idempotente validati attraverso il proxy.
- **Fix proxy (inode)**: lo smoke del primo deploy falliva perché il proxy nginx restava agganciato
  al vecchio inode di `nginx.conf` (file tracciato, riscritto da `actions/checkout` a ogni deploy).
  Reload/restart non bastano → aggiunto `--force-recreate` al proxy nel job `deploy`. Dettagli in
  [pipeline.md](pipeline.md).
- **Chiarimento architettura proxy**: due livelli — proxy esterno duckdns (manuale, forwarding
  `ip:port/`) + `mediamgr-proxy` interno (nostro, gestito dalla pipeline).
- **Governance**: rilevato che `Tbc159` è admin, ma la branch protection (1 review su
  develop/coll/main) + l'impossibilità di auto-approvarsi impone il bypass admin. Opzioni in
  [repository-governance.md](repository-governance.md).
- **Documentazione**: riallineamento README ad alto livello + cartella `doc/` (questo insieme).

## 8. Upload `POST /v0/source/media` + allineamento gestione (2026-06-06)

- **Upload server-side multipart**: `POST /v0/source/media` riceve file + metadati, salva i byte
  nello storage e inserisce il record in SQLite (`201`). Duplicati (`object_key`) → `409` via
  `DuplicateObjectKeyError` (astrae `sqlite3.IntegrityError`). Aggiunti `repository.get(id)` e la
  `SourceService.create()`.
- **Pre-signed predisposto** (coll/prod): `SourceService.presigned_upload_url()` su `get_upload_url`
  dello storage (`None` in locale). Endpoint dedicato come step futuro.
- **README di develop** reso domain-agnostic (il commit `505af1a` rimasto fuori dal merge #4) e
  allineamento della **gestione** su `coll`/`main` (PR dedicate: solo doc indipendenti dal codice).
- Test saliti a **43** (unit create/duplicate/get/presigned + integration upload).

## 9. Singolo record + byte (play/download) + governance generalizzata (2026-06-06)

- **`GET /v0/source/media/{id}`**: metadati del singolo record (colma il buco: prima c'era solo il
  listing). `SourceService.get_item()`.
- **`GET /v0/source/media/{id}/content`**: i byte del media. Default **inline** (play),
  `?download=1|true|yes|on` → **allegato** (save) — stessi byte, cambia solo `Content-Disposition`.
  Ibrido: `302` verso URL pre-firmato in coll/prod (client diretto allo storage), **streaming** con
  **Range** (`206`) in dev via `flask.send_file`; `404` se id assente o byte mancanti.
- **`SourceMediaItem`**: rimosso `stream_url`, aggiunti **`content_url`** (inline) e
  **`download_url`** (attachment) — URL relativi verso `/content`. Storage: `get_download_url`
  (attachment) + `local_path`; service `content(id, download)` con `DownloadTarget`.
- **Verifica reale**: upload di un `.m4a` da ~73 MB da macchina esterna → record `id 1`,
  `size_bytes` = dimensione su disco (integrità byte), su DB svuotato (autoincrement resettato).
- **Governance generalizzata**: `repository-governance.md` reso riusabile (owner al posto di
  `Tbc159`, placeholder `$OWNER/$REPO`).
- **Direzione concordata** (prossima iterazione): `source` come dominio **interno**, `/v0/media`
  come **BFF pubblico** che lo media (download via redirect; relay solo in dev). Vedi
  [domains-and-api.md](domains-and-api.md).
- Test a **55** (unit get_item/content + integration metadati + content inline/attachment/Range/404).

## 10. `media` come BFF pubblico, `source` interno (2026-06-06)

- **`media` diventa il BFF pubblico**: endpoint specchio di source su `/v0/media` (`list`, `{id}`,
  `{id}/content[?download]`, `POST` upload). `MediaService` delega via **`SourceGateway`** (httpx,
  rete docker, niente SDK generato) e **ri-mappa** gli URL `/v0/source/…` → `/v0/media/…`.
- **Download — nodo media→source**: media chiama source con `follow_redirects=False`; in coll/prod
  **propaga il `302`** (resta fuori dai byte), in dev **relaia** i byte (limite di dev accettato).
- **`source` diventa interno**: marker `openapi/source/.internal`; `gen-nginx-conf.sh` **non**
  instrada i domini interni (solo rete docker). Smoke della CI aggiornato: health interna via
  `docker exec`, e verifica del listing attraverso il BFF (`/v0/media`).
- Config `SOURCE_INTERNAL_URL` (`config/media/<env>.env`); `MediaItem` rispecchia `SourceMediaItem`.
- Test a **68** (unit BFF remap/relay/passthrough + integration media via gateway fittizio).
- > Nota: il proxy **esterno** (duckdns, manuale) va puntato solo su `/v0/media`; `/v0/source` non
  è più esposto pubblicamente.

### 10.1 Range relay nel BFF (2026-06-07)

- **Problema rilevato** testando lo streaming da Kodi: un `.m4a` **non-faststart** (atomo `moov` in
  fondo) non parte perché il relay del BFF in dev rispondeva sempre con il file intero (`200`,
  niente Range) → il player non riesce a "seekare" per leggere il `moov` → *failed to play*.
- **Fix**: `media` ora **propaga il Range** a `source` (che lo supporta già via `flask.send_file`):
  inoltra l'header `Range`, relaia `206`/`Content-Range` e annuncia `Accept-Ranges: bytes`; gestisce
  anche `HEAD` (via `httpx.head`, senza scaricare i byte). Così i player possono seekare e
  riprodurre i `.m4a` non-faststart anche in dev. Test a **70**.

| Componente | Stato (target dopo merge di questa linea) |
|------------|-------|
| `media` container | **BFF pubblico**: list/`{id}`/`{id}/content`/upload, delega a source |
| `source` container | **interno** (`.internal`): SQLite + storage; non instradato dal proxy pubblico |
| `mediamgr-proxy` | instrada solo i domini **pubblici** (`/v0/media/`) |
| MinIO | non in staging (solo coll/prod) |
| `coll` / `main` | indietro rispetto a develop (vedi [branching-strategy.md](branching-strategy.md)) |

## 11. Collection API condivisibili (`api-collections/`) (2026-06-11)

- **Problema**: importare `openapi/<dom>/api.yaml` direttamente in Bruno/Postman produce endpoint
  errati — `servers: /v0` è **relativo** (l'importer non lo antepone) e i `$ref` verso
  `../shared/components.yaml` sono **esterni** (non risolti).
- **Soluzione**: `tools/build_collections.py` genera un **bundle OpenAPI self-contained per dominio**
  in `api-collections/<dom>.openapi.yaml`: componenti condivisi **inlineati** + `servers:` **assoluti**.
  Discovery dei domini come il resto del progetto; il marker `.internal` rende il bundle interno.
- **Ambienti**: solo **dev** e **coll** (nessun host di produzione nel repo). I domini interni
  (`source`) hanno server di rete docker / port-forward e sono marcati "INTERNO".
- **Target**: `make collections` (rigenera) e `make collections-check` (drift-check, eseguito anche
  in `ci.yaml`). La cartella è versionata su tutti i branch ma resta priva di host prod.

## Prossimi passi suggeriti

- Impostare i secret storage (`MINIO_*`, `STORAGE_*`) nell'Environment `collaudo`, poi promozione
  `develop → coll`.
- Attivare il flusso **pre-signed** come endpoint dedicato in coll/prod (building block già pronti:
  `presigned_upload_url` + `get_upload_url`).
- Governance: deciso *solo documentazione* per ora (nessuna modifica alla branch protection);
  percorso pianificato = **validatore esterno** (account indipendente, vedi
  [repository-governance.md](repository-governance.md)).
- Sostituire i placeholder dei secret (`API_KEY=REPLACE_ME`) con valori reali.
