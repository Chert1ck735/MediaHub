"""Сервис-парсер OK-ссылок."""

from backend.modules.ok.dto.dto import OkLinkRef
from backend.modules.ok.links.links import parse_ok_link


class OkLinkParser:
    """Оборачивает чистую функцию parse_ok_link в интерфейсный сервис."""

    def parse(self, raw: str) -> OkLinkRef:
        """Распознаёт OK-ссылку как group/profile/topic."""

        return parse_ok_link(raw)
