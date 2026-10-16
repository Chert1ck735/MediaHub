"""Регистрация шрифтов с поддержкой кириллицы для ReportLab.

ReportLab по умолчанию не умеет в кириллицу — даёт «тофу» вместо букв.
Нужен TTF. Основной шрифт отчёта — PT Sans, он лежит в репозитории: макет
согласован именно в нём, а на сервере системных шрифтов нет. Если файлов не
окажется, берётся системный Arial, а за ним — DejaVuSans из поставки
matplotlib; имена в reportlab одни и те же, чтобы pdf_builder не зависел от
окружения и не падал KeyError('Arial').
"""
from __future__ import annotations

import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# backend/modules/report/utils/fonts.py -> backend/modules/report/assets/fonts
_BUNDLED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts"
)

# (имя в reportlab, файл PT Sans, файл Arial, файл DejaVu)
_FACES = (
    ("Arial", "PT_Sans-Web-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"),
    ("Arial-Bold", "PT_Sans-Web-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
    # Курсив в отчёте не используется, поэтому в репозиторий его не кладём.
    ("Arial-Italic", None, "ariali.ttf", "DejaVuSans-Oblique.ttf"),
    ("Arial-BoldItalic", None, "arialbi.ttf", "DejaVuSans-BoldOblique.ttf"),
)


def _mpl_ttf_dir() -> str | None:
    try:
        import matplotlib
        return os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
    except Exception:
        return None


def register_cyrillic_fonts() -> bool:
    """Регистрирует четыре начертания под именами Arial*.

    Возвращает True, только если зарегистрированы все четыре — иначе
    pdf_builder упадёт на отсутствующем имени.
    """

    win_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    mpl_dir = _mpl_ttf_dir()

    registered = 0
    for name, bundled, arial_file, dejavu_file in _FACES:
        candidates: list[str] = []
        if bundled:
            candidates.append(os.path.join(_BUNDLED_DIR, bundled))
        candidates.append(os.path.join(win_dir, arial_file))
        if mpl_dir:
            candidates.append(os.path.join(mpl_dir, dejavu_file))

        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                registered += 1
                break
            except Exception:
                continue
    return registered == len(_FACES)
