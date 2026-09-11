#!/usr/bin/env bash
# Genera deploy/proxy/nginx.conf dai domini scoperti (openapi/<dominio>/api.yaml).
# Zero-hardcoding: aggiungere openapi/social/api.yaml -> la rotta /v0/social/ compare da sola.
# Eseguibile in locale (`make proxy-config`) e nella CI prima di avviare il proxy.
#
# TLS (opt-in, default OFF): con PROXY_TLS=1 genera un server 443 con i certificati e un
# server 80 che redirige a https (mantenendo il path ACME per i rinnovi http-01). Con TLS
# OFF resta il comportamento storico (tutto su :80), cosi' lo sviluppo locale e gli host
# senza certificato continuano a funzionare.
#
# NB: il CORS NON e' qui. Vive nell'app (src/cors.py) sui soli domini pubblici, per evitare
# intestazioni duplicate (che romperebbero il preflight) e per poterlo testare. Non aggiungere
# header Access-Control-* in questo file.
set -euo pipefail

cd "$(dirname "$0")/../.."
OUT="deploy/proxy/nginx.conf"

PROXY_TLS="${PROXY_TLS:-0}"
PROXY_SERVER_NAME="${PROXY_SERVER_NAME:-_}"
PROXY_TLS_CERT="${PROXY_TLS_CERT:-/etc/nginx/certs/fullchain.pem}"
PROXY_TLS_KEY="${PROXY_TLS_KEY:-/etc/nginx/certs/privkey.pem}"

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

# Emette il corpo comune di un server (limiti, resolver e le location per dominio).
emit_server_body() {
  echo "    client_max_body_size 300M;"
  echo "    resolver 127.0.0.11 valid=10s;   # DNS interno di Docker"
  echo ""
  for dom in $PUBLIC_DOMAINS; do
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
}

{
  echo "# === FILE GENERATO da deploy/proxy/gen-nginx-conf.sh — non editare a mano. ==="
  echo "# Reverse-proxy per host: instrada /v0/<dominio>/ al container <dominio>:8080"
  echo "# sulla rete docker interna 'mediamgr' (risoluzione nomi a runtime via DNS Docker)."

  if [ "$PROXY_TLS" = "1" ]; then
    echo "# TLS attivo: :80 redirige a https (con path ACME per i rinnovi); routing su :443."
    echo "server {"
    echo "    listen 80;"
    echo "    server_name $PROXY_SERVER_NAME;"
    echo "    # Sfida ACME http-01 (rinnovo Let's Encrypt) servita da webroot condiviso."
    echo "    location ^~ /.well-known/acme-challenge/ {"
    echo "        root /var/www/certbot;"
    echo "        default_type \"text/plain\";"
    echo "    }"
    echo "    location / { return 301 https://\$host\$request_uri; }"
    echo "}"
    echo ""
    echo "server {"
    echo "    listen 443 ssl;"
    echo "    http2 on;"
    echo "    server_name $PROXY_SERVER_NAME;"
    echo "    ssl_certificate $PROXY_TLS_CERT;"
    echo "    ssl_certificate_key $PROXY_TLS_KEY;"
    echo "    ssl_protocols TLSv1.2 TLSv1.3;"
    echo "    ssl_prefer_server_ciphers off;"
    echo "    ssl_session_cache shared:SSL:10m;"
    echo "    ssl_session_timeout 1d;"
    emit_server_body
    echo "}"
  else
    echo "# TLS non attivo (PROXY_TLS!=1): tutto il traffico su :80."
    echo "server {"
    echo "    listen 80;"
    echo "    server_name $PROXY_SERVER_NAME;"
    emit_server_body
    echo "}"
  fi
} > "$OUT"

echo "Generato $OUT (TLS=$PROXY_TLS, server_name=$PROXY_SERVER_NAME) per domini pubblici: $PUBLIC_DOMAINS"
