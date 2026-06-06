# Documentazione di approfondimento

Approfondimenti tematici del progetto. Il [README principale](../README.md) dà i concetti ad alto
livello; qui si entra nel dettaglio.

I documenti si dividono in due famiglie:

## Gestione del progetto (universale)

Descrivono il **processo**: validi su ogni branch a prescindere dai domini deployati. Allineati e
identici su `develop`, `coll`, `main`.

| Documento | Contenuto |
|-----------|-----------|
| [branching-strategy.md](branching-strategy.md) | Modello di branching, `feature/*` vs `infrastructure/*`, promozione tra ambienti |
| [pipeline.md](pipeline.md) | I tre workflow, `detect/verify/deploy`, infrastruttura (self-hosted runner, proxy a due livelli, fix inode, object storage), ambienti e secret |
| [development.md](development.md) | Patto di sviluppo: contract-first, generato vs custom, `base_path=/v0`, security, mock, test, convenzioni, Definition of Done |
| [repository-governance.md](repository-governance.md) | Permessi, branch protection, perché serve la "forzatura", come aggiungere un validatore esterno |

## Stato e funzionalità (specifici dell'ambiente)

Riflettono **cosa** è deployato nel branch: possono variare tra ambienti.

| Documento | Contenuto |
|-----------|-----------|
| [domains-and-api.md](domains-and-api.md) | API per dominio e architettura dei domini presenti nel branch, implementazioni attuali/future |
| [api-reference.md](api-reference.md) | Riferimento endpoint **pubblici (esterni)** vs **interni** e loro utilizzo (esempi `curl`) |
| [changelog.md](changelog.md) | Storico: cosa è stato implementato/predisposto dall'ultimo README a oggi |

Runbook operativi (fuori da `doc/`):
- [`deploy/README.md`](../deploy/README.md) — deploy su host, self-hosted runner, reverse-proxy.
- [`deploy/storage/README.md`](../deploy/storage/README.md) — object storage MinIO (coll/prod).
