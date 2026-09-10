# Deploy — runbook operativo

Come deployare i microservizi su un host (LXC Proxmox o macchina locale) e come riconfigurare
tutto da zero. Per il quadro d'insieme vedi la sezione "Deploy / infrastruttura" del `README.md`.

## Modello

- **1 ambiente = 1 host = 1 self-hosted runner.** Mapping:

  | Branch | Environment GitHub | Label runner | Host |
  |--------|--------------------|--------------|------|
  | `develop` | `staging` | `self-hosted,staging` | macchina dev locale |
  | `coll` | `collaudo` | `self-hosted,collaudo` | LXC collaudo |
  | `main` | `production` | `self-hosted,production` | LXC produzione (gate reviewers) |

- Su ogni host: una rete docker `mediamgr`, un container **nginx** (reverse-proxy) che instrada
  `/<dominio>/` → `http://<dominio>:8080`, e un container per dominio (`media`, `social`, …).
- **Build sull'host** (nessun registry): il runner fa `docker compose up -d --build`.

## Prerequisiti host (una volta)

1. Docker + plugin compose, `bash`, `curl` installati.
2. Utente del runner nel gruppo `docker` (`sudo usermod -aG docker $USER` poi ri-login).
3. Rete docker condivisa:
   ```bash
   docker network create mediamgr
   ```
4. (Opzionale) porta pubblicata del proxy diversa dalla 80: imposta la **variabile** GitHub
   `PROXY_HTTP_PORT` (repo o environment) — es. `8080`. Il workflow la passa al compose del proxy.

## Registrare il self-hosted runner (una volta per host)

Ottieni un registration token (scade in ~1h):
```bash
gh api -X POST repos/Tbc159/microservice-media-manager/actions/runners/registration-token --jq .token
```
Sull'host:
```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
# scarica l'ultimo runner: vedi Settings -> Actions -> Runners -> New self-hosted runner
curl -o runner.tar.gz -L https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64.tar.gz
tar xzf runner.tar.gz
./config.sh \
  --url https://github.com/Tbc159/microservice-media-manager \
  --token <TOKEN> \
  --labels self-hosted,<staging|collaudo|production> \
  --name <hostname> --unattended
sudo ./svc.sh install && sudo ./svc.sh start    # esegue come servizio
```

⚠️ **Sicurezza:** i self-hosted runner su repo **pubblici** sono rischiosi. Qui il deploy parte solo
su `push` ai branch protetti (i fork non pushano) e `ci.yaml`/`api-draft.yaml` girano su runner
cloud. Consigliato comunque rendere il repo privato: `gh repo edit Tbc159/microservice-media-manager --visibility private --accept-visibility-change-consequences`.

## Cosa fa il workflow `generate-api.yml` al deploy

Per ogni dominio impattato dal push, sul runner dell'ambiente:
```bash
docker network create mediamgr 2>/dev/null || true
bash deploy/proxy/gen-nginx-conf.sh                                  # rigenera nginx.conf dai domini
docker compose -f deploy/proxy/docker-compose.proxy.yml up -d        # proxy (idempotente)
docker compose -f docker-compose.<dominio>.yml up -d --build         # build+run del dominio
curl -fsS http://localhost:${PROXY_HTTP_PORT:-80}/<dominio>/health   # smoke
```

## Deploy manuale (debug, senza CI)

```bash
export APP_ENV=staging          # o collaudo/production
docker network create mediamgr 2>/dev/null || true
bash deploy/proxy/gen-nginx-conf.sh
docker compose -f deploy/proxy/docker-compose.proxy.yml up -d
docker compose -f docker-compose.media.yml up -d --build
curl -fsS http://localhost:${PROXY_HTTP_PORT:-80}/media/health
```

## HTTPS del proxy (Let's Encrypt via DuckDNS, DNS-01)

Il proxy termina il TLS. Emissione **una tantum** sull'host (serve il token DuckDNS). Con il
challenge **DNS-01** non serve esporre la 80: si aggiorna il TXT `_acme-challenge.<sub>.duckdns.org`
via l'API DuckDNS.

```bash
export DUCKDNS_TOKEN=xxxxxxxx SUB=mediamanager-dev
mkdir -p deploy/proxy/certs deploy/proxy/certbot-www

# 1) Emetti il certificato (hook manuali che aggiornano il TXT su DuckDNS)
docker run --rm -it -v "$PWD/deploy/proxy/letsencrypt:/etc/letsencrypt" certbot/certbot certonly \
  --manual --preferred-challenges dns --agree-tos -m you@example.com --no-eff-email \
  --manual-auth-hook 'curl -fsS "https://www.duckdns.org/update?domains='"$SUB"'&token='"$DUCKDNS_TOKEN"'&txt=$CERTBOT_VALIDATION" && sleep 30' \
  --manual-cleanup-hook 'curl -fsS "https://www.duckdns.org/update?domains='"$SUB"'&token='"$DUCKDNS_TOKEN"'&txt=removed&clear=true"' \
  -d "$SUB.duckdns.org"
# (in alternativa il plugin certbot-dns-duckdns, senza hook manuali)

# 2) Rendi i cert leggibili dal proxy come fullchain.pem + privkey.pem
cp deploy/proxy/letsencrypt/live/$SUB.duckdns.org/{fullchain,privkey}.pem deploy/proxy/certs/
```

3. **Attiva TLS** impostando i `vars` dell'Environment GitHub (staging):
   `PROXY_TLS=1`, `PROXY_SERVER_NAME=mediamanager-dev.duckdns.org`
   (`PROXY_CERTS_DIR`/`PROXY_HTTPS_PORT` hanno default `./certs` e `443`). Al deploy successivo
   `gen-nginx-conf.sh` genera il server `:443` + redirect `:80→443`, e il compose pubblica la 443 e
   monta i certificati. In locale/debug:
   `PROXY_TLS=1 PROXY_SERVER_NAME=... bash deploy/proxy/gen-nginx-conf.sh`.

4. **Rinnovo** (i cert durano 90g): cron sull'host che rilancia `certbot renew` (stessi hook), ricopia
   i pem in `deploy/proxy/certs/` e ricarica nginx: `docker exec mediamgr-proxy nginx -s reload`.

> I certificati e i webroot ACME (`deploy/proxy/certs/`, `letsencrypt/`, `certbot-www/`) sono
> **gitignored**: non vanno mai committati. `source` resta interno (nessuna rotta nel proxy), quindi
> non e' esposto neppure via https.

## CORS dei domini pubblici (`media`, `content`)

Il CORS e' gestito **nell'app** (`src/cors.py`), non in nginx: unica sede (niente header duplicati che
romperebbero il preflight) e preflight coperto da un contract test. Si attiva impostando le origini web
consentite:

- `vars.CORS_ALLOW_ORIGINS` nell'Environment = elenco separato da virgola, es.
  `https://app.miodominio.tld,http://localhost:5173`. Vuoto → CORS disattivato.

Il workflow la passa ai soli container `media` e `content` (mai `source`). Il preflight `OPTIONS` su un
endpoint pubblico risponde `204` con `Access-Control-Allow-Origin` (l'origine, mai `*`),
`Access-Control-Allow-Headers: content-type, x-api-key`, `Access-Control-Allow-Methods: GET, POST,
OPTIONS` e `Access-Control-Max-Age`.

## Aggiungere un nuovo dominio (es. social)

1. `openapi/social/api.yaml` (path relative, operationId).
2. `src/domains/social/{controllers,services}` (vedi media come modello).
3. `docker-compose.social.yml` = copia di `docker-compose.media.yml` con `social` al posto di `media`
   e `config/social/<env>.env`.
4. Nient'altro: `gen-nginx-conf.sh` aggiunge la rotta `/social/` e la CI lo scopre da sé.

## Aggiungere un nuovo ambiente/host

1. Crea l'Environment GitHub e i suoi secret.
2. Mappa il branch in `generate-api.yml` (step `map`) e usa la label runner uguale al nome env.
3. Registra il runner sull'host con quella label; crea la rete `mediamgr`.
