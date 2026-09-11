"""Preset generators: a `tipo` that expands into layers for the shared compositor.

A preset is a **pure function** of the request body: it returns `(canvas, layers)` and does no
I/O, no asset resolution and no rendering. The service then resolves each layer's `media`/`font`
reference and calls `layer_compositor.render_composita` exactly as it does for `composita`, so a
preset and a hand-written `layers[]` share one code path — one set of warnings, one set of
diagnostic 400s, one renderer.

Every generated layer may carry `_field` / `_font_field`: the **request** field name to quote in
a diagnostic, so the caller reads `logo_top` instead of `layers[2].media`.

Adding a preset = one builder here + its `<Nome>Request` schema in openapi/content/api.yaml.
"""
from typing import List, Optional, Tuple

SOCIAL_CANVAS: Tuple[int, int] = (1080, 1080)   # quadrato per i post social
SLIDE_CANVAS: Tuple[int, int] = (1920, 1080)    # 16:9, copertina di un video


def _text(content: str, *, field: str, font_ref, color: str, size: int, x: str, y: str,
          align: str = "center", max_width: Optional[int] = None, **extra) -> dict:
    layer = {
        "type": "text", "content": content, "color": color, "font_size": size,
        "align": align, "x": x, "y": y, "_font_field": field,
    }
    if font_ref is not None:
        layer["font"] = font_ref
    if max_width:
        layer["max_width"] = max_width
    layer.update(extra)
    return layer


def _image(ref, *, field: str, x: str, y: str, size: dict, **extra) -> dict:
    return {"type": "image", "media": ref, "x": x, "y": y, "size": size, "_field": field, **extra}


# ── social: 1080x1080, logo in alto, testo centrale, logo tondo in basso ─────────

def _build_social(body: dict) -> Tuple[Tuple[int, int], List[dict]]:
    colore_testo = body.get("colore_testo", "#ffffff")
    font = body.get("font")
    layers: List[dict] = [
        {"type": "background", "fallback_color": body.get("colore_sfondo", "#ff751f"),
         "_field": "colore_sfondo"},
        # Il logo e' vincolato in ALTEZZA: la fascia che occupa non dipende dalle sue
        # proporzioni, quindi il testo centrale non gli finisce mai sopra.
        _image(body["logo_top"], field="logo_top", x="center", y="70px",
               size={"height": "170px"}, required=True),
    ]
    testo = body.get("testo", "è lieto di ospitare")
    if testo:
        layers.append(_text(testo.upper(), field="font", font_ref=font, color=colore_testo,
                            size=74, x="center", y="50%", max_width=900))
    logo_bottom = body.get("logo_bottom")
    if logo_bottom is not None:
        layers.append(_image(logo_bottom, field="logo_bottom", x="center", y="670px",
                             size={"width": "260px"}, mask="circle"))
    testo_bottom = body.get("testo_bottom")
    if testo_bottom:
        layers.append(_text(testo_bottom, field="font", font_ref=font, color=colore_testo,
                            size=40, x="center", y="950px", max_width=900))
    return SOCIAL_CANVAS, layers


# ── slide: 1920x1080, copertina video (sfondo + velo + titolo + ospiti) ─────────

# Altezza dei ritagli persona e posizione orizzontale (% dello spazio libero) per numero di
# ospiti: piu' ospiti = ritagli piu' bassi, distribuiti nella fascia di destra (titolo a
# sinistra) o su tutta la larghezza (titolo centrato).
_PERSON_HEIGHT = {1: "70%", 2: "62%", 3: "55%"}
_PERSON_X = {
    "left": {1: ["92%"], 2: ["70%", "100%"], 3: ["62%", "81%", "100%"]},
    "center": {1: ["50%"], 2: ["15%", "85%"], 3: ["0%", "50%", "100%"]},
}


def _build_slide(body: dict) -> Tuple[Tuple[int, int], List[dict]]:
    align = body.get("allineamento", "left")
    colore_testo = body.get("colore_testo", "#ffffff")
    x_text = "80px" if align == "left" else "center"
    max_width = 920 if align == "left" else 1500   # a sinistra: fuori dalla fascia ospiti

    layers: List[dict] = [{
        "type": "background",
        "media": body.get("sfondo"),
        "fit": body.get("fit", "cover"),
        "fallback_color": body.get("colore_sfondo", "#111111"),
        "overlay": {"color": body.get("colore_velo", "#000000"),
                    "opacity": body.get("velo", 0.45)},
        "_field": "sfondo",
    }]

    persone = body.get("persone", [])[:3]
    if persone:
        height = _PERSON_HEIGHT[len(persone)]
        for ref, x in zip(persone, _PERSON_X[align][len(persone)]):
            layers.append({"type": "person", "media": ref, "x": x, "y": "bottom",
                           "size": {"height": height}, "_field": "persone"})

    logo = body.get("logo")
    if logo is not None:
        layers.append(_image(logo, field="logo", x="80px", y="56px", size={"width": "260px"}))

    layers.append(_text(
        body["titolo"], field="font_titolo", font_ref=body.get("font_titolo"),
        color=colore_testo, size=body.get("dimensione_titolo", 110), x=x_text, y="55%",
        align="left" if align == "left" else "center", max_width=max_width,
        shadow={"color": "#000000", "offset": {"x": 0, "y": 0}, "blur": 24, "opacity": 0.85},
    ))

    sottotitolo = body.get("sottotitolo")
    if sottotitolo:
        layers.append(_text(
            sottotitolo, field="font_testo", font_ref=body.get("font_testo"),
            color=colore_testo, size=52, x=x_text, y="80%",
            align="left" if align == "left" else "center", max_width=max_width,
            shadow={"color": "#000000", "offset": {"x": 0, "y": 0}, "blur": 16, "opacity": 0.8},
        ))
    return SLIDE_CANVAS, layers


_PRESETS = {"social": _build_social, "slide": _build_slide}

# Titolo del media salvato: campo della richiesta da cui ricavarlo.
_TITLE_FIELD = {"social": "testo", "slide": "titolo"}


def is_preset(tipo: str) -> bool:
    return tipo in _PRESETS


def build(tipo: str, body: dict) -> Tuple[Tuple[int, int], List[dict]]:
    """Espande la richiesta del preset in `(canvas, layers)` per il compositor."""
    return _PRESETS[tipo](body)


def title_for(tipo: str, body: dict) -> str:
    """Titolo leggibile del media generato (fallback: il nome del preset)."""
    value = body.get(_TITLE_FIELD.get(tipo, ""), "") or ""
    return " ".join(str(value).split()) or tipo
