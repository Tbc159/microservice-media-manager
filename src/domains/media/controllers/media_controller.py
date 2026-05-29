from src.domains.media.services.media_service import MediaService

_service = MediaService()


def list_media():
    return _service.list_all(), 200
