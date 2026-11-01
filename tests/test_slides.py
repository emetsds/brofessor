import copy

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE

from brofessor import media, service, worker
from brofessor.models import Slides
from brofessor.workspace import Workspace


def plan(citation="source:1", language="ru"):
    return {
        "title": "Grounded materials",
        "language": language,
        "slides": [
            {
                "title": "Доказательства / Evidence",
                "bullets": ["Испытана нагрузка 1200 кг", "Наводнение не проверялось"],
                "notes": "Original paragraph one.\n\nУточнение во втором абзаце.",
                "citations": [citation],
            },
            {
                "title": "Известное и неизвестное",
                "bullets": [],
                "notes": "A blank cell means unknown, not zero.",
                "citations": [citation],
                "table": {
                    "headers": ["Показатель", "Результат", "Ограничение"],
                    "rows": [
                        ["Нагрузка", "1200 кг", "Один тест"],
                        ["Наводнение", "", "Не проверялось"],
                    ],
                },
            },
            {
                "title": "Последовательность обработки",
                "bullets": ["Это последовательность действий, а не доказательство причинности"],
                "notes": "The labels remain editable.",
                "citations": [citation],
                "steps": ["Источник", "Проверка", "Результат"],
            },
        ],
    }


@pytest.mark.parametrize("language", ["ru", "en"])
def test_native_content_notes_fonts_and_editability(tmp_path, language):
    value = plan(language=language)
    value["slides"][0]["citations"] = [f"original-long-source-{i}:page{i}" for i in range(50)]
    before = copy.deepcopy(value)
    output = media.render_slides(
        value, tmp_path / "native.pptx", source_labels={"source:1": "chapter.md · page 1"}
    )
    deck = Presentation(output)
    assert value == before and len(deck.slides) == 3
    notes = deck.slides[0].notes_slide.notes_text_frame.text
    assert value["slides"][0]["notes"] in notes
    assert all(c in notes for c in value["slides"][0]["citations"])
    assert "chapter.md · page 1" in deck.slides[1].notes_slide.notes_text_frame.text
    assert not any(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes)
    for slide in deck.slides:
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0
            assert shape.left + shape.width <= deck.slide_width
            assert shape.top + shape.height <= deck.slide_height
    table = next(shape.table for shape in deck.slides[1].shapes if shape.has_table)
    assert table.cell(2, 1).text == ""
    assert table.cell(0, 0).text_frame.paragraphs[0].font.size.pt >= 18
    nodes = [
        s
        for s in deck.slides[2].shapes
        if s.shape_type == 1 and s.auto_shape_type == MSO_SHAPE.RECTANGLE
    ]
    arrows = [
        s
        for s in deck.slides[2].shapes
        if s.shape_type == 1 and s.auto_shape_type == MSO_SHAPE.CHEVRON
    ]
    assert [s.text for s in nodes] == value["slides"][2]["steps"] and len(arrows) == 2
    assert all(s.text_frame.paragraphs[0].font.size.pt >= 18 for s in nodes)
    table.cell(1, 1).text = "Изменённая ячейка"
    nodes[1].text = "Изменённый этап"
    deck.slides[2].notes_slide.notes_text_frame.text = "Изменённая заметка"
    edited = tmp_path / "edited.pptx"
    deck.save(edited)
    reopened = Presentation(edited)
    assert (
        next(s.table for s in reopened.slides[1].shapes if s.has_table).cell(1, 1).text
        == "Изменённая ячейка"
    )
    assert any(s.has_text_frame and s.text == "Изменённый этап" for s in reopened.slides[2].shapes)
    assert reopened.slides[2].notes_slide.notes_text_frame.text == "Изменённая заметка"


@pytest.mark.parametrize(
    "change,message",
    [
        (
            lambda slide: slide.update(table={"headers": ["A", "B"], "rows": [["only one"]]}),
            "match its headers",
        ),
        (lambda slide: slide.update(steps=["Only one"]), "2–5 steps"),
        (lambda slide: slide.update(steps=["", "Next"]), "must not be blank"),
        (
            lambda slide: slide.update(table={"headers": ["A"], "rows": [["B"]]}, steps=["A", "B"]),
            "not both",
        ),
    ],
)
def test_invalid_visual_content_is_rejected_before_publication(tmp_path, change, message):
    value = plan()
    change(value["slides"][0])
    output = tmp_path / "keep.pptx"
    output.write_bytes(b"previous output")
    with pytest.raises(ValueError, match=message):
        media.render_slides(value, output)
    assert output.read_bytes() == b"previous output" and list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("kind", ["title", "bullets", "table", "steps"])
def test_measured_overflow_preserves_previous_file_and_all_draft_text(tmp_path, kind):
    value = plan()
    if kind == "title":
        value["slides"][0]["title"] = "An excessively long heading " * 25
    elif kind == "bullets":
        value["slides"][0]["bullets"] = ["An extensive qualification " * 35] * 6
    elif kind == "table":
        value["slides"][1]["table"]["rows"][0][1] = "Long cell explanation " * 80
    else:
        value["slides"][2]["steps"][1] = "An unusually verbose process label " * 30
    before = copy.deepcopy(value)
    output = tmp_path / "keep.pptx"
    output.write_bytes(b"previous output")
    with pytest.raises(ValueError, match=r"Slide \d.*dense"):
        media.render_slides(value, output)
    assert value == before and output.read_bytes() == b"previous output"
    assert list(tmp_path.iterdir()) == [output]


def test_generated_visuals_survive_edit_and_worker_render_with_source_locations(
    tmp_path, monkeypatch
):
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "chapter.md"
    source.write_text("The bridge carried 1200 kg. Flood resistance was not tested.")
    w.add_source(source)
    citation = w.units()[0]["id"]
    value = plan(citation)
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **kw: value)
    job = service.submit(w, "slides", slide_count=3, start_worker=False)
    worker.run(w, once=True)
    assert w.job(job["id"])["status"] == "succeeded"
    saved = w.draft(job["id"])
    assert saved["data"]["slides"][1]["table"] == value["slides"][1]["table"]
    saved["data"]["slides"][2]["steps"][1] = "Сверка с источником"
    service.edit_draft(w, job["id"], saved["data"], 1)
    rendered = service.render(w, job["id"], start_worker=False)
    worker.run(w, once=True)
    assert w.job(rendered["id"])["status"] == "succeeded"
    artifact = w.artifacts(rendered["id"])[0]
    assert artifact["metadata"]["revision"] == 2
    deck = Presentation(w.path / artifact["path"])
    assert any(s.has_text_frame and s.text == "Сверка с источником" for s in deck.slides[2].shapes)
    assert "chapter.md" in deck.slides[0].notes_slide.notes_text_frame.text
    assert citation in deck.slides[0].notes_slide.notes_text_frame.text
    assert w.draft(job["id"], 1)["data"]["slides"][2]["steps"][1] == "Проверка"


def test_bullet_only_saved_draft_keeps_its_content_with_new_schema():
    value = plan()
    value["slides"] = value["slides"][:1]
    validated = Slides.model_validate(value).model_dump()
    assert validated["slides"][0]["bullets"] == value["slides"][0]["bullets"]
    assert validated["slides"][0]["table"] is None and validated["slides"][0]["steps"] == []


def test_long_russian_labels_use_a_readable_vertical_sequence(tmp_path):
    value = plan()
    value["slides"] = [value["slides"][2]]
    item = value["slides"][0]
    item["bullets"] = []
    item["steps"] = [
        "Любящее детство и мечта раскрыть тайны природы",
        "Университет: поддержка наставника и стремление превзойти предшественников",
        "Исследование жизни вытесняет здоровье и близких",
        "Создание оживает, Виктор в ужасе оставляет его",
        "Клерваль выхаживает Виктора, не зная его тайны",
    ]
    deck = Presentation(media.render_slides(value, tmp_path / "vertical.pptx"))
    shapes = [s for s in deck.slides[0].shapes if s.shape_type == 1]
    nodes = [s for s in shapes if s.auto_shape_type == MSO_SHAPE.RECTANGLE]
    assert [s.text for s in nodes] == item["steps"]
    assert sum(s.auto_shape_type == MSO_SHAPE.DOWN_ARROW for s in shapes) == 4
    assert all(s.text_frame.paragraphs[0].font.size.pt >= 18 for s in nodes)
    assert all(s.top + s.height <= deck.slide_height for s in shapes)
