from __future__ import annotations

import uuid

import pytest
from sqlalchemy import column, select

from backend.modules.analytics.utils.public_link_filter import (
    apply_public_social_link_filter,
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)
from backend.modules.report.repositories.audience_repository import AudienceRepository
from backend.modules.report.repositories.post_repository import ReportPostRepository


class _EmptyResult:
    def all(self):
        return []


class _CapturingDb:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()


def _contains_parameter_value(statement, expected) -> bool:
    return any(value == expected for value in statement.compile().params.values())


def test_parse_csv_deduplicates_and_compacts_single_source():
    first = uuid.uuid4()
    second = uuid.uuid4()

    parsed = parse_public_social_link_ids(f" {first}, {second}, {first} ")

    assert parsed == [first, second]
    assert compact_public_social_link_filter([first]) == first
    assert compact_public_social_link_filter(parsed) == parsed


def test_parse_csv_rejects_invalid_uuid():
    with pytest.raises(ValueError):
        parse_public_social_link_ids(f"{uuid.uuid4()},not-a-uuid")


def test_apply_filter_uses_in_for_multiple_sources():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    statement = apply_public_social_link_filter(
        select(column("id")),
        column("source_id"),
        link_ids,
    )

    assert "source_id IN" in str(statement)
    assert _contains_parameter_value(statement, link_ids)


@pytest.mark.asyncio
async def test_report_post_repository_accepts_csv_sources():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    db = _CapturingDb()

    result = await ReportPostRepository(db).load_vk_posts(
        uuid.uuid4(),
        public_social_link_id=",".join(map(str, link_ids)),
        period="all",
    )

    assert result == []
    assert len(db.statements) == 1
    assert _contains_parameter_value(db.statements[0], link_ids)


@pytest.mark.asyncio
async def test_report_audience_repository_accepts_csv_sources():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    db = _CapturingDb()

    window, heatmap = await AudienceRepository(db).compute_activity(
        uuid.uuid4(),
        public_social_link_id=",".join(map(str, link_ids)),
        period="all",
    )

    assert window is None
    assert heatmap is None
    assert len(db.statements) == 1  # часовые/дневные итоги выводятся из общей heatmap
    assert all(_contains_parameter_value(statement, link_ids) for statement in db.statements)
