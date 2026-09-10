"""Dominio `audio`: elaborazione audio (normalize/silence/convert/analyze/split/concat).

BFF pubblico: input = riferimento a un media in archivio (risolto via source), output = nuovi
media. Lavorazioni lunghe -> modello a job persistente (SQLite) con worker in background.
"""
