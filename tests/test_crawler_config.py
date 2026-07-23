from pathlib import Path

from crawler.config import load_config


CONFIG = Path(__file__).parents[1] / "config" / "sources.official.json"


def test_user_agent_comes_from_environment_and_warns_without_formal_value(monkeypatch, caplog):
    monkeypatch.delenv("CRAWLER_USER_AGENT", raising=False)
    with caplog.at_level("WARNING"):
        settings, _ = load_config(CONFIG)
    assert "set CRAWLER_USER_AGENT before real crawling" in settings.user_agent
    assert "CRAWLER_USER_AGENT is not configured" in caplog.text

    monkeypatch.setenv("CRAWLER_USER_AGENT", "EECompassTest/1.0 (contact=test@example.com)")
    settings, _ = load_config(CONFIG)
    assert settings.user_agent == "EECompassTest/1.0 (contact=test@example.com)"
