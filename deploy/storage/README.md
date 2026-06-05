# Object storage (MinIO) — runbook

Storage S3-compatible **self-hosted** per gli ambienti `collaudo` e `production`.
In `staging`/dev NON viene avviato: là i domini usano `STORAGE_BACKEND=local` (file su FS).

## Perché MinIO
- **Zero costi di licenza**, self-hosted, gestibile dal team operations.
- **API S3 al 100%**: lo stesso codice gira su MinIO, Amazon S3, Cloudflare R2, Backblaze B2.
  Migrare a un servizio a pagamento = cambiare 3 variabili d'ambiente, zero modifiche al codice.

## Interfacce
| Porta | Cosa | Esposizione |
|-------|------|-------------|
| `9000` | S3 API | solo rete docker interna `mediamgr` (i container la usano via DNS `minio:9000`) |
| `9001` | Console web | pubblicata sull'host per l'ops team |

## Variabili (secret negli Environment GitHub)
| Variabile | Dove | Note |
|-----------|------|------|
| `MINIO_ROOT_USER` | secret env | utente root MinIO |
| `MINIO_ROOT_PASSWORD` | secret env | password root MinIO (>= 8 char) |
| `MINIO_DATA_PATH` | var env | path host del volume dati (default `./data/minio`) |
| `STORAGE_BUCKET` | var env | nome bucket (default `media-source`) |

Il container del dominio (`source`) autentica con `STORAGE_ACCESS_KEY`/`STORAGE_SECRET_KEY`.
In setup base coincidono con root user/password; in hardening prod si crea un service account
dedicato con `mc admin user svcacct add` e policy ristretta al solo bucket.

## Avvio manuale (replica/debug)
```bash
export MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD=...
docker network create mediamgr 2>/dev/null || true
docker compose -f deploy/storage/docker-compose.storage.yml up -d
# init manuale dall'host (se serve rifarlo):
MINIO_ENDPOINT=http://localhost:9000 bash deploy/storage/init-minio.sh
```

## Verifica
```bash
docker compose -f deploy/storage/docker-compose.storage.yml ps
docker logs minio-init          # deve terminare con "Bucket privato pronto"
# Console: http://<host>:9001
mc ls local/media-source        # lista oggetti (con alias configurato)
```

## Migrazione a S3/R2 (futuro, se budget)
1. Crea bucket sul provider.
2. Aggiorna gli env del dominio: `STORAGE_ENDPOINT`, `STORAGE_SECURE=true`,
   `STORAGE_ACCESS_KEY`/`STORAGE_SECRET_KEY` con le credenziali del provider.
3. Rimuovi `deploy/storage` dalla pipeline. Il codice non cambia.
