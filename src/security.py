"""Security handlers per connexion 3.x.

x-apikeyInfoFunc punta qui. Se API_KEY non e' impostata nell'env, qualsiasi
chiave non vuota e' accettata (utile in staging/mock). In produzione impostare
API_KEY con il valore atteso.
"""
import os

from connexion.exceptions import OAuthProblem


def api_key_info(api_key, required_scopes=None):
    expected = os.environ.get("API_KEY", "")
    if not api_key:
        raise OAuthProblem("No API key provided")
    if expected and api_key != expected:
        raise OAuthProblem("Invalid API key")
    return {"sub": "service", "scopes": []}
