import json

import pytest

from backend.modules.analytics.utils import object_directory as od


@pytest.fixture()
def directory(tmp_path, monkeypatch):
    """Маленький справочник вместо боевого файла."""
    entries = [
        {"n": "МБОУ Средняя школа № 9", "a": "г. Енисейск, ул. Ленина, 1",
         "l": "Енисейск", "t": "school", "lat": 58.45, "lon": 92.17},
        {"n": "МБОУ Средняя школа № 19", "a": "г. Енисейск, ул. Мира, 2",
         "l": "Енисейск", "t": "school", "lat": 58.46, "lon": 92.18},
        {"n": "МБОУ Средняя школа № 9", "a": "г. Ачинск, ул. Ленина, 3",
         "l": "Ачинск", "t": "school", "lat": 56.27, "lon": 90.50},
        {"n": "Дивногорская межрайонная больница", "a": "г. Дивногорск, ул. Чкалова, 1",
         "l": "Дивногорск", "t": "med", "lat": 55.95, "lon": 92.37},
    ]
    path = tmp_path / "object_directory.json"
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(od, "DIRECTORY_PATH", path)
    monkeypatch.setattr(od, "_entries", None)
    monkeypatch.setattr(od, "_index", {})
    return od


def test_finds_school_by_number(directory):
    hit = directory.find_object("школа №9", "Енисейск")
    assert hit is not None
    assert hit.lat == 58.45


def test_number_is_matched_as_whole(directory):
    """«школа 9» не должна совпасть со школой 19."""
    hit = directory.find_object("школа 9", "Енисейск")
    assert hit is not None and "№ 9" in hit.name


def test_locality_separates_same_numbers(directory):
    """Один номер в разных городах — берётся город площадки."""
    assert directory.find_object("школа №9", "Ачинск").lon == pytest.approx(90.50)
    assert directory.find_object("школа №9", "Енисейск").lon == pytest.approx(92.17)


def test_without_locality_nothing_found(directory):
    """Без населённого пункта искать нельзя: школа №9 есть в двух десятках городов."""
    assert directory.find_object("школа №9", "") is None


def test_single_object_of_kind_matches_without_number(directory):
    """Единственная больница в городе двусмысленной быть не может."""
    hit = directory.find_object("около больницы", "Дивногорск")
    assert hit is not None and hit.kind == "med"


def test_unknown_locality_gives_nothing(directory):
    assert directory.find_object("школа №9", "Норильск") is None


def test_case_without_object_marker_ignored(directory):
    assert directory.find_object("улица Ленина", "Енисейск") is None


def test_missing_file_does_not_break(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "DIRECTORY_PATH", tmp_path / "нет.json")
    monkeypatch.setattr(od, "_entries", None)
    monkeypatch.setattr(od, "_index", {})
    assert od.find_object("школа №9", "Енисейск") is None
    assert od.available() is False


def test_single_object_rule_applies_only_to_hospitals(directory):
    """Единственная школа в справочнике не значит, что речь именно о ней.

    В округе школ много, а в открытых данных может быть только райцентровская —
    «Лебедевская школа Каратузского округа» иначе уехала бы в Каратузское.
    """
    assert directory.find_object("Лебедевская школа", "Ачинск") is None
    assert directory.find_object("около больницы", "Дивногорск") is not None


def test_locality_name_is_not_a_match(directory):
    """Название населённого пункта совпадением не считается.

    Иначе «Емельяновский район, Совхоз Сибиряк, школа» цепляется за любой
    емельяновский объект, хотя речь про школу в совхозе.
    """
    assert directory.find_object("Енисейская школа в посёлке", "Енисейск") is None


def test_administrations_are_not_objects(directory):
    """«Администрация города Дивногорска» — обрывок обращения к площадке.

    Ставить по такому кейсу точку на здание мэрии значит рисовать на карте
    несуществующую проблему.
    """
    assert directory.find_object("Администрация города Дивногорска", "Дивногорск") is None
