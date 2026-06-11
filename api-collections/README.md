# api-collections — collection API condivisibili

Bundle **OpenAPI self-contained**, uno per dominio, **generati** dai contratti
`openapi/<dominio>/api.yaml`. Servono per testare le API da qualsiasi client
(Bruno, Postman, Insomnia, Swagger UI, …) senza incappare nei due problemi
dell'import diretto di `api.yaml`:

1. `servers: /v0` è **relativo** → gli importer non lo antepongono e gli endpoint
   escono "nudi" (`/media` invece di `…/v0/media`). Qui i `servers:` sono **assoluti**.
2. i `$ref` verso `../shared/components.yaml` sono **esterni** → molti importer non li
   risolvono. Qui i componenti condivisi (`ApiKeyAuth`, `Health`, `Error`,
   `PaginationMeta`) sono **inlineati**.

## File

| File | Dominio | Esposizione |
|------|---------|-------------|
| `media.openapi.yaml` | `media` | **pubblico** (reverse-proxy): server dev + coll |
| `source.openapi.yaml` | `source` | **interno** (`.internal`): server rete docker / port-forward |

> Niente host di **produzione**: i bundle contengono solo gli ambienti **dev** e **coll**.

## Come si rigenerano (non si editano a mano)

La fonte di verità resta `openapi/<dominio>/api.yaml`. Dopo ogni modifica al contratto:

```bash
make collections          # rigenera tutti i bundle
make collections-check    # verifica drift (lo usa anche la CI)
```

Il generatore è `tools/build_collections.py` e scopre i domini come il resto del
progetto (un `openapi/<dom>/api.yaml` = un dominio; il marker `.internal` lo rende interno).

## Import in Bruno (o altri tool)

1. **Import Collection → OpenAPI V3** e scegli `media.openapi.yaml`.
2. Seleziona il **server**: `dev` (default, `http://mediamanager-dev.duckdns.org/v0`)
   oppure `coll` (imposta la variabile `coll_host` con l'host di collaudo).
3. Imposta l'**auth**: header `X-API-Key`. In dev va bene qualunque valore non vuoto
   (es. `REPLACE_ME`); negli altri ambienti deve combaciare col secret `API_KEY`.

Endpoint che ottieni (dominio `media`):

- `GET  /media?type=audio/m4a` — lista paginata
- `GET  /media/{id}` — metadati del singolo media
- `GET  /media/{id}/content[?download=1]` — byte (play inline / allegato), supporta `Range`
- `POST /media` — upload multipart
- `GET  /media/health` — health

> **`source` è interno**: `source.openapi.yaml` è incluso per completezza ma NON è
> raggiungibile dall'esterno. Lo si prova solo dentro la rete docker `mediamgr` o via
> port-forward locale verso il container `source`. Il contratto pubblico è solo `media`.
