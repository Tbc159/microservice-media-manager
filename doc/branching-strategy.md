# Strategia di branching

Approfondimento del modello di branching. Sintesi ad alto livello nel [README](../README.md).

## Modello: feature effimere + branch d'ambiente persistenti

Due dimensioni **ortogonali**:
- il **branch** decide *in quale ambiente* si rilascia;
- i **path cambiati** decidono *quali domini* (ri)deployare.

| Branch | Tipo | Ambiente | Trigger CI/CD |
|--------|------|----------|---------------|
| `feature/*` | effimero | — (locale / artifact) | `api-draft.yaml` (scaffold rapido) |
| `infrastructure/*` | effimero | — (locale / artifact) | `api-draft.yaml` |
| `develop` | persistente | **staging** | `generate-api.yml` (genera + deploya) |
| `coll` | persistente | **collaudo / UAT** | `generate-api.yml` |
| `main` | persistente | **production** | `generate-api.yml` + gate reviewers |

Ogni branch d'ambiente **è** la fonte di verità di ciò che è effettivamente deployato in
quell'ambiente (modello environment-branch / GitOps).

## `feature/*` vs `infrastructure/*`

Stesso flusso tecnico (PR → ambiente), semantica diversa:

- **`feature/*`** — evoluzione funzionale di un dominio applicativo (es. `feature/list-all-media`):
  nuovi endpoint, modifiche al contratto OAS, logica di business.
- **`infrastructure/*`** — componenti di supporto e fondamenta del sistema (es.
  `infrastructure/source`, `infrastructure/docs`): nuovi domini-bridge, storage, persistenza,
  pipeline, documentazione. Frequenza di aggiornamento bassa (1-2 volte/mese).

Entrambi i prefissi attivano `api-draft.yaml` (scaffold + artifact). La distinzione è
**organizzativa**: separare ciò che cambia spesso (feature) da ciò che cambia di rado e tocca
le fondamenta (infrastructure), per review e tracciabilità più chiare.

## Deploy selettivo per dominio

Il job `detect` di `generate-api.yml` calcola i domini impattati dal **diff dei path**, non dal
nome del branch. Conseguenza: un push su `develop` che tocca solo `openapi/media/**` ridistribuisce
**solo** il container `media` in staging. Un cambio a file condivisi
(`Makefile`, `Dockerfile`, `requirements*.txt`, `src/app.py`, `src/client/`, `openapi/config/`,
`openapi/shared/`) ridistribuisce **tutti** i domini. Dettaglio in [pipeline.md](pipeline.md).

## Promozione tra ambienti

L'avanzamento verso la produzione avviene **per PR tra branch d'ambiente**, non per merge diretti:

```
feature/*  --PR-->  develop  --PR-->  coll  --PR-->  main
infra/*    --PR-->  (staging)        (collaudo)    (production)
```

Ogni salto ripassa dal gate della CI (`ci.yaml`); l'ultimo salto verso `main` aggiunge
l'approvazione manuale del deploy (Required reviewers sull'environment `production`).

**Regola:** PR aperta = solo test CI (nessun deploy). Merge = push sul branch d'ambiente = deploy.

## Stato corrente dei branch

Lo stato puntuale — quali domini sono deployati in ciascun ambiente e le promozioni in sospeso —
cambia nel tempo e vive nel [changelog](changelog.md), non qui: questo documento descrive il
**modello** di branching, valido a prescindere dallo stato di deploy.

## Branch protection e review

Tutti e tre i branch d'ambiente richiedono **1 review approvante** prima del merge. Poiché GitHub
non consente di approvare le proprie PR, in un repo con un solo collaboratore questo costringe al
bypass admin. Analisi e soluzioni (relax delle regole / validatore esterno) in
[repository-governance.md](repository-governance.md).
