# Pipeline CI/CD

Approfondimento dei workflow e dell'infrastruttura di deploy. Concetto ad alto livello nel
[README](../README.md).

## Principio guida

**PR aperta = test. Merge = deploy.** Nulla viene rilasciato durante la review; il deploy scatta
solo quando il merge produce un `push` sul branch d'ambiente. Si usa `on: push` (non
`pull_request: closed`) perché cattura *ogni* modifica del branch — merge, squash, hotfix — e
`github.ref_name` indica direttamente l'ambiente target.

## I tre workflow

| Workflow | Trigger | Cosa fa | Deploy? |
|----------|---------|---------|---------|
| `api-draft.yaml` | push su `feature/**`, `draft/**`, `infrastructure/**` | validazione warning-only + `make generate-all` + artifact dello scaffold | no |
| `ci.yaml` | pull_request verso `develop`/`coll`/`main` | `make install` → `validate` (strict) → `generate-all` → `lint` → `test` | no |
| `generate-api.yml` | push su `develop`/`coll`/`main` | `detect` → `verify` → `deploy` selettivo per dominio | **sì** |

> Nota: `ci.yaml` genera lo scaffold "fresh" per provare che la generazione funzioni; `generated/`
> è **gitignored** (rigenerato in CI, mai committato), quindi non esiste un check "diff vuoto" sul
> generato. Lo step di confronto è presente ma commentato.

## `generate-api.yml` in dettaglio

### Job `detect`
- Mappa branch → environment: `develop→staging`, `coll→collaudo`, `main→production`.
- Calcola i **domini impattati** dal diff dei path tra `before` e `sha`:
  - file di un dominio (`openapi/<d>/`, `config/<d>/`, `src/domains/<d>/`, `docker-compose.<d>.yml`)
    → quel dominio;
  - **file condivisi** (`Makefile`, `Dockerfile`, `.dockerignore`, `requirements*.txt`,
    `src/app.py`, `src/client/`, `openapi/config/`, `openapi/shared/`) → **tutti** i domini;
  - primo push / history non raggiungibile → tutti i domini.
- Output: lista JSON di domini → matrix dei job successivi. Lista vuota → niente deploy.

### Job `verify` (runner cloud `ubuntu-latest`)
Gate contract+test **prima** di toccare gli host: `make install` + `generate-<dominio>` + `test`.
Gli host eseguono solo Docker (niente toolchain Java/Python), quindi la validazione pesante gira
qui.

### Job `deploy` (self-hosted runner, label = environment)
`max-parallel: 1` (proxy e rete condivisi sull'host). Passi:
1. **Rete + reverse-proxy**: `docker network create mediamgr` (idempotente) → `gen-nginx-conf.sh`
   → `docker compose ... proxy up -d --force-recreate`.
2. **Object storage** (solo `coll`/`prod`, `if: env.APP_ENV != 'staging'`): avvia MinIO e attende
   l'init bucket one-shot. In staging è saltato (storage locale).
3. **Build & deploy dominio**: `docker compose -f docker-compose.<dominio>.yml up -d --build`
   (build **sull'host**, nessun registry).
4. **Smoke**: `curl /v0/<dominio>/health` con retry; per `source` anche verifica del listing
   (envelope paginato).

I secret (`API_HOST/KEY/SECRET`, `STORAGE_*`, `MINIO_*`) arrivano dall'Environment GitHub del
branch; le variabili non sensibili da `config/<dominio>/<env>.env`.

## Infrastruttura di deploy

### Topologia per host
Ogni ambiente è **un host** con: rete docker `mediamgr`, un container **nginx** (reverse-proxy
interno), un container per dominio, e — in coll/prod — un container **MinIO**.

```
                 (proxy esterno duckdns, manuale)        rete docker interna "mediamgr"
Internet ─► <dom>.duckdns.org ─► ip:port/ ─► mediamgr-proxy ─┬─► /v0/media/  → media:8080
                                              (nginx, NOSTRO) ├─► /v0/source/ → source:8080 ─► minio:9000 (coll/prod)
                                                              └─► ...
```

Due livelli di proxy:
- **esterno** (duckdns → `ip:port/`): forwarding del dominio pubblico, gestito a mano, fuori pipeline;
- **interno** `mediamgr-proxy`: instrada `/v0/<dom>/` ai container, **generato dai domini** e
  **gestito dalla pipeline**.

### Reverse-proxy interno
- `deploy/proxy/gen-nginx-conf.sh` genera `deploy/proxy/nginx.conf` dai domini scoperti
  (zero-hardcoding). Per ogni dominio crea **due** location:
  - `location = /v0/<dom>` (exact match) — evita il 301 automatico di nginx senza slash finale;
  - `location /v0/<dom>/` (prefix) — sottopath (`/health`, listing, ecc.).
- Upstream risolti a runtime via DNS Docker (`set $up_<dom> <dom>:8080; proxy_pass …$request_uri`):
  il proxy parte anche se il container non è ancora su.

### Il fix `--force-recreate` (inode)
`nginx.conf` è bind-mount di un **singolo file** ed è tracciato da git. A ogni deploy
`actions/checkout` lo riscrive con un **nuovo inode**, ma un container nginx già attivo resta
agganciato al **vecchio inode**: `nginx -s reload` e `docker restart` **non** vedono il nuovo
contenuto (stesso container, stesso mount). Risultato: le rotte di un dominio appena aggiunto non
si caricano e lo smoke fallisce (404).

Soluzione: ricreare il container del proxy a ogni deploy
(`docker compose ... up -d --force-recreate`), così rimonta l'inode corrente. nginx riparte in
meno di un secondo; in staging/coll il blip è trascurabile.

### Object storage (coll/prod)
MinIO self-hosted, S3-compatible, in `deploy/storage/`. Avviato dalla pipeline solo in coll/prod;
`:9000` (S3 API) è interno alla rete, `:9001` (Console) è pubblicato per l'ops team. Bucket creato
da un container `minio-init` one-shot idempotente. Runbook: [`deploy/storage/README.md`](../deploy/storage/README.md).
Dettagli d'uso lato dominio in [domains-and-api.md](domains-and-api.md).

## Ambienti, secret e gate

| Environment | Branch | Runner label | Host | Protezioni |
|-------------|--------|--------------|------|------------|
| `staging` | `develop` | `self-hosted,staging` | macchina dev locale | — |
| `collaudo` | `coll` | `self-hosted,collaudo` | LXC Proxmox | — |
| `production` | `main` | `self-hosted,production` | LXC Proxmox | **Required reviewers** (gate sul deploy) |

Ogni environment definisce gli **stessi nomi di secret** con **valori diversi**; il job dichiara
`environment: <nome>` e GitHub risolve i secret giusti, senza `if`/`case` nel workflow.

Secret per ambiente:
- comuni: `API_HOST`, `API_KEY`, `API_SECRET`;
- storage (coll/prod, dominio source): `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`,
  `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`.

Variabili (non sensibili, opzionali): `PROXY_HTTP_PORT`, `STORAGE_BUCKET`, `SOURCE_DATA_PATH`,
`MINIO_DATA_PATH`.

> ⚠️ I self-hosted runner su repo **pubblici** sono rischiosi (una PR potrebbe eseguire codice
> arbitrario sull'host). Qui il deploy parte solo su `push` ai branch protetti, ma è consigliato
> rendere il repo privato. Vedi [repository-governance.md](repository-governance.md).
