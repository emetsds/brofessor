import json

import pytest

from brofessor import ui_language


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "brofessor" / "preferences.json"


@pytest.mark.parametrize(
    "browser,expected", [(None, "ru"), ("ru-RU", "ru"), ("en-US", "en"), ("fr-FR", "en")]
)
def test_first_visit_uses_browser_language_without_creating_settings(
    config_home, browser, expected
):
    assert ui_language.load_language(browser) == expected
    assert not config_home.exists()


def test_explicit_choice_overrides_browser_and_survives_reload(config_home):
    ui_language.save_language("en")
    assert ui_language.load_language("ru-RU") == "en"
    ui_language.save_language("ru")
    assert ui_language.load_language("en-US") == "ru"
    assert json.loads(config_home.read_text()) == {"ui_language": "ru"}


@pytest.mark.parametrize(
    "content", ["broken JSON", "[]", "null", '{"ui_language":"de"}', '{"ui_language":[]}']
)
def test_invalid_settings_do_not_prevent_opening_ui(config_home, content):
    config_home.parent.mkdir()
    config_home.write_text(content)
    assert ui_language.load_language("en-US") == "en"


def test_saving_language_preserves_other_preferences(config_home):
    config_home.parent.mkdir()
    config_home.write_text('{"existing_setting": "user choice"}')
    ui_language.save_language("en")
    assert json.loads(config_home.read_text()) == {
        "existing_setting": "user choice",
        "ui_language": "en",
    }


def test_rejects_unsupported_language_before_writing(config_home):
    with pytest.raises(ValueError):
        ui_language.save_language("de")
    assert not config_home.exists()
