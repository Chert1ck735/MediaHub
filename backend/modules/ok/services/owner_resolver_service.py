"""Сервис определения владельца OK-стены."""

from backend.modules.ok.dto.dto import OkLinkRef, OkOwnerInfoDTO
from backend.modules.ok.utils.errors import OkApiError, OkIngestionError
from backend.modules.ok.utils.interfaces import OkApiClientProtocol


class OkOwnerResolverService:
    """Получает нормализованные данные группы OK из API."""

    def __init__(self, api_client: OkApiClientProtocol) -> None:
        self.api_client = api_client

    def resolve_group_owner(self, ref: OkLinkRef) -> OkOwnerInfoDTO:
        """Возвращает данные группы по её uid или короткому имени."""

        group_ref = ref.group_id or ref.group_ref
        if not group_ref:
            raise OkIngestionError("Не удалось определить идентификатор OK-группы")

        try:
            group = self.api_client.get_group(group_ref)
        except OkApiError as exc:
            raise OkIngestionError(f"OK API (group.getInfo): {exc}") from exc

        group_id = str(group.get("uid") or group.get("id") or "")
        if not group_id:
            raise OkIngestionError(
                f"OK не вернул идентификатор группы '{group_ref}'. Проверьте ссылку."
            )

        shortname = group.get("shortname") or group_ref
        name = group.get("name") or shortname
        return OkOwnerInfoDTO(
            name=name,
            description=group.get("description"),
            shortname=str(shortname),
            canonical_url=f"https://ok.ru/group/{shortname}",
            external_public_id=group_id,
            group_id=group_id,
            members_count=int(group.get("members_count") or 0),
        )
