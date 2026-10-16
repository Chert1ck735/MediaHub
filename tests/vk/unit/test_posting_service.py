from datetime import timezone, datetime

import pytest
import requests

from backend.modules.vk.dto.dto import UploadPhotoDTO, CreateVkPostDTO, EditVkPostDTO
from backend.modules.vk.services.posting_service import VkPostingService
from backend.modules.vk.utils.errors import VKAPIError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self):
        self.post_payloads = []
        self.get_payloads = []
        self.post_calls = []
        self.get_calls = []

    def post(self, url, data=None, files=None, timeout=None):
        self.post_calls.append({"url": url, "data": data, "files": files, "timeout": timeout})
        payload = self.post_payloads.pop(0)
        if isinstance(payload, requests.exceptions.RequestException):
            raise payload
        return FakeResponse(payload)

    def get(self, url, params=None, timeout=None):
        self.get_calls.append({"url": url, "params": params, "timeout": timeout})
        payload = self.get_payloads.pop(0)
        if isinstance(payload, requests.exceptions.RequestException):
            raise payload
        return FakeResponse(payload)


def test_create_post_returns_post_id(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.settings.ACCESS_TOKEN",
        "token",
    )
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.settings.VK_API_VERSION",
        "5.199",
    )
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.settings.VK_API_URL_POST",
        "https://api.vk.com/method/wall.post",
    )
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.time.sleep",
        lambda _: None,
    )

    session = FakeSession()
    session.post_payloads = [{"response": {"post_id": 10}}]

    service = VkPostingService(session=session)

    post_id = service.create_post(
        CreateVkPostDTO(
            message="hello",
            attachments="photo1_2",
            owner_id=-123,
        )
    )

    assert post_id == 10
    assert session.post_calls[0]["data"]["owner_id"] == -123
    assert session.post_calls[0]["data"]["from_group"] == 1
    assert session.post_calls[0]["data"]["attachments"] == "photo1_2"


def test_create_post_raises_vk_api_error(monkeypatch):
    monkeypatch.setattr("backend.modules.vk.services.posting_service.settings.VK_API_URL_POST", "url")
    monkeypatch.setattr("backend.modules.vk.services.posting_service.time.sleep", lambda _: None)
    session = FakeSession()
    session.post_payloads = [{"error": {"error_msg": "denied"}}]
    service = VkPostingService(session=session)

    with pytest.raises(VKAPIError, match="denied"):
        service.create_post(CreateVkPostDTO(message="hello"))


def test_edit_delete_and_post_url(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.time.sleep",
        lambda _: None,
    )

    session = FakeSession()
    session.post_payloads = [
        {"response": 1},
        {"response": 1},
    ]

    service = VkPostingService(session=session)

    assert service.edit_post(
        EditVkPostDTO(
            post_id=1,
            message="updated",
            owner_id=-123,
        )
    ) is True

    assert service.delete_post(
        post_id=1,
        owner_id=-123,
    ) is True

    assert service.post_url(
        post_id=1,
        owner_id=-123,
    ) == "https://vk.com/wall-123_1"


def test_upload_wall_photo_success(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.settings.GROUP_ID",
        123,
    )
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.time.sleep",
        lambda _: None,
    )

    session = FakeSession()
    session.get_payloads = [
        {"response": {"upload_url": "https://upload.example"}},
    ]
    session.post_payloads = [
        {"photo": "photo_payload", "server": 1, "hash": "hash"},
        {"response": [{"owner_id": -123, "id": 555}]},
    ]

    service = VkPostingService(session=session)

    attachment = service.upload_wall_photo(
        UploadPhotoDTO(
            file_bytes=b"jpg",
            filename="a.jpg",
            content_type="image/jpeg",
        )
    )

    assert attachment == "photo-123_555"
    assert session.post_calls[0]["files"]["photo"][0] == "a.jpg"

def test_upload_wall_photo_raises_when_vk_returns_empty_photo(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.settings.GROUP_ID",
        123,
    )
    monkeypatch.setattr(
        "backend.modules.vk.services.posting_service.time.sleep",
        lambda _: None,
    )

    session = FakeSession()
    session.get_payloads = [
        {"response": {"upload_url": "https://upload.example"}},
    ]
    session.post_payloads = [
        {"photo": "[]", "server": 1, "hash": "hash"},
    ]

    service = VkPostingService(session=session)

    with pytest.raises(VKAPIError, match="VK не принял фото"):
        service.upload_wall_photo(
            UploadPhotoDTO(
                file_bytes=b"jpg",
                filename="a.jpg",
                content_type="image/jpeg",
            )
        )


def test_to_timestamp_handles_naive_and_aware_datetime():
    service = VkPostingService(session=FakeSession())

    assert service._to_timestamp(123) == 123
    assert service._to_timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600
    assert service._to_timestamp(datetime(2026, 1, 1)) == 1767225600
