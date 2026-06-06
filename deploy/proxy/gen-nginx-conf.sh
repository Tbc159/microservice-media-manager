#!/usr/bin/env bash
# Genera deploy/proxy/nginx.conf dai domini scoperti (openapi/<dominio>/api.yaml).
# Zero-hardcoding: aggiungere openapi/social/api.yaml -> la rotta /v0/social/ compare da sola.
# Eseguibile in locale (`make proxy-config`) e nella CI prima di avviare il proxy.
set -euo pipefail

# Root del repo (questo script vive in deploy/proxy/)
cd "$(dirname "$0")/../.."
OUT="deploy/proxy/nginx.conf"

DOMAINS=$(for d in openapi/*/; do if [ -f "$d/api.yaml" ]; then basename "$d"; fi; done | sort -u)
if [ -z "$DOMAINS" ]; then
  echo "Nessun dominio trovato in openapi/*/api.yaml" >&2
  exit 1
fi

# Domini PUBBLICI = senza marker openapi/<dom>/.internal. I domini "interni" (es. source,
# mediato dal BFF media) NON vengono instradati dal proxy: restano raggiungibili solo sulla
# rete docker 'mediamgr' per le chiamate service-to-service.
PUBLIC_DOMAINS=""
for d in $DOMAINS; do
  [ -f "openapi/$d/.internal" ] || PUBLIC_DOMAINS="$PUBLIC_DOMAINS $d"
done
PUBLIC_DOMAINS=$(echo $PUBLIC_DOMAINS | xargs)

{
  echo "# === FILE GENERATO da deploy/proxy/gen-nginx-conf.sh — non editare a mano. ==="
  echo "# Reverse-proxy per host: instrada /v0/<dominio>/ al container <dominio>:8080"
  echo "# sulla rete docker interna 'mediamgr' (risoluzione nomi a runtime via DNS Docker)."
  echo "server {"
  echo "    listen 80;"
  echo "    server_name _;"
  echo "    client_max_body_size 300M;"
  echo "    resolver 127.0.0.11 valid=10s;   # DNS interno di Docker"
  echo ""
  for dom in $PUBLIC_DOMAINS; do
    # nome variabile nginx: solo [A-Za-z0-9_]
    var=$(printf '%s' "$dom" | tr -c 'A-Za-z0-9' '_')
    # Exact match: evita il 301 automatico di nginx per proxy_pass senza slash finale
    echo "    location = /v0/$dom {"
    echo "        set \$up_$var $dom:8080;"
    echo "        proxy_pass http://\$up_$var\$request_uri;"
    echo "        proxy_set_header Host \$host;"
    echo "        proxy_set_header X-Real-IP \$remote_addr;"
    echo "        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "        proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "    }"
    echo ""
    # Prefix match: /v0/<dom>/health, /v0/<dom>/<id>, ecc.
    echo "    location /v0/$dom/ {"
    echo "        set \$up_$var $dom:8080;"
    echo "        proxy_pass http://\$up_$var\$request_uri;"
    echo "        proxy_set_header Host \$host;"
    echo "        proxy_set_header X-Real-IP \$remote_addr;"
    echo "        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "        proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "        proxy_read_timeout 300;"
    echo "        proxy_connect_timeout 300;"
    echo "        proxy_send_timeout 300;"
    echo "    }"
    echo ""
  done
  echo "    location = / {"
  echo "        default_type text/plain;"
  echo "        return 200 \"media-manager reverse-proxy. domini pubblici: $PUBLIC_DOMAINS\\n\";"
  echo "    }"
  echo "    location / { return 404; }"
  echo "}"
} > "$OUT"

echo "Generato $OUT per domini pubblici: $PUBLIC_DOMAINS"
