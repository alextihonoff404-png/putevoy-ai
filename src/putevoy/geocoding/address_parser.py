"""Разбор «свободного» адреса на структурированные компоненты.

Используется при загрузке форм, чтобы существующий адрес из БД
(введённый когда-то одной строкой) разложить по полям UI.

Эвристика, не претендует на 100% точность — для сложных случаев
поля «название» получит всё что не удалось определить.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Канонический тип улицы и шаблоны для распознавания (полные и сокращённые формы)
STREET_TYPES = [
    ("проспект", [r"проспект", r"пр-т", r"пр\.", r"пр(?=\s|$)"]),
    ("переулок", [r"переулок", r"пер\."]),
    ("шоссе", [r"шоссе", r"ш\."]),
    ("набережная", [r"набережная", r"наб\."]),
    ("площадь", [r"площадь", r"пл\."]),
    ("бульвар", [r"бульвар", r"б-р", r"бул\."]),
    ("проезд", [r"проезд"]),
    ("тупик", [r"тупик"]),
    ("аллея", [r"аллея", r"ал\."]),
    ("микрорайон", [r"микрорайон", r"мкр\."]),
    # Улица — последняя в списке, потому что её сокращение «ул.» наиболее частое
    # и его проверка должна выполняться после более специфичных шаблонов.
    ("улица", [r"улица", r"ул\."]),
]


@dataclass
class AddressParts:
    city: str = ""
    street_type: str = "улица"
    street_name: str = ""
    house_number: str = ""
    corpus: str = ""

    def to_dict(self) -> dict:
        return {
            "city": self.city, "street_type": self.street_type,
            "street_name": self.street_name, "house_number": self.house_number,
            "corpus": self.corpus,
        }


def parse_address(address: str) -> AddressParts:
    """Разобрать строковый адрес на компоненты.

    Поддерживает форматы:
      - «Санкт-Петербург, ул. Репищева, д. 10, к3»
      - «Санкт-Петербург, ул. Репищева 10к3»
      - «Санкт-Петербург, Невский проспект 1»
      - «Санкт-Петербург, ул. Дыбенко, д. 8»
      - «Санкт-Петербург, Репищева 10»
    """
    if not address or not address.strip():
        return AddressParts()

    # Город — первый сегмент до запятой (если он содержит «,»),
    # иначе считаем, что города нет и всё — улица.
    parts = [p.strip() for p in address.split(",", 1)]
    if len(parts) == 2:
        city, rest = parts[0], parts[1]
    else:
        city, rest = "", parts[0]

    # Найдём тип улицы (где бы он ни стоял — до или после названия).
    # Регулярки заканчиваются lookahead'ом, чтобы корректно сматчить
    # «ул.» перед пробелом (после точки нет word-boundary к пробелу).
    found_type = "улица"
    type_found = False
    for canonical, patterns in STREET_TYPES:
        for pat in patterns:
            m = re.search(rf"\b{pat}(?=\s|,|$)", rest, flags=re.IGNORECASE)
            if m:
                found_type = canonical
                rest = (rest[:m.start()] + rest[m.end():])
                type_found = True
                break
        if type_found:
            break

    # Уберём «дом» / «д.» перед цифрой — это рудимент, который не важен дальше
    rest = re.sub(r"\bдом\b\s*(?=\d)", "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\bд\.\s*(?=\d)", "", rest, flags=re.IGNORECASE)

    house_number = ""
    corpus = ""

    # Пытаемся вытащить «дом + корпус» в любом из распространённых форматов:
    # «10к3», «10/3», «10 корпус 3», «10, корп. 3», «10, к3», «10 к. 3»
    m = re.search(
        r"(?<!\d)(\d+)[,\s]*(?:[/к]|корп\.?|корпус|к\.)\s*(\d+)(?!\d)",
        rest, flags=re.IGNORECASE,
    )
    if m:
        house_number = m.group(1)
        corpus = m.group(2)
        rest = rest[:m.start()] + rest[m.end():]
    else:
        # Только дом без корпуса — последнее число в строке
        m = re.search(r"(?<!\d)(\d+)(?!\d)\s*$", rest.strip(", "))
        if m:
            house_number = m.group(1)
            rest = rest[:m.start()].strip(", ")

    # То, что осталось — название улицы; чистим запятые и пробелы по краям
    street_name = re.sub(r"\s+", " ", rest).strip(" ,")

    return AddressParts(
        city=city, street_type=found_type, street_name=street_name,
        house_number=house_number, corpus=corpus,
    )


def compose_address(
    city: str, street_type: str, street_name: str,
    house_number: str, corpus: str = "",
) -> str:
    """Собрать структурированные компоненты обратно в строковый адрес.

    Формат: «Город, тип название номер[кN]» — без слова «дом», без запятых
    между номером и корпусом, что наиболее надёжно понимается OSM/Yandex.
    """
    house = house_number.strip()
    if corpus.strip():
        house += "к" + corpus.strip()
    street_part = " ".join(p for p in (street_type, street_name.strip(), house) if p)
    city = city.strip()
    return f"{city}, {street_part}" if city else street_part
