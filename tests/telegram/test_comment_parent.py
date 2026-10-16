import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from backend.db import Comment
from backend.modules.telegram.client import TelegramCommentDTO
from backend.modules.telegram.repositories import TelegramIngestionRepository


async def test_newest_first_comments_keep_parent(monkeypatch):
    comments = []
    def add(item):
        if isinstance(item, Comment):
            item.id = uuid.uuid4()
            comments.append(item)

    dedup = SimpleNamespace(by_external_id={}, duplicate_id=lambda **kwargs: None, remember=lambda **kwargs: None)
    monkeypatch.setattr('backend.modules.telegram.repositories.load_comment_dedup_state', AsyncMock(return_value=dedup))
    db = SimpleNamespace(add=add, flush=AsyncMock())
    now = datetime.now(timezone.utc)
    imported = await TelegramIngestionRepository(db).upsert_comments(
        SimpleNamespace(id=uuid.uuid4()), 42,
        [TelegramCommentDTO(101, 'Ответ', '2', 'Автор', now, 100),
         TelegramCommentDTO(100, 'Вопрос', '1', 'Автор', now)],
    )
    assert imported == 2
    assert comments[0].external_id == '42:100'
    assert comments[1].parent_comment_id == comments[0].id
