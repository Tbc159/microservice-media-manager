# API reference — endpoint pubblici e interni

Riferimento pratico degli endpoint, diviso tra **esterni (pubblici)** — quelli che il FrontEnd
usa — e **interni** — raggiungibili solo sulla rete docker, mediati dal BFF. Per il design dei
domini vedi [domains-and-api.md](domains-and-api.md).

## Modello

```
FrontEnd / Internet ─► /v0/media/*   (PUBBLICO: dominio media, BFF)
                              │  delega sulla rete docker
                              ▼
                        /v0/source/*  (INTERNO: dominio source, marker .internal)
```

- **Esterno** = dominio **`media`** (BFF). L'unico instradato dal reverse-proxy ed esposto al
  proxy esterno (duckdns).
- **Interno** = dominio **`source`** (`openapi/source/.internal`). **Non** instradato dal proxy:
  raggiungibile solo come `http://source:8080/v0/source/...` sulla rete docker `mediamgr`, dal BFF.

## Autenticazione

Tutti gli endpoint sono protetti con header **`X-API-Key`** (eccetto `/health`). In CI/CD il valore
arriva dal secret `API_KEY` dell'Environment.

```
-H "X-API-Key: <chiave>"
```

---

## Endpoint ESTERNI (pubblici) — base `/v0/media`

> Negli esempi `$BASE` è l'host pubblico (es. `https://<sottodominio>.duckdns.org`).

### `GET /v0/media` — lista (metadati)
Envelope paginato; filtro per `type` (obbligatorio) e `title` (opzionale).
```bash
curl -H "X-API-Key: $KEY" "$BASE/v0/media?type=audio/m4a&page=1&page_size=20"
# → { "items": [ { id, title, filename, media_type, size_bytes, duration_s,
#                  created_at_s, status, content_url, download_url, metadata } ],
#     "pagination": { page, page_size, total, total_pages } }
```

### `GET /v0/media/{id}` — metadati del singolo media
```bash
curl -H "X-API-Key: $KEY" "$BASE/v0/media/1"
# → 200 MediaItem   |   404 se assente
```

### `GET /v0/media/{id}/content` — byte (play / download)
Default **inline** (player); `?download=1|true|yes|on` → **allegato** (salva).
```bash
# play (inline)
curl -H "X-API-Key: $KEY" "$BASE/v0/media/1/content" --output -
# download (attachment)
curl -L -H "X-API-Key: $KEY" "$BASE/v0/media/1/content?download=1" -o traccia.m4a
```
In coll/prod risponde `302` verso un URL pre-firmato dello storage (usare `-L` per seguirlo); in dev
streamma i byte. `404` se id assente o byte mancanti.

### `POST /v0/media` — upload (multipart)
```bash
curl -H "X-API-Key: $KEY" -X POST "$BASE/v0/media" \
  -F "file=@/percorso/traccia.m4a;type=audio/m4a" \
  -F "title=La mia traccia" -F "media_type=audio/m4a"
# → 201 MediaItem   |   400 dati non validi   |   409 gia' presente
```

I campi `content_url` / `download_url` nelle risposte puntano già al path pubblico `/v0/media/...`.

---

## Endpoint INTERNI — base `/v0/source` (NON pubblici)

Stesso set di `media`, ma **non esposti dal proxy**: si raggiungono solo dalla rete docker
(`http://source:8080/v0/source/...`), tipicamente dal BFF `media`. Utili per debug/manutenzione
con `docker exec`.

| Endpoint | Cosa |
|----------|------|
| `GET /v0/source/media?type=&title=&page=&page_size=` | lista (metadati) |
| `GET /v0/source/media/{id}` | metadati del singolo record |
| `GET /v0/source/media/{id}/content[?download=1]` | byte (inline/attachment); `302` in coll/prod |
| `POST /v0/source/media` | upload server-side (multipart) |

```bash
# esempio: verifica interna dall'host (rete docker), senza passare dal proxy
docker exec source python -c "import urllib.request; \
  print(urllib.request.urlopen('http://localhost:8080/v0/source/media/health').read())"
```

> Il dominio `source` espone gli **stessi** dati di `media`; la differenza è la **superficie**:
> `source` è il data layer interno, `media` è il contratto pubblico curato.

---

## Play vs Download

Stessi byte, stesso storage — cambia solo l'header `Content-Disposition`:

```
content_url   →  /v0/media/{id}/content              →  inline      (player <audio>/<video>)
download_url  →  /v0/media/{id}/content?download=1    →  attachment  (salva su disco)
```

## Nota sul proxy esterno

Il proxy **esterno** (duckdns, configurazione manuale) deve instradare **solo `/v0/media`**:
`/v0/source` non è pubblico. Il reverse-proxy interno (`mediamgr-proxy`) instrada già solo i domini
pubblici (salta quelli con marker `.internal`).
