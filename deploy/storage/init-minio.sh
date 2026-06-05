#!/usr/bin/env sh
# Inizializza il bucket MinIO. Idempotente: rieseguibile a ogni deploy senza effetti.
# Usato sia dal container one-shot 'minio-init' (automazione CI) sia a mano dall'ops team:
#   MINIO_ENDPOINT=http://localhost:9000 ./init-minio.sh
set -eu

ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
BUCKET="${STORAGE_BUCKET:-media-source}"

# Attesa che MinIO sia pronto (il container puo' partire prima del server).
echo ">>> Attendo MinIO su $ENDPOINT ..."
i=0
until mc alias set local "$ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERRORE: MinIO non raggiungibile dopo 60s" >&2
    exit 1
  fi
  sleep 2
done

# Crea il bucket se non esiste e lo rende privato (accesso solo via pre-signed URL).
mc mb --ignore-existing "local/$BUCKET"
mc anonymous set none "local/$BUCKET"

echo ">>> MinIO inizializzato. Bucket privato pronto: $BUCKET"
