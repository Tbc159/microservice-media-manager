"""Costruzione del documento RSS 2.0 a partire dagli eventi Nostr. Puro: niente rete, niente I/O.

Due vincoli guidano il codice piu' di quanto sembri:

1. **Determinismo.** L'ETag e' l'hash del corpo, quindi il corpo non puo' contenere nulla che
   cambi a parita' di eventi: niente `now()`, niente insiemi iterati in ordine casuale.
   `lastBuildDate` deriva dall'evento piu' recente, non dall'orologio.
2. **Date RFC 822 in inglese.** `strftime("%a, %d %b %Y")` dipende dal locale del container:
   con `LANG=it_IT` produrrebbe "Sab, 13 Set" e i validatori lo rifiutano. I nomi sono scritti
   a mano.

Cio' che non si sa non si inventa: niente `<itunes:category>`, niente `<itunes:duration>`,
niente `<itunes:owner>` senza email — a meno che l'evento non li dichiari.

**Tag oltre NIP-F4.** Le piattaforme pretendono dati che NIP-F4 non prevede: Apple e Amazon
rifiutano un feed senza `itunes:category`; Spotify, Amazon e YouTube verificano la proprieta'
mandando un codice all'`itunes:email`; il validatore W3C tratta un `<itunes:owner>` senza
`<itunes:email>` come errore. Il client li scrive nel 10154 e nel 54 con tag semplici, e qui
si leggono — tutti facoltativi, e senza di essi il comportamento non cambia:

  10154  ["category", "News", "Daily News"]  fino a 3, il primo e' la primaria (nomi Apple)
         ["language", "it"]                  ISO 639-1: vince su ?lang, che vince sul default
         ["email", "owner@esempio.tld"]      itunes:owner esiste SOLO se c'e' questo
         ["content-warning", ...]            NIP-36: la presenza (anche vuoto) = explicit
  54     ["duration", "3600"]                secondi interi -> itunes:duration
         ["content-warning", ...]            explicit del singolo episodio
"""
import re
import uuid
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse
from xml.sax.saxutils import escape, quoteattr

from src.domains.feed.nostr import nip19
from src.domains.feed.nostr.events import first_tag_value, tag_values

_MAX_CATEGORIES = 3
_LANG_RE = re.compile(r"^[a-zA-Z]{2}(-[a-zA-Z]{2,8})?$")

# Namespace di Podcasting 2.0 per <podcast:guid>: e' cosi' che Podcast Index deduplica i feed.
PODCAST_NAMESPACE = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")

GENERATOR = "media-manager feed"
NJUMP = "https://njump.me/"

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rfc822(timestamp: int) -> str:
    """Data RFC 822 in UTC, con nomi inglesi indipendenti dal locale del container."""
    import datetime

    dt = datetime.datetime.fromtimestamp(int(timestamp), datetime.timezone.utc)
    return (f"{_DAYS[dt.weekday()]}, {dt.day:02d} {_MONTHS[dt.month - 1]} {dt.year} "
            f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0000")


def podcast_guid(feed_url: str) -> str:
    """UUIDv5 dell'URL del feed **senza schema**, nel namespace di Podcasting 2.0."""
    without_scheme = feed_url.split("://", 1)[-1]
    return str(uuid.uuid5(PODCAST_NAMESPACE, without_scheme))


def audio_tags(event: dict) -> List[Sequence[str]]:
    """Tag `audio` con MIME `audio/*`, nell'ordine dell'evento. Il primo diventa l'enclosure."""
    out = []
    for values in tag_values(event, "audio"):
        url = absolute_url(values[0] if values else None)
        mime = values[1] if len(values) > 1 else None
        if url and mime and mime.lower().startswith("audio/"):
            out.append((url, mime))
    return out


def absolute_url(value: Optional[str]) -> Optional[str]:
    """URL assoluto, o None se il valore non e' utilizzabile come URL.

    Gli eventi Nostr portano spesso URL **senza schema** (`tbc159.github.io/x`): finiti in un
    `<link>` o in un `enclosure` non sono URL validi — i validatori li segnalano e i client li
    interpretano come path relativi al proprio host. Qui si completa con `https://`, che non
    inventa informazione (host e path restano quelli scritti dall'autore) e oggi e' il default
    ragionevole. Cio' che non assomiglia a un URL (uno schema diverso, o del testo qualsiasi)
    viene scartato: meglio il ripiego del chiamante che un link rotto nel feed.
    """
    value = (value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value
    if parsed.scheme:                      # mailto:, ftp:, javascript:... non e' un link web
        return None
    host = value.split("/", 1)[0]
    if "." not in host or " " in host:     # non assomiglia a un host
        return None
    return f"https://{value}"


def categories(card: dict) -> List[Sequence[str]]:
    """`[(principale, sotto|None), ...]` dai tag `category`, nell'ordine, al massimo 3.

    I nomi sono quelli **esatti** di Apple, `&` compresa e non escapata: la validazione contro
    l'elenco la fa il client prima di pubblicare, qui si riporta quello che si trova.
    """
    out: List[Sequence[str]] = []
    for values in tag_values(card, "category"):
        main = (values[0] if values else "").strip()
        if not main:
            continue
        sub = values[1].strip() if len(values) > 1 and values[1] and values[1].strip() else None
        out.append((main, sub))
        if len(out) >= _MAX_CATEGORIES:
            break
    return out


def language(card: dict, requested: str) -> str:
    """Il tag `language` del 10154 vince su `?lang`; `?lang` vince sul default.

    Un valore che non e' un codice lingua (`"italiano"`) romperebbe l'intero feed per i
    validatori: si ignora e si ricade su `requested`.
    """
    declared = (first_tag_value(card, "language") or "").strip()
    return declared.lower() if _LANG_RE.match(declared) else requested


def is_explicit(event: dict) -> bool:
    """NIP-36: la **presenza** del tag `content-warning`, anche vuoto, marca il contenuto."""
    return bool(tag_values(event, "content-warning"))


def duration_seconds(event: dict) -> Optional[int]:
    """Secondi interi dal tag `duration`, o None se assente o non intero."""
    raw = (first_tag_value(event, "duration") or "").strip()
    return int(raw) if raw.isdigit() else None


def _cdata(text: str) -> str:
    """CDATA a prova di `]]>` nel contenuto (chiude la sezione e la riapre)."""
    return "<![CDATA[" + (text or "").replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _tag(name: str, text: Optional[str], indent: str = "    ") -> str:
    if text is None or text == "":
        return ""
    return f"{indent}<{name}>{escape(text)}</{name}>\n"


def _author_name(profile: Optional[dict], npub: str) -> str:
    if profile:
        import json

        try:
            data = json.loads(profile.get("content") or "{}")
        except ValueError:
            data = {}
        if isinstance(data, dict):
            for key in ("display_name", "displayName", "name"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return npub


def build_feed(
    *,
    card: dict,
    profile: Optional[dict],
    episodes: Sequence[dict],
    pubkey_hex: str,
    feed_url: str,
    lang: str,
    relays: Sequence[str],
    enclosure_lengths: Dict[str, Optional[int]],
    skipped: int = 0,
    episode_relay_hints: Sequence[str] = (),
) -> str:
    """Documento RSS completo. `enclosure_lengths`: url -> Content-Length (None se ignoto)."""
    npub = nip19.hex_to_npub(pubkey_hex)
    title = first_tag_value(card, "title") or npub
    description = first_tag_value(card, "description") or ""
    image = absolute_url(first_tag_value(card, "image"))
    website = absolute_url(first_tag_value(card, "website")) or f"{NJUMP}{npub}"
    author = _author_name(profile, npub)

    out = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    # I relay interrogati in testa: un feed vuoto e' quasi sempre un problema di relay, e
    # senza questa riga non e' diagnosticabile da chi scarica il feed.
    out.append(f"<!-- relays: {escape(', '.join(relays))} -->\n")
    out.append(
        '<rss version="2.0"\n'
        '     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"\n'
        '     xmlns:content="http://purl.org/rss/1.0/modules/content/"\n'
        '     xmlns:atom="http://www.w3.org/2005/Atom"\n'
        '     xmlns:podcast="https://podcastindex.org/namespace/1.0">\n'
        "  <channel>\n"
    )
    out.append(_tag("title", title))
    out.append(_tag("description", description))
    out.append(_tag("link", website))
    out.append(_tag("language", language(card, lang)))
    out.append(f"    <generator>{escape(GENERATOR)}</generator>\n")
    out.append(f'    <atom:link href={quoteattr(feed_url)} rel="self" '
               'type="application/rss+xml"/>\n')
    out.append(f"    <podcast:guid>{podcast_guid(feed_url)}</podcast:guid>\n")
    if image:
        out.append(
            "    <image>\n"
            f"      <url>{escape(image)}</url>\n"
            f"      <title>{escape(title)}</title>\n"
            f"      <link>{escape(website)}</link>\n"
            "    </image>\n"
            f"    <itunes:image href={quoteattr(image)}/>\n"
        )
    else:
        # Apple richiede itunes:image, ma la scheda non ne ha una e NON la si inventa: il
        # kind 0 avrebbe una `picture`, che pero' e' l'avatar dell'autore, non la copertina
        # del podcast. Lo si dichiara qui, cosi' chi sottomette il feed sa cosa sistemare
        # (aggiungendo un tag `image` al proprio kind 10154).
        out.append("    <!-- image assente nel kind 10154: Apple richiede itunes:image -->\n")
    out.append(_tag("itunes:author", author))
    email = (first_tag_value(card, "email") or "").strip()
    if email:
        # itunes:owner esiste SOLO con l'email: e' l'indirizzo a cui Spotify/Amazon/YouTube
        # mandano il codice di verifica della proprieta', e per il validatore W3C un owner
        # senza email e' un errore. Un owner vuoto e' peggio di nessun owner.
        out.append("    <itunes:owner>\n"
                   f"      <itunes:name>{escape(author)}</itunes:name>\n"
                   f"      <itunes:email>{escape(email)}</itunes:email>\n"
                   "    </itunes:owner>\n")
    for main, sub_category in categories(card):
        # quoteattr scrive la & come &amp; nell'attributo: "Kids & Family" resta il nome Apple.
        if sub_category:
            out.append(f"    <itunes:category text={quoteattr(main)}>\n"
                       f"      <itunes:category text={quoteattr(sub_category)}/>\n"
                       "    </itunes:category>\n")
        else:
            out.append(f"    <itunes:category text={quoteattr(main)}/>\n")
    # Obbligatorio per Apple: senza content-warning (NIP-36) e' false, l'unica scelta onesta.
    out.append(f"    <itunes:explicit>{'true' if is_explicit(card) else 'false'}</itunes:explicit>\n")
    if episodes:
        out.append(_tag("lastBuildDate", rfc822(max(e["created_at"] for e in episodes))))

    for event in episodes:
        out.append(_item(event, pubkey_hex, enclosure_lengths, episode_relay_hints))

    if skipped:
        # In coda ma DENTRO <channel>: dopo </rss> sarebbe nell'epilogo del documento —
        # tecnicamente valido, ma alcuni validatori di feed lo trattano male.
        out.append(f"    <!-- saltati: {skipped} senza audio -->\n")
    out.append("  </channel>\n</rss>\n")
    return "".join(out)


def _item(event: dict, pubkey_hex: str, lengths: Dict[str, Optional[int]],
          relay_hints: Sequence[str]) -> str:
    from src.domains.feed.services import markdown_html

    title = first_tag_value(event, "title") or ""
    description = first_tag_value(event, "description") or ""
    image = absolute_url(first_tag_value(event, "image"))
    url, mime = audio_tags(event)[0]
    length = lengths.get(url)
    nevent = nip19.encode_nevent(event["id"], relays=relay_hints, author_hex=pubkey_hex,
                                 kind=event["kind"])

    body = (event.get("content") or "").strip()
    html = markdown_html.to_html(body) if body else escape(description)

    out = ["    <item>\n"]
    out.append(_tag("title", title, "      "))
    out.append(_tag("description", description, "      "))
    if html:
        out.append(f"      <content:encoded>{_cdata(html)}</content:encoded>\n")
    out.append(f'      <guid isPermaLink="false">{escape(event["id"])}</guid>\n')
    out.append(_tag("pubDate", rfc822(event["created_at"]), "      "))
    out.append(_tag("link", f"{NJUMP}{nevent}", "      "))
    if image:
        out.append(f"      <itunes:image href={quoteattr(image)}/>\n")
    if length is None:
        # Non si omette l'enclosure: un item senza enclosure non e' un episodio per nessun
        # aggregatore. Si dichiara 0 e si dice perche', cosi' e' diagnosticabile.
        out.append("      <!-- length sconosciuto: HEAD sull'URL non riuscita -->\n")
    out.append(f'      <enclosure url={quoteattr(url)} type={quoteattr(mime)} '
               f'length="{length if length is not None else 0}"/>\n')
    seconds = duration_seconds(event)
    if seconds is not None:
        out.append(f"      <itunes:duration>{seconds}</itunes:duration>\n")
    if is_explicit(event):
        out.append("      <itunes:explicit>true</itunes:explicit>\n")
    for alt_url, alt_mime in audio_tags(event)[1:]:
        alt_length = lengths.get(alt_url)
        length_attr = f' length="{alt_length}"' if alt_length is not None else ""
        out.append(f"      <podcast:alternateEnclosure type={quoteattr(alt_mime)}{length_attr}>\n"
                   f"        <podcast:source uri={quoteattr(alt_url)}/>\n"
                   "      </podcast:alternateEnclosure>\n")
    out.append("    </item>\n")
    return "".join(out)
