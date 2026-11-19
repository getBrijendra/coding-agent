from coding_agent.config import Settings
from coding_agent.llm import OPENROUTER_BASE_URL, OPENROUTER_MODEL, create_model


def test_create_model_configures_openrouter(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("coding_agent.llm.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    create_model(Settings(data_dir=tmp_path, model_name=None))

    assert captured["model"] == OPENROUTER_MODEL
    assert captured["api_key"] == "test-openrouter-key"
    assert captured["base_url"] == OPENROUTER_BASE_URL


def test_configured_model_can_override_openrouter_default(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("coding_agent.llm.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    create_model(Settings(data_dir=tmp_path, model_name="openrouter/free"))

    assert captured["model"] == "openrouter/free"
