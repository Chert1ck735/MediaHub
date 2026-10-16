"""Добор вероятных болей в эталонный набор (для recall/категорий).

Сэмплирует пользовательские (не community-authored) комменты подлиннее из «болевых»
пабликов, которых ещё нет в eval_set.jsonl. Помечает subset="augment".
Размечаются они так же агентами; нужны, т.к. в реалистичной выборке болей мало.

Запуск:  python -m tools.build_eval_augment [N]
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from backend.db.comments import Comment
from backend.db.database import async_session_maker
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.publications import Publication
from backend.db.social_networks import SocialNetwork

OUT_DIR = Path("data/eval")
# Шумные паблики (розыгрыши/благодарности/не муниципалка) — в доборе болей не нужны.
NOISE_PUBLICS = {"Красноярский Театр Пушкина", "Краевая клиническая больница",
                 "Благотворительный фонд Владимира Потанина"}


async def main(n: int) -> None:
    existing = set()
    p = OUT_DIR / "eval_set.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line)["comment_id"])

    async with async_session_maker() as session:
        rows = (await session.execute(
            select(Comment.id, Comment.text, Public.name.label("public_name"))
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Comment.is_deleted.is_(False))
            .where(SocialNetwork.code == "vk")
            .where(func.coalesce(Comment.author_external_id, "").not_like("-%"))  # не сообщество
            .where(func.length(func.coalesce(Comment.text, "")) > 120)
            .where(~Public.name.in_(NOISE_PUBLICS))
            .order_by(func.random())
            .limit(n * 3)
        )).all()

    picked = []
    for cid, text, public_name in rows:
        if str(cid) in existing:
            continue
        picked.append({
            "comment_id": str(cid), "public": public_name or "",
            "text": " ".join((text or "").split()),
            "subset": "augment",
            "sys_relevance": "", "sys_source": "", "sys_category": "",
            "sys_subcategory": "", "sys_case": "", "sys_msg_type": "",
            "gold_is_pain": "", "gold_category": "", "gold_subcategory": "",
            "gold_case": "", "gold_noise": "", "gold_notes": "",
        })
        if len(picked) >= n:
            break

    with (OUT_DIR / "augment.jsonl").open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "augment.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(picked[0].keys()))
        w.writeheader(); w.writerows(picked)
    print(f"Добрано {len(picked)} кандидатов в боли (пользовательские, >120 символов, из болевых пабликов)")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
