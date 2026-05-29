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
                },
            }
        ]
