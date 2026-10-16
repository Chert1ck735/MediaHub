from backend.modules.telegram.links.links import TelegramLinkRef, parse_telegram_link


class TelegramLinkParser:
    def parse(self, raw: str) -> TelegramLinkRef:
        return parse_telegram_link(raw)

