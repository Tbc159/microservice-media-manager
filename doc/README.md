# Documentazione di approfondimento

Approfondimenti tematici del progetto. Il [README principale](../README.md) dà i concetti ad alto
livello; qui si entra nel dettaglio.

| Documento | Contenuto |
|-----------|-----------|
| [branching-strategy.md](branching-strategy.md) | Modello di branching, `feature/*` vs `infrastructure/*`, promozione tra ambienti, stato dei branch |
| [pipeline.md](pipeline.md) | I tre workflow, `detect/verify/deploy`, infrastruttura (self-hosted runner, proxy a due livelli, fix inode, MinIO), ambienti e secret |
| [development.md](development.md) | Patto di sviluppo: contract-first, generato vs custom, `base_path=/v0`, security, mock, test, convenzioni, Definition of Done |
| [domains-and-api.md](domains-and-api.md) | Documentazione API per dominio (`media`, `source`), architettura source (SQLite/storage/Clean Architecture), implementazioni attuali/future |
| [repository-governance.md](repository-governance.md) | Permessi, branch protection, perché serve la "forzatura", come aggiungere un validatore esterno |
| [changelog.md](changelog.md) | Tutto ciò che è stato implementato/predisposto dall'ultimo README a oggi |

Runbook operativi (fuori da `doc/`):
- [`deploy/README.md`](../deploy/README.md) — deploy su host, self-hosted runner, reverse-proxy.
- [`deploy/storage/README.md`](../deploy/storage/README.md) — object storage MinIO (coll/prod).
