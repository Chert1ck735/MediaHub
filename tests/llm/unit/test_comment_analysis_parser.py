import json

from backend.modules.llm.services.comment_analysis_parser import CommentAnalysisParser


def test_parser_preserves_address_hierarchy():
    payload = {
        "relevance": "relevant",
        "author_type": "citizen",
        "message_type": "complaint",
        "sentiment": "negative",
        "is_official_response": False,
        "hierarchy": {
            "category": "ЖКХ и городская среда",
            "subcategory": "благоустройство",
            "case": "ул. Парковая 43",
        },
        "entities": {
            "address": "Назаровский муниципальный округ, ул. Парковая, 43",
            "address_hierarchy": {
                "municipality": "Назаровский муниципальный округ",
                "street": "ул. Парковая",
                "house": "43",
            },
            "institution": None,
            "reference_number": None,
            "deadline": None,
        },
        "summary": "",
    }

    parsed = CommentAnalysisParser().parse(json.dumps(payload, ensure_ascii=False))

    assert parsed.entities.address_hierarchy == {
        "municipality": "Назаровский муниципальный округ",
        "street": "ул. Парковая",
        "house": "43",
    }
