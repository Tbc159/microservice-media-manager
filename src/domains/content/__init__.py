"""Dominio `content`: generazione immagini (copertine, social) come BFF pubblico.

Legge gli asset (logo, avatar) dal dominio interno `source` e vi salva l'immagine
generata, restituendone gli URL pubblici (su /v0/media). La logica di rendering
(Pillow) vive nei service ed e' indipendente dal framework.
"""
