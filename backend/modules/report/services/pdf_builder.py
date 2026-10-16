"""Сборка финального PDF-отчёта через ReportLab.

Документ состоит из четырёх секций:
  1. Общая статистика (таблица метрик).
  2. Графики (PNG из ``charts/``).
  3. Рекомендации по контенту (текст от ``llm_recommendations_service``).
  4. Темы обсуждений — опционально, только если caller передал ``pains_data``.

Стили (Arial-cyrillic) регистрируются один раз в самом начале через
``utils.fonts.register_cyrillic_fonts``; без этого кириллица в PDF
превращается в «тофу».
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.modules.analytics.utils.case_extractor import (
    case_location_key,
    is_valid_case_title,
)
from backend.modules.report.utils.fonts import register_cyrillic_fonts

# Эмодзи и прочие символы вне шрифта → в PDF превращаются в «крокозябры» (□).
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⬀-⯿️‍]"
)

def _esc(value: object, limit: int | None = None) -> str:
    """Экранирует текст для reportlab Paragraph (& < > → сущности), чистит эмодзи, обрезает."""
    s = _EMOJI_RE.sub("", str(value or "")).strip()
    if limit is not None and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return _xml_escape(s)


_SEVERITY_LABELS = {
    "critical": "Критическая",
    "high": "Высокая",
    "medium": "Средняя",
    "low": "Низкая",
}


# Оформление отчёта главе округа — из согласованного макета.
_INK = colors.HexColor("#14171a")        # основной текст и жирные линейки
_MUTED = colors.HexColor("#6b6f76")      # подписи колонок и надзаголовки
_FAINT = colors.HexColor("#8a8f96")      # пояснения под цифрами
_RULE = colors.HexColor("#cfd3d8")       # линейки таблиц и разделители
_ACCENT = colors.HexColor("#9b2226")     # негатив и отставание от края
_SUBTLE = colors.HexColor("#4a4f56")     # подзаголовок в шапке


class _KickerLine(Flowable):
    """Надзаголовок по центру с разрядкой, без линейки."""

    def __init__(self, text: str, width: float, *, size: float = 7.4, spacing: float = 1.9):
        super().__init__()
        self.text = text.upper()
        self.width = width
        self.size = size
        self.spacing = spacing
        self.height = size * 1.2

    def draw(self) -> None:
        canvas_obj = self.canv
        canvas_obj.saveState()
        width = canvas_obj.stringWidth(self.text, "Arial", self.size)
        width += self.spacing * max(len(self.text) - 1, 0)
        text_obj = canvas_obj.beginText((self.width - width) / 2, 0)
        text_obj.setFont("Arial", self.size)
        text_obj.setFillColor(_MUTED)
        text_obj.setCharSpace(self.spacing)
        text_obj.textOut(self.text)
        canvas_obj.drawText(text_obj)
        canvas_obj.restoreState()


class _SectionHeading(Flowable):
    """Прописной заголовок раздела с разрядкой и линейкой под ним.

    ``ParagraphStyle`` принимает ``charSpace``, но при отрисовке его
    игнорирует — проверено. Настоящий межбуквенный интервал есть только у
    холста, поэтому заголовок рисуется напрямую, а не абзацем.
    """

    def __init__(self, text: str, width: float, *, size: float = 8.5, spacing: float = 1.3):
        super().__init__()
        self.text = text.upper()
        self.width = width
        self.size = size
        self.spacing = spacing
        self._gap = 1.2 * mm
        self.height = size * 1.15 + self._gap
        self.spaceBefore = 7 * mm
        self.spaceAfter = 3 * mm

    def draw(self) -> None:
        canvas_obj = self.canv
        canvas_obj.saveState()
        text_obj = canvas_obj.beginText(0, self._gap + self.size * 0.15)
        text_obj.setFont("Arial-Bold", self.size)
        text_obj.setFillColor(_INK)
        text_obj.setCharSpace(self.spacing)
        text_obj.textOut(self.text)
        canvas_obj.drawText(text_obj)
        canvas_obj.setStrokeColor(_INK)
        canvas_obj.setLineWidth(0.4)
        canvas_obj.line(0, 0, self.width, 0)
        canvas_obj.restoreState()


def _delta(now: int, before: int | None) -> str:
    """Изменение к прошлому периоду: «+41%», «−6%», «0%».

    Если в прошлом периоде был ноль, доля не определена — тогда показываем
    прирост в штуках.
    """

    if before is None:
        return ""
    if before == 0:
        return f"+{_fmt_int(now)}" if now else "0"
    change = round((now - before) / before * 100)
    if change == 0:
        return "0%"
    return f"{'+' if change > 0 else '−'}{abs(change)}%"


# С чем сравнивается динамика. Без этого «−27%» повисает в воздухе.
_PREVIOUS_PERIOD_LABELS = {
    "week": "к прошлой неделе",
    "month": "к прошлому месяцу",
    "three_months": "к прошлым 3 месяцам",
    "six_months": "к прошлому полугодию",
    "year": "к прошлому году",
}

_PERIOD_LABELS = {
    "week": "за неделю",
    "month": "за месяц",
    "three_months": "за 3 месяца",
    "six_months": "за полгода",
    "year": "за год",
    "all": "за всё время",
}


def _field(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _fmt_int(value: object) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _pct(value: object) -> str:
    try:
        return f"{float(value or 0):.0f}%"
    except (TypeError, ValueError):
        return "0%"


def _split_lines(text: str, *, limit: int = 420) -> list[str]:
    chunks: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        while len(line) > limit:
            pos = line.rfind(" ", 0, limit)
            if pos < 120:
                pos = limit
            chunks.append(line[:pos].strip())
            line = line[pos:].strip()
        if line:
            chunks.append(line)
    return chunks


def _page_footer(c: canvas.Canvas, doc: SimpleDocTemplate) -> None:
    c.saveState()
    c.setFont("Arial", 8)
    c.setFillColor(colors.HexColor("#7f8c8d"))
    c.drawRightString(doc.pagesize[0] - doc.rightMargin, 10 * mm, f"Стр. {doc.page}")
    c.restoreState()


def generate_pdf(
    platform: str,
    stats: dict,
    charts: list[str],
    recommendations: str,
    output_path: str = "report.pdf",
    pains_data: dict | None = None,
) -> str:
    """Собирает PDF-отчёт по площадке и возвращает путь к сохранённому файлу."""

    if not register_cyrillic_fonts():
        # Иначе reportlab упадёт глубоким KeyError('Arial') без намёка на причину.
        raise RuntimeError(
            "Не найдены TTF-шрифты с кириллицей (ни Arial, ни DejaVu из matplotlib) — "
            "PDF собрать нельзя. Проверьте, что на сервере установлен matplotlib."
        )

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )

    story: list = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleCustom", parent=styles["Title"],
        fontSize=20, spaceAfter=10, alignment=TA_CENTER,
        fontName="Arial-Bold",
    )
    h2_style = ParagraphStyle(
        "H2Custom", parent=styles["Heading2"],
        fontSize=14, spaceBefore=15, spaceAfter=8,
        textColor=colors.HexColor("#2C3E50"),
        fontName="Arial-Bold",
    )
    body_style = ParagraphStyle(
        "BodyCustom", parent=styles["Normal"],
        fontSize=11, leading=14, spaceAfter=6,
        fontName="Arial",
    )
    h3_style = ParagraphStyle(
        "H3Custom", parent=styles["Heading3"],
        fontSize=12, spaceBefore=8, spaceAfter=4,
        textColor=colors.HexColor("#34495E"), fontName="Arial-Bold",
    )
    small_style = ParagraphStyle(
        "SmallCustom", parent=styles["Normal"],
        fontSize=10, leading=13, spaceAfter=3, fontName="Arial",
    )
    quote_style = ParagraphStyle(
        "QuoteCustom", parent=styles["Normal"],
        fontSize=9.5, leading=12, spaceAfter=2, leftIndent=6 * mm,
        textColor=colors.HexColor("#555555"), fontName="Arial",
    )

    story.append(Paragraph(f"Аналитический отчёт: {platform}", title_style))
    story.append(Spacer(1, 5 * mm))

    # 1. Общая статистика.
    story.append(Paragraph("Общая статистика", h2_style))
    table_data = [["Метрика", "Значение"]]
    posts = int(stats.get("total_posts", 0) or 0)

    def _total(avg_key: str) -> int:
        return int(round(float(stats.get(avg_key, 0) or 0) * posts))

    metrics = [
        ("Всего постов", posts),
        ("Просмотров всего", _total("avg_views")),
        ("Максимум просмотров (пост)", stats.get("max_views", 0)),
    ]
    if "avg_likes" in stats:
        metrics.append(("Лайков всего", _total("avg_likes")))
        metrics.append(("Максимум лайков (пост)", stats.get("max_likes", 0)))
    if "avg_comments" in stats:
        metrics.append(("Комментариев всего", _total("avg_comments")))
        if "max_comments" in stats:
            metrics.append(("Максимум комментариев (пост)", stats.get("max_comments", 0)))
    if "group_members" in stats:
        metrics.append(("Подписчиков", stats.get("group_members", 0)))
    for label, value in metrics:
        table_data.append([label, str(value)])

    table = Table(table_data, colWidths=[80 * mm, 80 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ECF0F1")),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
        ("FONTNAME", (0, 1), (-1, -1), "Arial"),
        ("FONTSIZE", (0, 1), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 1, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    # 2. Графики.
    if charts:
        story.append(Paragraph("Графики", h2_style))
        for chart in charts:
            if Path(chart).exists():
                img = Image(chart, width=165 * mm, height=132 * mm)
                story.append(img)
                story.append(Spacer(1, 3 * mm))

    # 3. Рекомендации. Раздела нет, пока их не открыли в вебе: PDF берёт
    # готовый текст из кэша и сам в LLM не ходит.
    reco_lines = [line.strip() for line in recommendations.split("\n") if line.strip()]
    if reco_lines:
        story.append(PageBreak())
        story.append(Paragraph("Рекомендации по контенту", h2_style))
        for line in reco_lines:
            story.append(Paragraph(line, body_style))

    # 4. Темы обсуждений (опционально).
    if pains_data:
        story.append(PageBreak())
        story.append(Paragraph("Темы обсуждений (анализ комментариев пабликов)", h2_style))

        global_summary = pains_data.get("global_summary") or ""
        if global_summary:
            story.append(Paragraph(global_summary, body_style))
            story.append(Spacer(1, 4 * mm))

        counts = pains_data.get("counts") or {}
        if counts:
            counts_data = [
                ["Показатель", "Значение"],
                ["Релевантных комментариев", str(counts.get("relevant_comments", 0))],
                ["Обращений", str(counts.get("appeals", 0))],
                ["— из них жалоб", str(counts.get("complaints", 0))],
                ["— из них просьб", str(counts.get("requests", 0))],
                ["Благодарностей", str(counts.get("gratitude", 0))],
            ]
            t = Table(counts_data, colWidths=[100 * mm, 60 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("FONTNAME", (0, 1), (-1, -1), "Arial"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ECF0F1")),
                ("GRID", (0, 0), (-1, -1), 1, colors.white),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(t)
            story.append(Spacer(1, 5 * mm))

        pains = pains_data.get("pains") or []
        if pains:
            story.append(Paragraph("Топ проблем", h2_style))
            cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=10, leading=12, spaceAfter=0)
            pains_table_data = [["Проблема", "Серьёзность", "Упоминаний"]]
            for pain in pains[:10]:
                sev_raw = str(getattr(getattr(pain, "severity_level", None), "value", "") or "")
                sev = _SEVERITY_LABELS.get(sev_raw, sev_raw or "—")
                pains_table_data.append([
                    Paragraph(_esc(getattr(pain, "title", ""), 120), cell_style),
                    sev,
                    str(getattr(pain, "mentions_count", 0) or 0),
                ])
            pt = Table(pains_table_data, colWidths=[110 * mm, 35 * mm, 25 * mm])
            pt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (0, 1), (-1, -1), "Arial"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8F9FA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8F9FA"), colors.HexColor("#ECF0F1")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(pt)

        # Детализация по основным болям: подпроблемы, адресные кейсы и реальные
        # цитаты жителей. Данные из структурированного payload снапшота (ORM Pain
        # их не несёт) — отчёт показывает не только «сколько», но и «что писали».
        structured = pains_data.get("structured") or []
        if structured:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Детализация по основным болям", h2_style))
            for sp in structured[:5]:
                title = _esc(sp.get("title"))
                sev = _SEVERITY_LABELS.get(str(sp.get("severity_level") or ""), "")
                mentions = int(sp.get("mentions_count") or 0)
                pubs = int(sp.get("publications_count") or 0)
                head = (
                    f"{title} — {sev}, {mentions} упоминаний, {pubs} публикаций"
                    if sev else f"{title} — {mentions} упоминаний"
                )
                story.append(Paragraph(head, h3_style))

                subs = sp.get("subproblem_items") or []
                if subs:
                    sub_line = ", ".join(
                        f"{_esc(s.get('title'))} ({int(s.get('mentions_count') or 0)})"
                        for s in sorted(subs, key=lambda x: int(x.get("mentions_count") or 0), reverse=True)[:6]
                        if s.get("title")
                    )
                    if sub_line:
                        story.append(Paragraph(f"<b>Подпроблемы:</b> {sub_line}", small_style))

                # Адресные кейсы со всех подпроблем + дедуп по нормализованной
                # локации (на случай старых снапшотов до дедупа в источнике).
                merged: dict[str, list] = {}
                for s in subs:
                    for case in (s.get("cases") or []):
                        ct = str(case.get("title") or "").strip()
                        # Пропускаем не-адреса: названия категорий/подкатегорий и
                        # прочий мусор, который LLM кладёт в case (как в UI).
                        if not ct or not is_valid_case_title(ct):
                            continue
                        key = case_location_key(ct) or ct.lower()
                        if key in merged:
                            merged[key][1] += int(case.get("mentions_count") or 0)
                        else:
                            merged[key] = [ct, int(case.get("mentions_count") or 0)]
                cases_sorted = sorted(merged.values(), key=lambda x: x[1], reverse=True)[:6]
                if cases_sorted:
                    cline = ", ".join(f"{_esc(t)} ({n})" for t, n in cases_sorted)
                    story.append(Paragraph(f"<b>Адресные кейсы:</b> {cline}", small_style))

                # 2-3 реальные цитаты: сперва живые тексты комментариев, при их
                # отсутствии — короткие сигнальные выжимки жалоб/запросов.
                quotes: list[str] = []
                for ex in (sp.get("comment_examples") or []):
                    t = str(ex.get("text") or "").strip()
                    if t:
                        quotes.append(t)
                    if len(quotes) >= 3:
                        break
                if not quotes:
                    pool = list(sp.get("complaint_examples") or []) + list(sp.get("request_examples") or [])
                    quotes = [str(x).strip() for x in pool if str(x).strip()][:3]
                if quotes:
                    story.append(Paragraph("<b>Примеры:</b>", small_style))
                    for q in quotes:
                        story.append(Paragraph(f"«{_esc(q, 300)}»", quote_style))
                story.append(Spacer(1, 3 * mm))

    doc.build(story)
    return output_path


def generate_municipality_pains_pdf(
    *,
    municipality_name: str | None,
    period: str,
    summary: object,
    pains: list[object],
    output_path: str,
    source_label: str | None = None,
    krai_summary: object | None = None,
    burning_cases: list[dict] | None = None,
    previous: dict | None = None,
) -> str:
    """PDF о сообщениях аудитории: по одному округу или по всем сразу.

    ``municipality_name=None`` — округ не выбран, отчёт по всей территории.
    ``krai_summary`` — та же сводка без фильтра территории, чтобы показать,
    как округ смотрится на фоне края. Без неё блок сравнения не печатается.
    """

    if not register_cyrillic_fonts():
        raise RuntimeError(
            "Не найдены TTF-шрифты с кириллицей (ни Arial, ни DejaVu из matplotlib) — "
            "PDF собрать нельзя. Проверьте, что на сервере установлен matplotlib."
        )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MunicipalityTitle",
        parent=styles["Title"],
        fontName="Arial-Bold",
        fontSize=15,
        leading=17,
        alignment=TA_CENTER,
        textColor=_INK,
        spaceBefore=0,
        spaceAfter=1.4 * mm,
    )
    subtitle_style = ParagraphStyle(
        "MunicipalitySubtitle",
        parent=styles["Normal"],
        fontName="Arial",
        fontSize=8.4,
        leading=10,
        alignment=TA_CENTER,
        textColor=_SUBTLE,
        spaceAfter=0,
    )
    body_style = ParagraphStyle(
        "MunicipalityBody",
        parent=styles["Normal"],
        fontName="Arial",
        fontSize=8.8,
        leading=11.6,
        textColor=_INK,
        spaceAfter=3,
    )
    small_style = ParagraphStyle(
        "MunicipalitySmall",
        parent=styles["Normal"],
        fontName="Arial",
        fontSize=7.8,
        leading=10,
        textColor=_INK,
        spaceAfter=1.4,
    )
    note_style = ParagraphStyle(
        "MunicipalityNote",
        parent=styles["Normal"],
        fontName="Arial",
        fontSize=7,
        leading=9,
        textColor=_FAINT,
        spaceAfter=0,
    )
    cell_style = ParagraphStyle(
        "MunicipalityCell",
        parent=styles["Normal"],
        fontName="Arial",
        fontSize=8.8,
        leading=10.5,
        textColor=_INK,
        spaceAfter=0,
    )
    cell_bold_style = ParagraphStyle(
        "MunicipalityCellBold",
        parent=cell_style,
        fontName="Arial-Bold",
    )
    cell_muted_style = ParagraphStyle(
        "MunicipalityCellMuted",
        parent=cell_style,
        textColor=_MUTED,
    )
    cell_accent_style = ParagraphStyle(
        "MunicipalityCellAccent",
        parent=cell_style,
        textColor=_ACCENT,
    )
    cell_accent_bold_style = ParagraphStyle(
        "MunicipalityCellAccentBold",
        parent=cell_accent_style,
        fontName="Arial-Bold",
    )
    cell_head_style = ParagraphStyle(
        "MunicipalityCellHead",
        parent=styles["Normal"],
        fontName="Arial-Bold",
        fontSize=7.4,
        leading=9,
        textColor=_MUTED,
        spaceAfter=0,
    )
    quote_style = ParagraphStyle(
        "MunicipalityQuote",
        parent=small_style,
        leftIndent=4 * mm,
        textColor=_SUBTLE,
    )

    def _section(title: str) -> Flowable:
        return _SectionHeading(title, 180 * mm)

    story: list = []
    period_label = _PERIOD_LABELS.get(str(period or "all"), str(period or "all"))
    source_text = source_label or "все площадки"
    # Выбранных округов может быть несколько — приходят через запятую.
    scope_names = [part.strip() for part in str(municipality_name or "").split(",") if part.strip()]
    if not scope_names:
        scope_title = "все муниципалитеты"
    elif len(scope_names) <= 3:
        scope_title = _esc(", ".join(scope_names))
    else:
        scope_title = _esc(f"{', '.join(scope_names[:2])} и ещё {len(scope_names) - 2}")
    scope_title_plain = ", ".join(scope_names) if scope_names else "Все муниципалитеты"
    story.append(_KickerLine("Система мониторинга и анализа пабликов", 180 * mm))
    story.append(Spacer(1, 2.4 * mm))
    # Название и период — в рамке из двух линеек, как в макете.
    header = Table(
        [
            [Paragraph(f"Обращения жителей: {scope_title}", title_style)],
            [Paragraph(
                f"{_esc(period_label)} · {_esc(source_text, 120)}",
                subtitle_style,
            )],
        ],
        colWidths=[180 * mm],
    )
    header.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, _INK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, _INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, 0), 2.6 * mm),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 2 * mm),
    ]))
    story.append(header)
    story.append(Spacer(1, 5.5 * mm))

    classified = int(_field(summary, "classified_comment_count", 0) or 0)
    appeals = int(_field(summary, "appeal_count", 0) or 0)
    sla = _field(summary, "sla", {}) or {}

    story.append(_section("Главное за период"))

    prev_appeals = previous.get("appeals") if previous else None
    appeals_delta = _delta(appeals, prev_appeals)
    versus = _PREVIOUS_PERIOD_LABELS.get(str(period or "").lower().strip(), "")
    sla_hours = int(float(_field(sla, "sla_hours", 48) or 48))
    krai_sla = _field(krai_summary, "sla", {}) or {} if krai_summary is not None else {}

    own_rate = float(_field(sla, "response_rate", 0) or 0)
    krai_rate = float(_field(krai_sla, "response_rate", 0) or 0) if krai_sla else None
    gap = own_rate - krai_rate if krai_rate is not None else None

    # Каждый показатель — три строки: подпись, число, пояснение под ним.
    def _kpi(label: str, value: str, note: str, *, delta: str = "", alarm: bool = False):
        value_color = "#9b2226" if alarm else "#14171a"
        head = f'<font size="22" color="{value_color}"><b>{_esc(value)}</b></font>'
        if delta:
            head += f'  <font size="8.6" color="#9b2226"><b>{_esc(delta)}</b></font>'
        return [
            Paragraph(label.upper(), cell_head_style),
            Paragraph(head, ParagraphStyle("kpi", parent=body_style, leading=24, spaceAfter=0)),
            Paragraph(_esc(note), note_style),
        ]

    columns = [
        _kpi("Обращений жителей", _fmt_int(appeals), versus, delta=appeals_delta),
        _kpi("Из них отвечено", _fmt_int(_field(sla, "answered", 0)), "обращения"),
        _kpi(
            "Доля ответов",
            _pct(own_rate),
            f"к краевой доле {_pct(krai_rate)}" if krai_rate is not None else "от всех обращений",
            delta=f"{gap:+.0f} п.п.".replace("+-", "−") if gap is not None and abs(gap) >= 1 else "",
            alarm=gap is not None and gap < -1,
        ),
        _kpi(
            f"Ответов за {sla_hours} часов",
            _pct(_field(sla, "within_sla_rate", 0)),
            f"по краю — {_pct(_field(krai_sla, 'within_sla_rate', 0))}" if krai_sla else "из отвеченных",
        ),
    ]
    metric_table = Table([list(row) for row in zip(*columns)], colWidths=[45 * mm] * 4)
    metric_table.setStyle(TableStyle([
        ("LINEBEFORE", (1, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-2, -1), 4 * mm),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(metric_table)
    story.append(Spacer(1, 2.4 * mm))
    story.append(Paragraph(
        _esc(f"Отчёт построен на {_fmt_int(classified)} комментариях жителей {period_label}."),
        note_style,
    ))

    burning = list(burning_cases or [])
    if burning:
        story.append(_section("Требует внимания"))
        rows = [[
            Paragraph("АДРЕС", cell_head_style),
            Paragraph("НЕГАТИВНЫХ", cell_head_style),
            Paragraph("ВСЕГО ОБРАЩЕНИЙ", cell_head_style),
        ]]
        for item in burning:
            rows.append([
                Paragraph(_esc(item.get("title", ""), 90), cell_style),
                Paragraph(_fmt_int(item.get("negative", 0)), cell_accent_bold_style),
                Paragraph(_fmt_int(item.get("mentions", 0)), cell_style),
            ])
        burning_table = Table(rows, colWidths=[137 * mm, 23 * mm, 20 * mm], repeatRows=1)
        burning_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, _INK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, _RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("LEFTPADDING", (1, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-2, -1), 2 * mm),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1.2 * mm),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 2 * mm),
        ]))
        story.append(burning_table)

    all_categories = list(_field(summary, "category_breakdown", []) or [])
    categories_total = sum(int(_field(item, "count", 0) or 0) for item in all_categories)
    counts_by_category = {
        str(_field(item, "category", "") or "").strip().lower(): int(_field(item, "count", 0) or 0)
        for item in all_categories
    }
    top_pains = sorted(pains, key=lambda p: int(_field(p, "mentions_count", 0) or 0), reverse=True)[:12]

    # Тема и категория — одна и та же сущность, поэтому таблица одна. Счётчик
    # обращений берём из разбивки по категориям: он сходится с числом в шапке,
    # тогда как счётчик боли считает по другой базе и расходится на единицы.
    extra_by_category: dict[str, tuple[int, int]] = {}
    for pain in top_pains:
        key = str(_field(pain, "category", "") or _field(pain, "title", "") or "").strip().lower()
        posts, addresses = extra_by_category.get(key, (0, 0))
        extra_by_category[key] = (
            posts + int(_field(pain, "publications_count", 0) or 0),
            addresses + int(_field(pain, "cases_count", 0) or 0),
        )

    # Доля той же темы по всему краю: 30% про дороги — это много или обычно.
    krai_categories = list(_field(krai_summary, "category_breakdown", []) or []) if krai_summary is not None else []
    krai_total = sum(int(_field(item, "count", 0) or 0) for item in krai_categories)
    krai_share = {
        str(_field(item, "category", "") or "").strip().lower():
            int(_field(item, "count", 0) or 0) / krai_total * 100
        for item in krai_categories
    } if krai_total else {}

    story.append(_section("О чём пишут жители"))
    if not all_categories:
        story.append(Paragraph(f"За период обращений не найдено ({scope_title}).", body_style))
    else:
        head = [
            Paragraph("ТЕМА", cell_head_style),
            Paragraph("ОБРАЩЕНИЙ", cell_head_style),
            Paragraph("ДОЛЯ", cell_head_style),
        ]
        widths = [45 * mm, 22 * mm, 12 * mm]
        prev_categories = (previous or {}).get("categories") or {}
        if prev_categories:
            head.append(Paragraph(
                _esc(versus.upper()) if versus else "ДИНАМИКА", cell_head_style
            ))
            widths.append(28 * mm)
        if krai_share:
            head.append(Paragraph("ПО КРАЮ", cell_head_style))
            widths.append(17 * mm)
        head += [
            Paragraph("НЕГАТИВНЫХ", cell_head_style),
            Paragraph("ПОСТОВ", cell_head_style),
            Paragraph("АДРЕСОВ", cell_head_style),
        ]
        widths += [23 * mm, 16 * mm, 17 * mm]
        widths[0] += 170 * mm - sum(widths)

        # Темы меньше процента занимают строку и ничего не говорят: «Другое 1,
        # 0%». Первую всё равно оставляем, даже если объём совсем мал.
        shown_categories = [
            item for item in all_categories[:10]
            if not categories_total
            or int(_field(item, "count", 0) or 0) / categories_total >= 0.01
        ] or all_categories[:1]

        # Красным выделяем то, на что смотреть: рост обращений и самый
        # крупный негатив. Доля по краю — серым, это фон для сравнения.
        def _accent(text: str, *, bold: bool = True) -> Paragraph:
            style = cell_accent_bold_style if bold else cell_accent_style
            return Paragraph(_esc(text), style)

        worst_negative = max(
            (int(_field(item, "negative_count", 0) or 0) for item in shown_categories),
            default=0,
        )

        rows = [head]
        for item in shown_categories:
            name = str(_field(item, "category", "Без категории") or "Без категории")
            count = int(_field(item, "count", 0) or 0)
            neg = int(_field(item, "negative_count", 0) or 0)
            posts, addresses = extra_by_category.get(name.strip().lower(), (0, 0))
            row = [
                Paragraph(_esc(name, 80), cell_bold_style),
                Paragraph(_fmt_int(count), cell_bold_style),
                Paragraph(_pct(count / categories_total * 100) if categories_total else "—", cell_style),
            ]
            if prev_categories:
                change = _delta(count, prev_categories.get(name.strip().lower()))
                row.append(
                    _accent(change) if change.startswith("+")
                    else Paragraph(_esc(change or "—"), cell_style)
                )
            if krai_share:
                share = krai_share.get(name.strip().lower())
                row.append(Paragraph(
                    _pct(share) if share is not None else "—", cell_muted_style
                ))
            row += [
                _accent(_fmt_int(neg)) if neg and neg == worst_negative
                else Paragraph(_fmt_int(neg), cell_style),
                Paragraph(_fmt_int(posts) if posts else "—", cell_style),
                Paragraph(_fmt_int(addresses) if addresses else "—", cell_style),
            ]
            rows.append(row)
        topics_table = Table(rows, colWidths=widths, repeatRows=1)
        topics_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, _INK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, _RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("LEFTPADDING", (1, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-2, -1), 2 * mm),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1.2 * mm),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 2 * mm),
        ]))
        story.append(topics_table)

    story.append(_section("Детализация по ведущим темам"))

    detail_title_style = ParagraphStyle(
        "MunicipalityDetailTitle",
        parent=styles["Normal"],
        fontName="Arial-Bold",
        fontSize=9.6,
        leading=11.5,
        textColor=_INK,
        spaceAfter=0,
    )
    detail_meta_style = ParagraphStyle(
        "MunicipalityDetailMeta",
        parent=note_style,
        alignment=TA_RIGHT,
    )

    for idx, pain in enumerate(top_pains[:6], start=1):
        # Название темы и её показатели в одной строке: слева заголовок,
        # справа сводка, как в макете.
        # Число берём из той же разбивки, что и таблица выше: счётчик боли
        # считает по другой базе и расходился с ней на сотни.
        theme_count = counts_by_category.get(
            str(_field(pain, "category", "") or _field(pain, "title", "") or "").strip().lower(),
            int(_field(pain, "mentions_count", 0) or 0),
        )
        meta = " · ".join(
            part for part in (
                f"{_fmt_int(theme_count)} обращений",
                _pct(theme_count / categories_total * 100) if categories_total else "",
                f"{_fmt_int(_field(pain, 'cases_count', 0))} адресов"
                if int(_field(pain, "cases_count", 0) or 0) else "",
            ) if part
        )
        head_row = Table(
            [[
                Paragraph(f"{idx}. {_esc(_field(pain, 'title', ''), 150)}", detail_title_style),
                Paragraph(_esc(meta), detail_meta_style),
            ]],
            colWidths=[118 * mm, 62 * mm],
        )
        head_row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ]))
        story.append(head_row)

        # С числом упоминаний: без него список подпроблем не говорит, что
        # из перечисленного главное.
        counted = [
            (str(_field(item, "title", "") or "").strip(), int(_field(item, "mentions_count", 0) or 0))
            for item in list(_field(pain, "subproblem_items", []) or [])
        ]
        counted = [(title, n) for title, n in counted if title]
        if counted:
            counted.sort(key=lambda pair: pair[1], reverse=True)
            sub_line = ", ".join(f"{title} ({n})" if n else title for title, n in counted[:5])
        else:
            plain = [str(x).strip() for x in list(_field(pain, "subproblems", []) or []) if str(x).strip()]
            sub_line = ", ".join(plain[:5])
        if sub_line:
            story.append(Paragraph(f"<b>Из чего складывается:</b> {_esc(sub_line, 300)}", small_style))

        cases = list(_field(pain, "top_cases", []) or [])[:5]
        if cases:
            # Счётчик в скобках — только когда он о чём-то говорит.
            case_parts = []
            for case in cases:
                if not _field(case, "title", None):
                    continue
                title = _esc(_field(case, "title", ""), 70)
                mentions = int(_field(case, "mentions_count", 0) or 0)
                case_parts.append(f"{title} ({_fmt_int(mentions)})" if mentions else title)
            case_line = ", ".join(case_parts)
            if case_line:
                story.append(Paragraph(f"<b>Адреса:</b> {case_line}", small_style))

        examples = list(_field(pain, "comment_examples", []) or [])[:2]
        shown = [
            (str(_field(e, "text", "") or "").strip(), str(_field(e, "url", "") or "").strip())
            for e in examples
            if str(_field(e, "text", "") or "").strip()
        ]
        if shown:
            story.append(Paragraph("<b>Комментарии жителей:</b>", small_style))
            for text, url in shown:
                body = f"«{_esc(text, 260)}»"
                # Ссылка ведёт на исходный комментарий в VK — по PDF кликается.
                if url:
                    body = f'<link href="{_esc(url)}" color="#2f5d8a">{body}</link>'
                story.append(Paragraph(body, quote_style))
        story.append(Spacer(1, 2 * mm))

    def _footer(canvas_obj, doc_obj):
        """Слева территория и период, по центру номер, справа дата."""
        canvas_obj.saveState()
        canvas_obj.setFont("Arial", 7)
        canvas_obj.setFillColor(_FAINT)
        bottom = 8 * mm
        left = doc_obj.leftMargin
        right = doc_obj.pagesize[0] - doc_obj.rightMargin
        canvas_obj.drawString(left, bottom, f"{scope_title_plain} · {period_label}")
        canvas_obj.drawCentredString((left + right) / 2, bottom, f"— {doc_obj.page} —")
        canvas_obj.drawRightString(
            right, bottom, f"составлен {datetime.now().strftime('%d.%m.%Y')}"
        )
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output_path
