from ruangao_note.core.config import get_settings


def test_settings_read_environment_variables(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_NAME", "Test RuanGao")

    settings = get_settings()

    assert settings.app_name == "Test RuanGao"
    get_settings.cache_clear()
