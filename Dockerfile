# Dockerfile UNICO e parametrico per ogni dominio: una sola ricetta -> nessuna
# ambiguita' di versioni tra i microservizi. Si seleziona il dominio col build-arg
# DOMAIN (es. --build-arg DOMAIN=media).
#
# Il server a runtime NON usa generated/: connexion carica direttamente la spec
# OAS e risolve verso i controller in src/. Quindi l'immagine non richiede Java.
FROM python:3.12-slim

ARG DOMAIN
ENV DOMAIN=${DOMAIN} \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY openapi/ ./openapi/

EXPOSE 8080

# DOMAIN monta il singolo dominio; il reverse-proxy instrada /<DOMAIN>/* qui.
CMD ["python", "-m", "src.app"]
