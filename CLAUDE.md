# microservice-media-manager — Contesto di progetto per Claude Code

## Cos'è questo progetto
Microservizio Python **contract-first / API-first** e **multi-dominio**: ogni dominio
(es. `media`, `social`) ha la propria spec OAS 3.0 in `openapi/<dominio>/api.yaml`, che è
l'unica fonte di verità per quel dominio. Il codice viene *generato* dal contratto e tenuto
separato dalla logica custom. Ogni dominio è un microservizio deployabile in modo indipendente.

## Decisioni architetturali chiave

### Multi-dominio con discovery (zero hardcoding)
- Un dominio = una cartella `openapi/<dominio>/api.yaml`. Aggiungere `openapi/social/api.yaml`
  crea il dominio `social` **senza toccare Makefile né CI**.
- Il `Makefile` scopre i domini con `DOMAINS := $(notdir ... wildcard openapi/*/api.yaml)`.
- Ogni dominio genera il proprio stub: `generated/<dominio>/{server,client}`.

### Separazione fisica generato / custom
- `generated/` → MAI editato a mano. Rigenerabile, in `.gitignore`.
- `src/` → logica custom. `src/domains/<dominio>/{controllers,services}`.
- A runtime il **server NON usa `generated/`**: connexion carica la spec OAS e risolve verso
  i controller in `src/`. Il generato serve come scaffold/validazione e per l'SDK client.

### Server: connexion + base_path per dominio
`src/app.py` è il wiring unico. Per ogni dominio monta la spec sotto `base_path=/<dominio>` e
risolve le `operationId` verso `src.domains.<dominio>.controllers` (RelativeResolver).
- **Locale (sviluppo)**: nessuna env var → monta TUTTI i domini in un processo (`python -m src.app`).
- **Container (dev/coll/prod)**: `DOMAIN=media` → monta SOLO quel dominio.
- Le path nelle spec sono **relative** (`/health`, `/items`): il prefisso `/media` è il base_path.

```bash
python -m src.app                 # tutti i domini, :8080 (dev veloce)
DOMAIN=media python -m src.app    # solo media
MOCK=1 python -m src.app          # risposte dagli examples dell'OAS
```

### Reverse-proxy: prefisso di dominio mantenuto
nginx instrada `host/media/*` → container media (`10.1.3.10:3000`), `host/social/*` →
container social (`10.1.3.10:3010`). Usa `proxy_pass http://host:porta;` **senza URI finale**:
il prefisso `/media` NON viene strisciato e arriva al container, che serve a `base_path=/media`.

### Client: factory unico per dominio
`src/client/auth.py` è il SOLO punto di costruzione degli `ApiClient` generati.
`build_api_client(domain)` importa lazy il package `<dominio>_client` e legge
`API_HOST`, `API_KEY`, `API_SECRET` da env var.

### Container: un Dockerfile parametrico, un compose per dominio
- **`Dockerfile`** unico con `ARG DOMAIN` → una sola ricetta, nessuna ambiguità di versioni.
- **`docker-compose.<dominio>.yml`** per dominio = unità deployabile. La CI rideploya SOLO il
  compose del dominio cambiato.

### openapi-generator: versione pinnata
Generator version **7.5.0** (JAR cachato in `.cache/`). Usare sempre `make generate-all`
(tutti i domini) o `make generate-<dominio>` (uno solo) — mai il jar direttamente.

## Branching strategy

| Branch | Ambiente | Trigger CI/CD |
|--------|----------|---------------|
| `feature/*` | locale / artifact | `api-draft.yaml` (scaffold rapido) |
| `develop` | staging | `generate-api.yml` (genera + deploya) |
| `coll` | collaudo/UAT | `generate-api.yml` |
| `main` | production | `generate-api.yml` + gate reviewers |

**Due dimensioni ortogonali:** il **branch** decide l'ambiente; i **path cambiati** decidono
quali domini (ri)deployare. Push su `develop` che tocca solo `openapi/media/**` → deploy del
solo container media in staging.

**Regola:** PR aperta = CI test (nessun deploy). Merge = push su branch ambiente = deploy.

## Workflow GitHub Actions (`.github/workflows/`)

- `api-draft.yaml` — push su `feature/**`: valida warning-only, genera scaffold (tutti i domini), artifact.
- `ci.yaml` — pull_request verso env branches: validazione OAS strict, generate-all, lint, test. NO deploy.
- `generate-api.yml` — push su `[develop, coll, main]`: job `detect` calcola i domini cambiati →
  matrix `build-deploy` che builda+deploya SOLO quei domini nell'environment del branch.
  File condivisi (`Makefile`, `Dockerfile`, `requirements*.txt`, `src/app.py`, `src/client/`,
  `openapi/config/`, `openapi/shared/`) → rideploya tutti i domini.

## Comandi Makefile principali

```bash
make install            # dipendenze
make domains            # elenca i domini rilevati
make validate           # valida ogni openapi/<dominio>/api.yaml
make generate-all       # valida + genera server+client per tutti i domini
make generate-media     # genera il solo dominio media
make test               # pytest su tests/
make lint               # ruff su src/ e tests/
make clean              # rm -rf generated/ (sicuro)
make mock               # avvia l'app con MockResolver (tutti i domini)
```

## Stato attuale del progetto

### Fatto
- Layout multi-dominio con discovery (Makefile, `src/app.py` con base_path).
- Dominio `media` migrato: `openapi/media/api.yaml` (endpoint `/health`, `/items`), controller e service.
- Dockerfile parametrico, `docker-compose.media.yml`, config per-dominio (`config/media/*.env`).
- Tre workflow CI/CD; `generate-api.yml` con matrix selettiva per dominio.
- Repo su GitHub (owner `Tbc159`), branch `main`/`develop`/`coll`/`feature/list-all-media`.

### Da fare / prossimi passi
1. **Sostituire i secret placeholder** negli Environment GitHub (API_HOST, API_KEY, API_SECRET).
2. **Implementare lo step di deploy reale** in `generate-api.yml` (ssh + `docker compose up`).
3. **Scegliere e aggiungere la licenza**: PolyForm Noncommercial 1.0.0.
4. **Aggiungere il dominio `social`**: `openapi/social/api.yaml` + `src/domains/social/` + `docker-compose.social.yml`.
5. **Espandere il dominio media**: `upload-new-media`, `delete-media` (nuovi path in `openapi/media/api.yaml`).

## Struttura file (aggiornata)
```
openapi/<dominio>/api.yaml        ← EDITARE QUI per il contratto di un dominio (path relative)
openapi/shared/                   ← componenti OAS condivisi (modifica → rebuild di tutti)
openapi/config/                   ← config generator (packageName impostato per-dominio dal Makefile)
src/app.py                        ← wiring multi-dominio (base_path, discovery)
src/domains/<dominio>/controllers ← EDITARE QUI per logica server custom
src/domains/<dominio>/services    ← EDITARE QUI per business logic
src/client/auth.py                ← EDITARE QUI per autenticazione client
config/<dominio>/<env>.env        ← variabili NON sensibili per ambiente
Dockerfile                        ← unico, parametrico (ARG DOMAIN)
docker-compose.<dominio>.yml      ← unità deployabile per dominio
tests/unit/                       ← test unitari su src/
generated/<dominio>/              ← NON EDITARE (rigenerato da make generate-all)
```

## Riferimenti
- README completo: `README.md` (patto di sviluppo condiviso)
- OAS spec: `openapi/<dominio>/api.yaml`
- Documentazione processo CI/CD: sezione 9 del README
