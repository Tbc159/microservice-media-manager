# Handoff — microservices-media

## Repo
`https://github.com/Tbc159/microservices-media.git`

## Branch layout

| Branch | Contenuto |
|--------|-----------|
| `main` | Solo `README.md` (overview dei processi) |
| `dev`  | Tutti i microservizi Flask — **questo è il branch da cui estrarre codice** |
| `client` | Script Python client (`client/create_yt_media.py`, `client/upload_media.py`) |

## Struttura di `dev`

```
ffmpeg/          # Microservizio Flask — elaborazione audio con FFmpeg
  app.py                         # Route Flask
  processors/ffmpeg_processor.py # Logica FFmpeg (normalizzazione, silence removal, split, conversione)

ytmedia/         # Microservizio Flask — gestione asset media e generazione immagini
  app.py                              # Route Flask
  processors/media_processor.py       # Upload, registro UUID, lookup per id o nome file
  processors/slide_processor.py       # Generazione slide YouTube (1920×1080, Pillow)
  processors/social_processor.py      # Generazione immagine social (1080×1080, Pillow)
  processors/video_creator_processor.py # Creazione video da slide con FFmpeg
  processors/youtube_processor.py     # Download audio da YouTube (yt-dlp)

client/
  upload_media.py    # Caricamento file su ffmpeg/uploader
  create_yt_media.py # Pipeline: normalizzazione → (silence removal TODO) → link download

news/            # Microservizio lettura notizie TTS
station/         # Microservizio gestione playlist radio
uploader/        # Microservizio upload file
```

## Frammenti chiave da sapere

### Normalizzazione audio (ffmpeg/processors/ffmpeg_processor.py)
- Filtro: `dynaudnorm=f=500:g=31:p=0.95,loudnorm=I=-16:TP=-1.5:LRA=11`
- `dynaudnorm` prima (equalizz. per-frame ~500ms, ideale per più speaker alternati) poi `loudnorm` per target EBU R128 (-16 LUFS)
- Helper `_probe_audio()` usa ffprobe per stimare durata e size prima di avviare
- Output in `NORMALIZED_FOLDER` (env var)

### Registro media (ytmedia/processors/media_processor.py)
- File `media_registry.json` nella `MEDIA_FOLDER`
- Ogni file caricato/generato riceve un UUID e viene registrato
- `lookup_media_by_id_or_name(value, base_folder)`: cerca prima per UUID nel registry, poi per nome file ricorsivo su disco
- Quindi è possibile referenziare gli asset sia per UUID che per nome file originale

### Generazione immagine social (ytmedia/processors/social_processor.py)
- `SocialRequest`: `logo_top` (required), `logo_bottom` (required), `testo` (default: `"è lieto di ospitare"`), `colore_sfondo` (default: `#ff751f`), `colore_testo`, `testo_bottom`
- Output: PNG 1080×1080, in memoria come BytesIO

### Generazione slide YouTube (ytmedia/processors/slide_processor.py)
- `SlideRequest`: `testo_alto`, `testo_centrale`, `testo_basso`, `logo` (optional UUID/nome), `colore_sfondo`, ecc.
- Output: PNG 1920×1080

### Pipeline client (client/create_yt_media.py)
- Lavora su file in `<folder>/uploaded/`
- Step 1: POST `/media/normalize` → polling GET `/media/job/<job_id>` ogni 10s (timeout 10min)
- Step 2: POST `/media/remove_silence` — **attualmente commentato**, endpoint non ancora fixato sul server
- Successo → `done/`, fallimento → `failed/`
- Polling interval: `POLL_INTERVAL_SEC = 10`

## Host di produzione
`http://api-v0-bitcoinradio.duckdns.org` (porta 80, reverse proxy)

Endpoint principali:
- `POST /yt/media` — upload asset (multipart, chiave `files`)
- `GET /yt/media/<uuid-o-nome-file>` — download asset
- `POST /yt/slide` — genera slide YouTube
- `POST /yt/media/social` — genera immagine social
- `POST /media/normalize` — avvia normalizzazione audio (async, ritorna `job_id`)
- `GET /media/job/<job_id>` — polling stato job

## Note deployment
- Se un endpoint risponde 405: il container gira su una versione vecchia → fare `git pull` + rebuild sul server
- UUID degli asset persistono in `media_registry.json` tra i restart del container
