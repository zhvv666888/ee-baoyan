from __future__ import annotations

import re
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .http import PoliteHttpClient
from .models import CandidateLink, SourceConfig


def _normalized_domain(domain: str) -> str:
    return domain.lower().split(":", 1)[0]


def is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    host = _normalized_domain(urlparse(url).netloc)
    return any(host == _normalized_domain(item) or host.endswith("." + _normalized_domain(item)) for item in allowed_domains)


def _matches_detail_url(url: str, patterns: list[str]) -> bool:
    return not patterns or any(re.search(pattern, url) for pattern in patterns)


def _keyword_match(text: str, source: SourceConfig) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    if any(word.lower() in compact for word in source.exclude_keywords):
        return False
    return any(word.lower() in compact for word in source.include_keywords)


def discover_candidates(
    client: PoliteHttpClient,
    source: SourceConfig,
    stats: dict[str, int] | None = None,
) -> list[CandidateLink]:
    queue: deque[str] = deque(source.seed_urls)
    visited_list_pages: set[str] = set()
    discovered: dict[str, CandidateLink] = {}

    while queue and len(visited_list_pages) < source.max_list_pages:
        list_url = queue.popleft()
        if list_url in visited_list_pages:
            continue
        visited_list_pages.add(list_url)

        result = client.fetch(list_url)
        if stats is not None:
            stats["list_pages_fetched"] = stats.get("list_pages_fetched", 0) + 1
        soup = BeautifulSoup(result.text, "lxml")
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href", "")).strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            absolute = urldefrag(urljoin(result.url, href)).url
            if not is_allowed_domain(absolute, source.allowed_domains):
                continue

            title = " ".join(anchor.stripped_strings).strip()
            combined = f"{title} {absolute}"
            if _keyword_match(combined, source) and _matches_detail_url(absolute, source.detail_url_patterns):
                discovered.setdefault(
                    absolute,
                    CandidateLink(title=title or absolute, url=absolute, source_id=source.source_id, list_url=list_url),
                )
                continue

            anchor_text = re.sub(r"\s+", "", title).lower()
            looks_like_pagination = (
                any(keyword.lower() in anchor_text for keyword in source.pagination_keywords)
                or bool(re.fullmatch(r"\d{1,3}", anchor_text))
            )
            if looks_like_pagination and absolute not in visited_list_pages:
                queue.append(absolute)

        if len(discovered) >= source.max_notices_per_run:
            break

    return list(discovered.values())[: source.max_notices_per_run]
