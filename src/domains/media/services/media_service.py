"""Business logic del dominio media.
Sostituire la sorgente dati statica con la persistenza reale.
Il sample rispetta lo schema MediaItem (validate_responses=True)."""


class MediaService:
    def list_all(self):
        return [
            {
                "id": 2,
                "name": "data_NomeFile.m4a",
                "creation_date_s": 1779873651,
                "download_link": "http://host/download/data_NomeFile.m4a",
                "status": "draft",
                "pubblicazione": {
                    "titolo": None,
                    "description": None,
                    "cover_image": None,
                    "publishing_date_s": None,
                },
            },
            {
                "id": 1,
                "name": "data_AltroFile.m4a",
                "creation_date_s": 1779873600,
                "download_link": "http://host/download/data_AltroFile.m4a",
                "status": "published",
                "pubblicazione": {
                    "titolo": "Titolo puntata",
                    "description": "Descrizione puntata",
                    "cover_image": "http://host/covers/data_AltroFile.jpg",
                    "publishing_date_s": 1879873651,
                },
            },
            {
                "id": 0,
                "name": "data_PrimoFile.m4a",
                "creation_date_s": 1779873500,
                "download_link": "http://host/download/data_PrimoFile.m4a",
                "status": "processing",
                "pubblicazione": {
                    "titolo": None,
                    "description": None,
                    "cover_image": None,
                    "publishing_date_s": None,
                },
            },
        ]
