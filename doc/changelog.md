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

## Stato runtime attuale (staging)

| Componente | Stato |
|------------|-------|
| `media` container | attivo, `GET /v0/media` (statico) |
| `source` container | attivo, `GET /v0/source/media` (SQLite + storage local) |
| `mediamgr-proxy` | attivo, rotte `/v0/media/`, `/v0/source/` |
| MinIO | non in staging (solo coll/prod) |
| `coll` / `main` | indietro rispetto a develop (vedi [branching-strategy.md](branching-strategy.md)) |

## Prossimi passi suggeriti

- Impostare i secret storage (`MINIO_*`, `STORAGE_*`) nell'Environment `collaudo`, poi promozione
  `develop → coll`.
- Implementare `POST /v0/source/media` (upload) sfruttando `put_object`/`get_upload_url` già
  predisposti.
- Decidere il modello di governance (relax develop/coll + validatore su main).
- Sostituire i placeholder dei secret (`API_KEY=REPLACE_ME`) con valori reali.
