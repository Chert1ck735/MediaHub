"""Каждый фильтр доезжает до каждого запроса.



Период, площадка и муниципалитет задаются на странице вместе. Если хоть один

не дошёл до запроса, числа в карточке, в списке подпроблемы и в отчёте

посчитаны по разным условиям — именно так недельные цифры оказывались рядом

со списком за всё время.

"""

import pathlib

import re

import uuid

from unittest.mock import MagicMock, patch



import pytest



from backend.modules.analytics.services.pain_slice_service import PainSliceService

from backend.modules.analytics.utils.public_link_filter import (

    parse_public_social_link_ids,

)

from backend.modules.analytics.utils.time_helpers import period_to_since



def _ui_periods() -> list[str]:

    """Периоды берём из интерфейса, а не переписываем руками.



    Иначе легко проверить период, которого в списке нет, и не заметить тот,

    который есть.

    """



    source = (

        pathlib.Path(__file__).resolve().parents[3]

        / "frontend" / "src" / "constants" / "status.ts"

    ).read_text(encoding="utf-8-sig")

    block = re.search(r"REPORT_PERIOD = \{(.*?)\}", source, re.S).group(1)

    return re.findall(r'"([^"]+)"', block)





PERIODS = _ui_periods()

SOURCE = str(uuid.uuid4())

MUNICIPALITY = "Ачинский муниципальный округ"





class _RecordingRepository:

    """Запоминает, с какими фильтрами пришёл каждый запрос."""



    def __init__(self):

        self.calls: list[tuple[str, dict]] = []



    def _record(self, name):

        async def call(_ids=None, **kwargs):

            self.calls.append((name, kwargs))

            return {} if name != "list_case_counts_by_pain" else []



        return call



    def __getattr__(self, name):

        return self._record(name)





def _service(repository):

    service = PainSliceService.__new__(PainSliceService)

    service._db = MagicMock()

    service._comment_repository = repository

    return service





@pytest.mark.asyncio

@pytest.mark.parametrize("period", PERIODS)

@pytest.mark.parametrize("source", [None, SOURCE])

@pytest.mark.parametrize("municipality", [None, MUNICIPALITY])

async def test_every_query_gets_every_filter(period, source, municipality):

    repository = _RecordingRepository()

    service = _service(repository)

    pain_ids = [uuid.uuid4()]



    since = period_to_since(period)

    link = parse_public_social_link_ids(source)

    filters = {"since": since, "link_id": link, "municipality_name": municipality}



    await service.count_mentions(pain_ids, **filters)

    await service.count_publications(pain_ids, **filters)

    await service.collect_comment_ids(pain_ids, **filters)

    await service.collect_comment_examples(pain_ids, **filters)

    await service.collect_top_cases(pain_ids, **filters)

    await service.case_merge_map(pain_ids, **filters)



    assert repository.calls, "ни один запрос не выполнился"

    for name, kwargs in repository.calls:

        assert kwargs.get("since") == since, f"{name}: период не доехал"

        assert kwargs.get("link_id") == link, f"{name}: площадка не доехала"

        if municipality is None:

            # Пустой фильтр территории не передаём — это отдельная ветка запроса.

            assert kwargs.get("municipality_name") is None, f"{name}: лишний фильтр территории"

        else:

            assert kwargs.get("municipality_name") == municipality, (

                f"{name}: муниципалитет не доехал"

            )





@pytest.mark.parametrize("period", PERIODS)

def test_every_ui_period_is_understood(period):

    """Каждый пункт выпадающего списка должен давать отсечку по времени.



    «За всё время» — единственное исключение. Непонятый бэкендом период

    молча превращается в «за всё время», и фильтр просто не работает.

    """



    since = period_to_since(period)

    if period == "all":

        assert since is None

    else:

        assert since is not None, f"период «{period}» из интерфейса не распознан"





def test_ui_offers_all_the_periods_we_expect():

    assert set(PERIODS) == {"week", "month", "3months", "6months", "year", "all"}



@pytest.mark.asyncio
@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("municipality", [None, MUNICIPALITY])
async def test_subproblem_addresses_get_the_same_filters(period, municipality):
    """Список «Адреса в подпроблеме» — третья поверхность с теми же числами."""

    from backend.modules.analytics.services.pain_detail_service import PainDetailService

    seen: list[dict] = []

    async def _rows(_pain_id, **kwargs):
        seen.append(kwargs)
        return []

    service = PainDetailService.__new__(PainDetailService)
    service._db = MagicMock()
    service._comment_repository = MagicMock()
    service._comment_repository.list_case_rows_for_pain = _rows

    since = period_to_since(period)
    link = parse_public_social_link_ids(SOURCE)

    with patch(
        "backend.modules.analytics.services.pain_detail_service.PainMapService",
        return_value=MagicMock(cache_snapshot=MagicMock(return_value={})),
    ):
        await service._live_cases_by_subcategory(
            uuid.uuid4(), link, since, municipality_name=municipality
        )

    assert seen, "запрос адресов подпроблемы не выполнился"
    assert seen[0]["since"] == since, "период не доехал"
    assert seen[0]["link_id"] == link, "площадка не доехала"
    if municipality is not None:
        assert seen[0]["municipality_name"] == municipality, "округ не доехал"
