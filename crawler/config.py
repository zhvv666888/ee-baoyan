from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .models import CrawlSettings, SourceConfig


LOGGER = logging.getLogger(__name__)
DEV_USER_AGENT_MARKER = "set CRAWLER_USER_AGENT before real crawling"


def load_config(path: str | Path) -> tuple[CrawlSettings, list[SourceConfig]]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    settings_payload = dict(payload["global"])
    configured_user_agent = os.getenv("CRAWLER_USER_AGENT", "").strip()
    if configured_user_agent:
        settings_payload["user_agent"] = configured_user_agent
    elif DEV_USER_AGENT_MARKER in settings_payload.get("user_agent", ""):
        LOGGER.warning(
            "CRAWLER_USER_AGENT is not configured; crawler is using a development User-Agent."
        )
    settings = CrawlSettings.from_dict(settings_payload)
    sources = [SourceConfig.from_dict(item) for item in payload["sources"]]
    return settings, sources
