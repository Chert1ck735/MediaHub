"""Пропущенный период означает «за всё время», а не неделю.

Фронт при выборе «за всё время» не отправлял параметр, а ручки подставляли
неделю. В карточке за всё время выходило 6409 упоминаний, а в списке адресов
подпроблемы рядом — недельные 127.
"""
import pathlib
import re

from backend.modules.analytics.utils.time_helpers import period_to_since

BACKEND = pathlib.Path(__file__).resolve().parents[3] / "backend"
FRONTEND = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "api.ts"


def test_no_endpoint_defaults_to_a_week():
    guilty = []
    for path in BACKEND.rglob("router.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").split("\n"), 1):
            if re.search(r'period:\s*str\s*=\s*"week"', line):
                guilty.append(f"{path.name}:{number}")

    assert not guilty, f"пропущенный период молча даёт неделю: {guilty}"


def test_frontend_always_sends_the_period():
    """Иначе бэкенд не отличит «за всё время» от «параметр забыли»."""

    source = FRONTEND.read_text(encoding="utf-8-sig")

    assert 'period !== "all"' not in source, "период не отправляется при «за всё время»"


def test_all_means_no_time_filter():
    assert period_to_since("all") is None
    assert period_to_since(None) is None
    assert period_to_since("week") is not None
