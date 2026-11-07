"""The review uses original contexts and preserves accepted meanings/anchors."""

import copy
from types import SimpleNamespace

import pytest

from brofessor.contracts.content import ContentLanguage
from brofessor.features.books import terminology
from brofessor.infrastructure.formats.epub import TextBlock
from tests.helpers.books import payloads


def example():
    texts = {
        "definition": "Move the indicator; the database log stores entries.",
        "middle": "The indicator has a fine line.",
        "end": "Read the indicator after moving the slider.",
    }
    book = SimpleNamespace(
        language=ContentLanguage.EN,
        source_hash="frozen-source",
        blocks=[TextBlock(k, "chapter", k, text, {}) for k, text in texts.items()],
    )
    terms = [
        {
            "id": "journal",
            "term": "log",
            "sense": "database journal",
            "translation": "реестр",
            "origin": "user",
        }
    ]
    start = texts["definition"].index("log")
    occurrences = [
        {
            "id": "accepted",
            "term_id": "journal",
            "block_id": "definition",
            "start": start,
            "end": start + 3,
            "quote": texts["definition"],
            "surface": "log",
        }
    ]
    return book, terms, occurrences


def test_recurring_omitted_component_gets_grounded_meaning_without_rewriting_user_choice():
    book, terms, occurrences = example()
    before = copy.deepcopy((terms, occurrences))
    candidates = terminology.recurring_candidates(book, terms, occurrences)
    assert "indicator" in {c["surface"] for c in candidates}
    assert "log" not in {c["surface"] for c in candidates}

    def generate(prompt, schema, **kwargs):
        packet = payloads(prompt)[0]
        assert (
            next(t for t in packet["known_meanings"] if t["id"] == "journal")["translation"]
            == "реестр"
        )
        return {
            "assessed_blocks": [b["id"] for b in packet["blocks"]],
            "terms": [
                {
                    "term": "indicator",
                    "sense": "movable slide rule cursor",
                    "translation": "бегунок",
                    "existing_id": None,
                    "occurrences": [
                        {
                            "block_id": b["id"],
                            "quote": b["text"],
                            "surface": "indicator",
                            "match": 1,
                        }
                        for b in packet["blocks"]
                    ],
                }
            ],
        }

    result, linked = terminology.review_recurring(
        book, terms, occurrences, "ru", generate, lambda: None, lambda _: None
    )
    missing = next(t for t in result if t["term"] == "indicator")
    assert missing["translation"] == "бегунок"
    assert next(t for t in result if t["id"] == "journal") == terms[0]
    assert occurrences[0] in linked
    for o in linked:
        block = next(b for b in book.blocks if b.id == o["block_id"])
        assert block.text[o["start"] : o["end"]] == o["surface"]
    assert (terms, occurrences) == before


@pytest.mark.parametrize("fault", ["rewrite", "occupied", "invented"])
def test_review_does_not_publish_ungrounded_or_conflicting_additions(fault):
    book, terms, occurrences = example()
    before = copy.deepcopy((terms, occurrences))

    def generate(prompt, schema, **kwargs):
        packet = payloads(prompt)[0]
        proposal = {
            "term": "indicator",
            "sense": "movable cursor",
            "translation": "бегунок",
            "existing_id": None,
            "occurrences": [
                {
                    "block_id": "definition",
                    "quote": "invented quote",
                    "surface": "indicator",
                    "match": 1,
                }
            ],
        }
        if fault != "invented":
            proposal.update({k: terms[0][k] for k in ("term", "sense", "translation")})
            proposal["existing_id"] = terms[0]["id"]
            proposal["occurrences"] = [
                {
                    "block_id": "definition",
                    "quote": book.blocks[0].text,
                    "surface": "log",
                    "match": 1,
                }
            ]
            if fault == "rewrite":
                proposal["translation"] = "нежелательная замена"
        return {"assessed_blocks": [b["id"] for b in packet["blocks"]], "terms": [proposal]}

    with pytest.raises(ValueError):
        terminology.review_recurring(
            book, terms, occurrences, "ru", generate, lambda: None, lambda _: None
        )
    assert (terms, occurrences) == before


def test_alignment_repair_never_rewrites_changed_numbers():
    source = TextBlock("voltage", "chapter", "voltage", "Input 12 V.", {})
    value = {"blocks": [{"id": "voltage", "text": "Input 120 V.", "targets": []}]}

    def generate(*args, **kwargs):
        raise AssertionError("Numeric errors must not be sent for link repair")

    with pytest.raises(ValueError, match="numeric"):
        terminology.validate_or_repair_alignment(value, [source], [], [], generate)
