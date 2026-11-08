"""Keep user preferences, navigation and model resources out of the host account."""

import pytest


@pytest.fixture(autouse=True)
def isolated_user_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "user-data"))


@pytest.fixture
def preset_voices(monkeypatch):
    from tests.helpers.speech import install_presets

    return install_presets(monkeypatch)
