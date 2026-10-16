"""Сервис определения владельца VK-стены."""

from backend.modules.vk.dto.dto import VkOwnerInfoDTO, VkLinkRef, VkLinkType
from backend.modules.vk.utils.errors import IngestionError, VkApiError
from backend.modules.vk.utils.interfaces import VkApiClientProtocol


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class VkOwnerResolverService:
    """Получает нормализованные данные владельца стены из VK API."""

    def __init__(self, api_client: VkApiClientProtocol) -> None:
        self.api_client = api_client

    def resolve_screen_name(self, ref: VkLinkRef) -> VkLinkRef:
        """Уточняет screen_name как community или profile."""

        if not ref.domain:
            return ref
        try:
            info = self.api_client.resolve_screen_name(ref.domain)
        except VkApiError as exc:
            raise IngestionError(f"VK API: {exc}") from exc
        obj_type = (info or {}).get("type")
        object_id = (info or {}).get("object_id")
        if obj_type in {"group", "page", "event"} and object_id:
            return VkLinkRef(type=VkLinkType.COMMUNITY, raw_url=ref.raw_url, canonical_url=ref.canonical_url, domain=ref.domain, owner_id=-int(object_id), screen_name=ref.screen_name)
        if obj_type == "user" and object_id:
            return VkLinkRef(type=VkLinkType.PROFILE, raw_url=ref.raw_url, canonical_url=ref.canonical_url, domain=ref.domain, owner_id=int(object_id), screen_name=ref.screen_name)
        raise IngestionError(f"VK не распознал screen_name '{ref.domain}'. Проверьте ссылку или укажите числовой id.")

    def resolve_community_owner(self, ref: VkLinkRef) -> VkOwnerInfoDTO:
        """Возвращает данные сообщества."""

        try:
            group_ref = ref.domain or abs(ref.owner_id or 0)
            group = self.api_client.get_group(group_ref)
        except VkApiError as exc:
            raise IngestionError(f"VK API (groups.getById): {exc}") from exc
        group_id = int(group["id"])
        screen = group.get("screen_name") or ref.screen_name or f"club{group_id}"
        name = group.get("name") or screen
        return VkOwnerInfoDTO(name=name, description=group.get("description"), screen=screen, canonical_url=f"https://vk.com/{screen}", external_public_id=str(group_id), owner_id=-group_id, members_count=int(group.get("members_count") or 0))

    def resolve_profile_owner(self, ref: VkLinkRef) -> VkOwnerInfoDTO:
        """Возвращает данные профиля."""

        user_ref = ref.domain or ref.owner_id
        if user_ref is None:
            raise IngestionError("Не удалось определить идентификатор VK-профиля")
        try:
            info = self.api_client.get_user(user_ref)
        except VkApiError as exc:
            raise IngestionError(f"VK API (users.get): {exc}") from exc
        if info.get("deactivated"):
            raise IngestionError(f"Профиль VK '{user_ref}' деактивирован ({info['deactivated']})")
        user_id = int(info["id"])
        screen = info.get("screen_name") or ref.screen_name or f"id{user_id}"
        full_name = " ".join(filter(None, [info.get("first_name"), info.get("last_name")])).strip()
        display_name = full_name or screen
        followers_count_getter = getattr(self.api_client, "get_user_followers_count", None)
        if followers_count_getter is not None:
            try:
                followers = _safe_int(followers_count_getter(user_id))
            except VkApiError:
                followers = _safe_int(info.get("followers_count") or (info.get("counters") or {}).get("followers"))
        else:
            followers = _safe_int(info.get("followers_count") or (info.get("counters") or {}).get("followers"))
        return VkOwnerInfoDTO(name=display_name, description=info.get("about"), screen=screen, canonical_url=f"https://vk.com/{screen}", external_public_id=str(user_id), owner_id=user_id, members_count=followers)

    def resolve_post_owner(self, ref: VkLinkRef) -> VkOwnerInfoDTO:
        """Возвращает владельца одиночного поста."""

        if ref.owner_id is None:
            raise IngestionError("Не удалось определить owner_id поста")
        if ref.owner_id < 0:
            return self.resolve_community_owner(VkLinkRef(type=VkLinkType.COMMUNITY, raw_url=ref.raw_url, canonical_url=ref.canonical_url, owner_id=ref.owner_id, screen_name=ref.screen_name))
        return self.resolve_profile_owner(VkLinkRef(type=VkLinkType.PROFILE, raw_url=ref.raw_url, canonical_url=ref.canonical_url, owner_id=ref.owner_id, screen_name=ref.screen_name))
