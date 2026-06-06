# microservice-media-manager

> **Patto di sviluppo, test e rilascio — approccio Contract-First (OAS 3.0)**
>
> Documento condiviso a cui aderisce chiunque entri nel progetto, in qualunque ruolo. Definisce il
> **processo**: come si progetta, genera, testa e rilascia un microservizio e quali regole governano
> il passaggio tra ambienti.

> ℹ️ **Questo è un branch d'ambiente.** Il README e i documenti in `doc/` coprono la **gestione**
> (processo), universale su ogni branch. L'architettura applicativa e le **API** dipendono da cosa è
> deployato in questo ambiente e sono documentate sul branch dove le funzionalità vivono (a partire
> da `develop`).

## Cos'è

Microservizio Python **contract-first** e **multi-dominio**: ogni dominio
(`openapi/<dominio>/api.yaml`) è una spec OpenAPI 3.0 — l'unica fonte di verità — da cui si
**genera** lo scaffold, tenuto separato dalla logica custom. Ogni dominio è un microservizio
deployabile in modo indipendente.

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [doc/branching-strategy.md](doc/branching-strategy.md) | modello di branching e promozione tra ambienti |
| [doc/repository-governance.md](doc/repository-governance.md) | permessi, review, come aggiungere un validatore esterno |

> Gli approfondimenti su pipeline di dettaglio, sviluppo e API (specifici delle funzionalità
> deployate) vivono sul branch `develop`.

## Sviluppo condiviso — concetti

- **Contract-first.** Prima l'OAS (`openapi/<dominio>/api.yaml`), poi l'implementazione. Il contratto
  è draft in `feature/*`/`infrastructure/*`, **confermato** quando entra in `develop`.
- **Generato vs custom, separati.** Lo scaffold (`generated/`, gitignored) è rigenerabile e non si
  edita mai a mano; la logica vive in `src/`.
- **Controller thin + dependency injection.** Le dipendenze sono assemblate da una factory, così si
  scambiano implementazioni senza toccare la logica.

| Ruolo | Cosa fa |
|-------|---------|
| **Sviluppatore** | definisce/aggiorna l'OAS, implementa i controller in `src/`, scrive i test |
| **Validatore** | revisiona e **approva** la PR verso un branch d'ambiente |
| **Maintainer** | gestisce branch protection, environment, secret, gate di produzione |

Principio: **nessun codice raggiunge un ambiente senza un doppio via libera** — CI verde +
approvazione del validatore. Vedi [doc/repository-governance.md](doc/repository-governance.md).

## Gestione della pipeline — concetto

**PR aperta = test. Merge = deploy.** Il **branch** decide l'ambiente; i **path cambiati** decidono
quali domini (ri)deployare. Tre workflow: `api-draft` (scaffold su branch effimeri), `ci` (su PR:
validate + lint + test, **nessun deploy**), `generate-api` (su push ai branch d'ambiente: rileva i
domini impattati → verifica → deploy selettivo). Dettaglio sul branch `develop`.

| Branch | Ambiente |
|--------|----------|
| `feature/*`, `infrastructure/*` | — (locale / artifact) |
| `develop` | staging |
| `coll` | collaudo / UAT |
| `main` | production (gate reviewers) |

Vedi [doc/branching-strategy.md](doc/branching-strategy.md).

## Quick start

```bash
make install            # dipendenze
make domains            # elenca i domini rilevati
make validate           # valida ogni openapi/<dominio>/api.yaml
make generate-all       # valida + genera server+client per tutti i domini
make test               # test
make lint               # lint
```

---

*Documento vivente: ogni modifica al processo passa da una PR, soggetta alle stesse regole di
revisione del codice.*
