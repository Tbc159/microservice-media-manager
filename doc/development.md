# Sviluppo condiviso

Approfondimento del patto di sviluppo. Concetti base nel [README](../README.md).

## Contract-first / API-first

Il **contratto OpenAPI 3.0** è l'unica fonte di verità di ogni dominio. Si progetta prima
l'interfaccia (`openapi/<dominio>/api.yaml`), poi la si implementa. Finché è in `feature/*` /
`infrastructure/*` è un **draft** modificabile; diventa **confermato** quando entra in `develop`
tramite PR approvata.

Conseguenze:
- il codice di scaffold (server stub + SDK client) è **generato** dal contratto, non scritto a mano;
- generato e custom vivono in directory **fisicamente separate**;
- i consumer si integrano contro un **mock guidato dal contratto** prima che esista
  l'implementazione.

## Generato vs custom: due mondi separati

```
generated/<dominio>/{server,client}   ← rigenerato, gitignored, MAI editato a mano
src/                                   ← il NOSTRO codice, la fonte di verità della logica
```

- `generated/` è **gitignored**: rigenerato in CI con `make generate-all`, mai committato. Si può
  fare `rm -rf generated/` in sicurezza.
- A runtime **il server non importa `generated/`**: connexion carica la spec OAS e risolve le
  `operationId` verso i controller in `src/` (vedi sotto). Il generato serve come
  scaffold/validazione e come SDK client.
- `.openapi-generator-ignore` è una cintura di sicurezza ulteriore per la rigenerazione.

## Wiring multi-dominio e `base_path = /v0`

`src/app.py` è il wiring unico. Per ogni dominio scoperto monta la spec sotto **`base_path=/v0`**
e risolve le `operationId` verso `src.domains.<dominio>.controllers` (RelativeResolver).

```python
# src/app.py (estratto)
app = connexion.FlaskApp(__name__, specification_dir=str(OPENAPI_DIR))
for domain in domains:
    app.add_api(
        f"{domain}/api.yaml",
        base_path="/v0",
        resolver=connexion.resolver.RelativeResolver(f"src.domains.{domain}.controllers"),
        strict_validation=True,
        validate_responses=True,
    )
```

Le path nelle spec sono **relative** e includono il nome del dominio (`/media`, `/media/health`,
`/source/media`): con `base_path=/v0` l'URL effettivo è `/v0/media`, `/v0/source/media`, ecc. Il
reverse-proxy interno instrada `/v0/<dom>/` → container.

Due modalità di esecuzione:
- **locale**: nessuna env var → monta **tutti** i domini in un processo (`python -m src.app`);
- **container**: `DOMAIN=<dominio>` → monta **solo** quel dominio (un microservizio per container).

## Componenti OAS condivisi

`openapi/shared/components.yaml` raccoglie ciò che è comune ai domini, referenziato via `$ref`
relativo (connexion 3.x risolve i `$ref` esterni rispetto alla directory della spec):

| Componente | Tipo | Uso |
|------------|------|-----|
| `ApiKeyAuth` | securityScheme | header `X-API-Key`, handler `src.security.api_key_info` |
| `Health` | schema | risposta di `/health` |
| `Error` | schema | corpo errori (`detail`) |
| `PaginationMeta` | schema | `page`, `page_size`, `total`, `total_pages` |

Esempio: in `openapi/source/api.yaml`,
`$ref: '../shared/components.yaml#/components/schemas/PaginationMeta'`.

## Sicurezza: API key

Gli endpoint protetti dichiarano `security: [ApiKeyAuth: []]`. Il client invia l'header
`X-API-Key`. La validazione è in `src/security.py` (`api_key_info`):
- se la env var `API_KEY` è impostata nel container → la chiave deve combaciare, altrimenti 401;
- se `API_KEY` è vuota (dev/mock) → qualunque chiave non vuota è accettata.

In CI/CD il valore arriva dal secret `API_KEY` dell'Environment GitHub del branch.

## Sviluppo locale e mock

La CI invoca gli **stessi target** del `Makefile` usati in locale: niente divergenza
"funziona da me". La versione di `openapi-generator` è **pinnata** (7.5.0) per output identico.

| Comando | Effetto |
|---------|---------|
| `make install` | dipendenze (runtime + dev) |
| `make domains` | elenca i domini rilevati |
| `make validate` | valida l'OAS di ogni dominio |
| `make generate-all` | valida + genera server+client per tutti i domini |
| `make generate-<dominio>` | genera il solo dominio indicato |
| `make mock` | avvia l'app con MockResolver (risposte = `examples` dell'OAS) |
| `make test` | esegue i test |
| `make lint` | ruff su `src/` e `tests/` |
| `make proxy-config` | rigenera `deploy/proxy/nginx.conf` dai domini |
| `make seed-source` | inserisce dati demo nel dominio source (dentro il container) |
| `make clean` | rimuove `generated/` |

```bash
python -m src.app                 # tutti i domini, :8080
DOMAIN=media python -m src.app    # solo media
MOCK=1 python -m src.app          # risposte dagli examples dell'OAS
```

## Strategia di test

Piramide: i livelli economici filtrano presto.

| Livello | Dove | Scopo |
|---------|------|-------|
| Validazione OAS | ogni push / PR | contratto ben formato |
| Lint + Unit | CI (PR) | logica isolata, niente rete |
| Integration (connexion `TestClient`) | CI (PR) | catena reale routing→security→controller→service, con `validate_responses` |
| Contract test (schemathesis) | predisposto (`tests/contract/`) | l'implementazione rispetta lo schema |
| Smoke + health/listing | ogni deploy | il servizio è vivo in ambiente |

I test vivono in `tests/{unit,integration,contract}/`. Esempi reali in
[domains-and-api.md](domains-and-api.md).

## Convenzioni di codice

- Logica custom **solo** in `src/domains/<dominio>/`; mai in `generated/`.
- Controller **thin**: traducono input → service → `(body, status)`. Niente business logic.
- Dipendenze iniettate via **factory** (composition root), non istanziate nei controller — facilita
  il test e lo scambio di implementazioni (es. mock ↔ SQLite, FS ↔ MinIO).
- Commit in italiano, prefissi convenzionali (`feat`, `fix`, `docs`, `ci`, `refactor`).

## Definition of Done

- [ ] OAS aggiornato e valido in modalità *strict* (`make validate`).
- [ ] `make generate-all` completa senza errori.
- [ ] Logica in `src/`, mai in `generated/`.
- [ ] Unit + integration test verdi (`make test`), lint pulito (`make lint`).
- [ ] PR approvata da almeno un validatore (vedi [repository-governance.md](repository-governance.md)).
- [ ] Deploy in staging supera smoke/health.
- [ ] Documentazione (README o `doc/`) aggiornata se cambia il processo o l'API.
