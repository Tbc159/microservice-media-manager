"""Download di asset da URL per l'upload interno (POST /source/media/from-url).

Sicurezza **leggera** (il dominio è già interno, `.internal`): timeout sul download e
dimensione massima. Lo streaming con abort evita di bufferizzare scaricamenti enormi: si
interrompe appena il totale supera il cap, senza scaricare tutto.
"""
from typing import Optional

import httpx

MAX_BYTES = 50 * 1024 * 1024  # 50 MB
TIMEOUT_S = 30.0


class DownloadError(Exception):
    """Download fallito: URL irraggiungibile, errore remoto o dimensione oltre il cap."""


def download(
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
    timeout: float = TIMEOUT_S,
    client: Optional[httpx.Client] = None,
) -> bytes:
    """Scarica `url` e ne restituisce i byte. Solleva DownloadError su errore o oversize.

    `client` è iniettabile per i test (es. httpx.MockTransport); in produzione se ne crea
    uno con timeout e follow_redirects.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadError(f"contenuto oltre il limite di {max_bytes} byte")
                chunks.append(chunk)
            return b"".join(chunks)
    except DownloadError:
        raise
    except httpx.HTTPError as exc:
        raise DownloadError(str(exc)) from exc
    finally:
        if owns_client:
            client.close()
