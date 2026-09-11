"""Security handlers per connexion 3.x.

x-apikeyInfoFunc punta qui. Se API_KEY non e' impostata nell'env, qualsiasi
chiave non vuota e' accettata (utile in staging/mock). In produzione impostare
API_KEY con il valore atteso.

Due schemi, in OR sulla sola lettura dei byte (`GET /media/{id}/content`):
- `ApiKeyAuth` — `X-API-Key` in header: l'accesso pieno, per i client server-side;
- `SignedUrlAuth` — `?token=` in query: permesso ristretto a *quel* media, in sola lettura e
  a scadenza, per i tag `<img>`/`<audio>`/`<video>` del browser (che non mandano header).
"""
import os

from connexion.exceptions import OAuthProblem

from src import signed_url


def api_key_info(api_key, required_scopes=None):
    expected = os.environ.get("API_KEY", "")
    if not api_key:
        raise OAuthProblem("No API key provided")
    if expected and api_key != expected:
        raise OAuthProblem("Invalid API key")
    return {"sub": "service", "scopes": []}


def signed_url_info(api_key, request, required_scopes=None):
    """Verifica il token di un URL firmato (`?token=`) contro l'id nel path.

    Il legame col media e' **crittografico**, non un confronto: l'id entra nella firma, quindi
    riusare il token su un altro media la invalida. `request` e' iniettata da connexion perche'
    la funzione la dichiara fra i parametri (vedi AbstractSecurityHandler._generic_check).
    """
    media_id = (request.path_params or {}).get("id")
    if media_id is None or not signed_url.verify(api_key, media_id):
        raise OAuthProblem("Invalid or expired signed URL")
    return {"sub": f"media:{media_id}", "scopes": ["read:media"]}
