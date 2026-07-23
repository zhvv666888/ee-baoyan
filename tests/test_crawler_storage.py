from datetime import date, datetime, timezone

from crawler.models import CrawledNotice, ExtractedFacts
from crawler.storage import NoticeStore


def make_notice(content_hash: str = "abc") -> CrawledNotice:
    return CrawledNotice(
        notice_id="notice-1",
        source_id="source-1",
        school="某大学",
        college="信息学院",
        title="2026年夏令营通知",
        url="https://example.edu.cn/notice/1.htm",
        published_date=date(2026, 7, 1),
        data_year=2026,
        notice_type="summer_camp_notice",
        content_text="申请条件",
        content_sha256=content_hash,
        fetched_at=datetime.now(timezone.utc),
        facts=ExtractedFacts(cet6_min=425),
    )


def test_store_upsert_and_export(tmp_path):
    database = tmp_path / "notices.sqlite3"
    output = tmp_path / "review.csv"
    with NoticeStore(database) as store:
        assert store.upsert(make_notice()) is True
        assert store.upsert(make_notice()) is False
        assert store.upsert(make_notice("changed")) is True
        assert store.export_csv(output, only_pending=True) == 1
    content = output.read_text(encoding="utf-8-sig")
    assert "cet6_min" in content
    assert "425" in content


def test_record_run_persists_structured_run_basics(tmp_path):
    database = tmp_path / "notices.sqlite3"
    with NoticeStore(database) as store:
        store.record_run(
            {
                "source_id": "source-1",
                "started_at": "2026-07-23T00:00:00+00:00",
                "finished_at": "2026-07-23T00:00:01+00:00",
                "notices_discovered": 2,
                "saved_or_changed": 1,
                "notices_failed": 1,
                "errors": ["one failure"],
            }
        )
        row = store.connection.execute("SELECT * FROM crawl_runs").fetchone()
    assert row["source_id"] == "source-1"
    assert row["discovered_count"] == 2
    assert row["saved_count"] == 1
    assert row["error_count"] == 1
