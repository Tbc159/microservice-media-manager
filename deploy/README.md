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
