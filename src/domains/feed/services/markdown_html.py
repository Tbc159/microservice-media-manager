"""Markdown -> HTML sanificato per `<content:encoded>`.

Il contenuto arriva da un evento Nostr, cioe' da chiunque: finisce dentro un feed che le app
di podcast renderizzano come HTML. Sanificare non e' opzionale.

Scelta: markdown-it-py con **`html=False`**. Non e' un dettaglio di configurazione — e' la
sanificazione stessa:
  - l'HTML grezzo nel sorgente viene **escapato**, non passato (`<script>` diventa testo);
  - i link con schemi pericolosi (`javascript:`, `data:text/html`, `vbscript:`) sono scartati
    dal validatore integrato e restano testo semplice.
Il risultato contiene quindi solo i tag che genera il parser da costrutti Markdown. Attenzione:
il preset "commonmark" di markdown-it abilita `html` — passarlo senza sovrascriverlo
reintrodurrebbe l'XSS. I test lo verificano.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def _renderer():
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})


def to_html(markdown: str) -> str:
    if not markdown:
        return ""
    return _renderer().render(markdown).strip()
