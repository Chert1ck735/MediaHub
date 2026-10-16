"""Отчёт считается по тем же фильтрам, что выбраны на странице.



Период, площадка и муниципалитет должны дойти до каждого блока отчёта:

сводки, разбора тем, блока «Требует внимания» и сравнения с прошлым

периодом. Иначе части отчёта посчитаны по разным условиям.

"""

import uuid

from datetime import datetime, timezone

from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock, patch



import pytest



from backend.modules.analytics.utils.time_helpers import period_to_since

from backend.modules.report.services.pdf_report_service import ReportPdfService



PERIODS = ["week", "month", "3months", "6months", "year", "all"]

SOURCE = f"{uuid.uuid4()},{uuid.uuid4()}"

MUNICIPALITY = "Ачинский муниципальный округ"





def _service():

    service = ReportPdfService.__new__(ReportPdfService)

    service._db = MagicMock()

    service._summary = MagicMock()

    service._summary.get_summary = AsyncMock(return_value={})

    service._pain_list = MagicMock()

    service._pain_list.list_pains = AsyncMock(return_value=[])

    service._burning_cases = AsyncMock(return_value=[])

    service._previous_period = AsyncMock(return_value=None)

    return service





@pytest.mark.asyncio

@pytest.mark.parametrize("period", PERIODS)

@pytest.mark.parametrize("municipality", [None, MUNICIPALITY])

async def test_filters_reach_every_block(period, municipality, tmp_path):

    service = _service()

    payload = SimpleNamespace(

        period=period, public_social_link_id=SOURCE, platform="vk",

        municipality_name=municipality,

    )



    with patch(

        "backend.modules.report.services.pdf_report_service.generate_municipality_pains_pdf",

        return_value=str(tmp_path / "report.pdf"),

    ):

        await service._generate_municipality_pains_pdf(

            SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()),

            payload,

            str(tmp_path / "report.pdf"),

            municipality_name=municipality,

        )



    checks = [

        ("сводка", service._summary.get_summary.await_args_list[0]),

        ("разбор тем", service._pain_list.list_pains.await_args),

        ("требует внимания", service._burning_cases.await_args),

        ("прошлый период", service._previous_period.await_args),

    ]

    for name, call in checks:

        assert call.kwargs["period"] == period, f"{name}: период не доехал"

        assert call.kwargs["public_social_link_id"] == SOURCE, f"{name}: площадка не доехала"

        assert call.kwargs["municipality_name"] == municipality, f"{name}: округ не доехал"





@pytest.mark.asyncio

async def test_krai_summary_is_taken_without_the_municipality():

    """Вторая сводка нужна для сравнения с краем — территорию к ней не применяем."""



    service = _service()

    payload = SimpleNamespace(

        period="week", public_social_link_id=None, platform="vk",

        municipality_name=MUNICIPALITY,

    )



    with patch(

        "backend.modules.report.services.pdf_report_service.generate_municipality_pains_pdf",

        return_value="report.pdf",

    ):

        await service._generate_municipality_pains_pdf(

            SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()),

            payload, "report.pdf", municipality_name=MUNICIPALITY,

        )



    krai = service._summary.get_summary.await_args_list[1]

    assert "municipality_name" not in krai.kwargs or krai.kwargs["municipality_name"] is None

    assert krai.kwargs["period"] == "week"





@pytest.mark.asyncio

@pytest.mark.parametrize("period", PERIODS)

async def test_previous_window_is_the_same_length_and_ends_where_this_one_starts(period):

    """«Стало больше или меньше» должно сравниваться с окном той же длины."""



    service = ReportPdfService.__new__(ReportPdfService)

    service._db = MagicMock()

    service._signals = MagicMock()

    service._signals.count_appeals = AsyncMock(return_value=7)

    service._signals.category_rows = AsyncMock(return_value=[])



    result = await service._previous_period(

        SimpleNamespace(id=uuid.uuid4()),

        period=period, public_social_link_id=SOURCE, municipality_name=MUNICIPALITY,

    )



    since = period_to_since(period)

    if since is None:

        assert result is None, "за всё время сравнивать не с чем"

        assert service._signals.count_appeals.await_count == 0

        return



    assert result == {"appeals": 7, "categories": {}}

    for call in (service._signals.count_appeals.await_args,

                 service._signals.category_rows.await_args):

        window = call.kwargs

        # Отсечка вычисляется от «сейчас», поэтому сравниваем с допуском.
        assert abs((window["until"] - since).total_seconds()) < 2, (
            "прошлое окно должно кончаться там, где начинается текущее"
        )

        # Длина окна совпадает с выбранным периодом с точностью до секунды.

        assert abs((since - window["since"]) - (datetime.now(timezone.utc) - since)).total_seconds() < 2

        assert window["municipality_name"] == MUNICIPALITY, "округ не доехал"

        assert window["link_id"] is not None, "площадка не доехала"

