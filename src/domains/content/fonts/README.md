# Font del dominio `content`

Il renderer delle copertine usa i font **Montserrat**:

- `Montserrat-ExtraBold.ttf`
- `Montserrat-Light.ttf`

Questi file **non sono versionati** (licenza/peso): vanno messi qui (o nella cartella
puntata da `FONTS_DIR`). In container l'immagine li monta/copia in `FONTS_DIR`
(default: questa cartella).

Se i font mancano, il renderer **non fallisce**: degrada al font di default di Pillow
(output funzionante ma meno curato) e logga un warning. Per output di qualita' in
produzione, fornire i TTF Montserrat (Open Font License) in `FONTS_DIR`.
