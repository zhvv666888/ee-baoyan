import sqlite3
from datetime import datetime, timezone

from crawler import pipeline as pipeline_module
from crawler.http import FetchResult
from crawler.models import CandidateLink, CrawledNotice, CrawlSettings, ExtractedFacts, SourceConfig


class FakeClient:
    request_count = 2
    cache_hit_count = 0
    robots_allowed = True

    def __init__(self, *_args, **_kwargs):
        self.purged: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def fetch(self, url: str, **_kwargs):
        return FetchResult(url, 200, b"<html></html>", "text/html", False)

    def purge_cache(self, url: str):
        self.purged.append(url)


def test_sensitive_pdf_text_is_not_persisted(monkeypatch, tmp_path):
    pdf_url = "https://example.edu.cn/files/results.pdf"
    candidate = CandidateLink(
        title="普通通知",
        url="https://example.edu.cn/notice/1.htm",
        source_id="test-source",
        list_url="https://example.edu.cn/notices.htm",
    )
    notice = CrawledNotice(
        notice_id="notice-1",
        source_id="test-source",
        school="某大学",
        college="信息学院",
        title="普通通知",
        url=candidate.url,
        published_date=None,
        data_year=2026,
        notice_type="other",
        content_text="普通正文",
        content_sha256="before",
        fetched_at=datetime.now(timezone.utc),
        facts=ExtractedFacts(),
        attachment_urls=[pdf_url],
    )
    fake_client = FakeClient()
    monkeypatch.setattr(pipeline_module, "PoliteHttpClient", lambda *_args, **_kwargs: fake_client)
    monkeypatch.setattr(
        pipeline_module,
        "discover_candidates",
        lambda _client, _source, stats=None: (stats.update(list_pages_fetched=1) if stats is not None else None) or [candidate],
    )
    monkeypatch.setattr(pipeline_module, "extract_notice", lambda *_args: notice)
    monkeypatch.setattr(pipeline_module, "extract_pdf_text", lambda *_args, **_kwargs: "姓名 学号 成绩 黄浩珉 61822105 88")

    settings = CrawlSettings(user_agent="test-agent")
    source = SourceConfig(
        source_id="test-source",
        school="某大学",
        college="信息学院",
        seed_urls=[candidate.list_url],
        allowed_domains=["example.edu.cn"],
        include_keywords=["通知"],
    )
    pipeline = pipeline_module.CrawlPipeline(
        settings,
        database_path=tmp_path / "notices.sqlite3",
        cache_dir=tmp_path / "cache",
    )
    pipeline.run_source(source)

    row = sqlite3.connect(tmp_path / "notices.sqlite3").execute(
        "select content_text from notices where notice_id='notice-1'"
    ).fetchone()
    assert row[0].startswith("[隐私敏感名单公告")
    assert "黄浩珉" not in row[0]
    assert pdf_url in fake_client.purged
