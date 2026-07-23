from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .discovery import discover_candidates
from .extract import PRIVACY_NOTICE_PLACEHOLDER, extract_facts, extract_notice, extract_pdf_text
from .http import PoliteHttpClient
from .models import CrawlSettings, SourceConfig
from .storage import NoticeStore

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CrawlSummary:
    source_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    discovered: int = 0
    fetched: int = 0
    saved_or_changed: int = 0
    skipped_old: int = 0
    failed: int = 0
    list_pages_fetched: int = 0
    attachments_found: int = 0
    pdf_attachments: int = 0
    requests_made: int = 0
    cache_hits: int = 0
    robots_allowed: bool | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "list_pages_fetched": self.list_pages_fetched,
            "notices_discovered": self.discovered,
            "notices_fetched": self.fetched,
            "notices_failed": self.failed,
            "notices_skipped": self.skipped_old,
            "attachments_found": self.attachments_found,
            "pdf_attachments": self.pdf_attachments,
            "requests_made": self.requests_made,
            "cache_hits": self.cache_hits,
            "robots_allowed": self.robots_allowed,
            "field_extraction_accuracy": "not_manually_verified",
            "discovered": self.discovered,
            "fetched": self.fetched,
            "saved_or_changed": self.saved_or_changed,
            "skipped_old": self.skipped_old,
            "errors": self.errors,
        }


class CrawlPipeline:
    def __init__(
        self,
        settings: CrawlSettings,
        database_path: str | Path = "data/crawler/notices.sqlite3",
        cache_dir: str | Path = "data/crawler/cache",
    ):
        self.settings = settings
        self.database_path = Path(database_path)
        self.cache_dir = Path(cache_dir)

    def run_source(self, source: SourceConfig, since: date | None = None) -> CrawlSummary:
        summary = CrawlSummary(source_id=source.source_id)
        with PoliteHttpClient(self.settings, self.cache_dir) as client, NoticeStore(self.database_path) as store:
            try:
                if not source.enabled:
                    return summary

                discovery_stats: dict[str, int] = {}
                try:
                    candidates = discover_candidates(client, source, stats=discovery_stats)
                except Exception as exc:  # source-level isolation
                    summary.errors.append(f"list discovery failed: {type(exc).__name__}: {exc}")
                    return summary

                summary.list_pages_fetched = discovery_stats.get("list_pages_fetched", 0)
                summary.discovered = len(candidates)
                for candidate in candidates:
                    try:
                        result = client.fetch(candidate.url)
                        notice = extract_notice(result, candidate, source)
                        if notice.facts.privacy_sensitive:
                            client.purge_cache(candidate.url)
                        summary.attachments_found += len(notice.attachment_urls)
                        summary.pdf_attachments += sum(
                            url.lower().split("?", 1)[0].endswith(".pdf")
                            for url in notice.attachment_urls
                        )
                        if (
                            self.settings.download_pdf_text
                            and not notice.facts.privacy_sensitive
                            and notice.attachment_urls
                        ):
                            attachment_texts: list[str] = []
                            for attachment_url in notice.attachment_urls[:3]:
                                if not attachment_url.lower().split("?", 1)[0].endswith(".pdf"):
                                    continue
                                try:
                                    pdf_text = extract_pdf_text(
                                        client, attachment_url, max_bytes=self.settings.max_pdf_bytes
                                    ).strip()
                                    if pdf_text:
                                        attachment_texts.append(pdf_text[:30000])
                                except Exception as exc:
                                    summary.errors.append(
                                        f"attachment {attachment_url}: {type(exc).__name__}: {exc}"
                                    )
                            if attachment_texts:
                                combined_content = notice.content_text + "\n\n[官方附件文本]\n" + "\n".join(
                                    attachment_texts
                                )
                                notice.facts = extract_facts(
                                    notice.title, combined_content, notice.notice_type
                                )
                                if notice.facts.privacy_sensitive:
                                    for attachment_url in notice.attachment_urls:
                                        client.purge_cache(attachment_url)
                                notice.content_text = (
                                    PRIVACY_NOTICE_PLACEHOLDER
                                    if notice.facts.privacy_sensitive
                                    else combined_content
                                )
                                notice.content_sha256 = hashlib.sha256(
                                    combined_content.encode("utf-8")
                                ).hexdigest()
                        if since and notice.published_date and notice.published_date < since:
                            summary.skipped_old += 1
                            continue
                        summary.fetched += 1
                        if store.upsert(notice):
                            summary.saved_or_changed += 1
                        store.create_program_draft_from_notice(notice.notice_id)
                    except PermissionError as exc:
                        summary.failed += 1
                        summary.errors.append(str(exc))
                    except Exception as exc:  # one broken page must not stop the source
                        summary.failed += 1
                        LOGGER.exception("Failed to crawl %s", candidate.url)
                        summary.errors.append(f"{candidate.url}: {type(exc).__name__}: {exc}")
            finally:
                summary.finished_at = datetime.now(timezone.utc).isoformat()
                summary.requests_made = client.request_count
                summary.cache_hits = client.cache_hit_count
                summary.robots_allowed = client.robots_allowed
                store.record_run(summary.to_dict())
        return summary

    def run_many(self, sources: list[SourceConfig], since: date | None = None) -> list[CrawlSummary]:
        return [self.run_source(source, since=since) for source in sources if source.enabled]

    @staticmethod
    def write_summary(summaries: list[CrawlSummary], output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([item.to_dict() for item in summaries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
