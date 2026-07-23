from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.models import ApplicantProfile, ProgramRecord
from app.repository import PublishedSqliteProgramRepository, get_data_mode
from app.recommender import recommend
from crawler.extract import extract_notice
from crawler.http import FetchResult
from crawler.models import CandidateLink, ExtractedFacts, CrawledNotice, SourceConfig
from crawler.storage import NoticeStore


FIXTURE = Path(__file__).parent / "fixtures" / "detail_page.html"


def fixture_source() -> SourceConfig:
    return SourceConfig(
        source_id="fixture-source",
        school="测试大学",
        college="信息学院",
        seed_urls=["https://ee.example.edu.cn/notices.htm"],
        allowed_domains=["ee.example.edu.cn"],
        include_keywords=["夏令营", "推免"],
        content_selectors=[".v_news_content"],
        title_selectors=["h1"],
        date_selectors=[".info"],
    )


def fixture_notice() -> CrawledNotice:
    result = FetchResult(
        url="https://ee.example.edu.cn/info/1142/16512.htm",
        status_code=200,
        content=FIXTURE.read_bytes(),
        content_type="text/html",
        from_cache=False,
    )
    candidate = CandidateLink(
        title="夏令营通知",
        url=result.url,
        source_id="fixture-source",
        list_url="https://ee.example.edu.cn/notices.htm",
    )
    return extract_notice(result, candidate, fixture_source())


def sensitive_notice() -> CrawledNotice:
    return CrawledNotice(
        notice_id="sensitive-1",
        source_id="fixture-source",
        school="测试大学",
        college="信息学院",
        title="2026拟录取名单",
        url="https://ee.example.edu.cn/info/1/2.htm",
        published_date=date(2026, 7, 2),
        data_year=2026,
        notice_type="proposed_admission_list",
        content_text="内容已脱敏，不持久化个人名单。",
        content_sha256="sensitive-hash",
        fetched_at=datetime.now(timezone.utc),
        facts=ExtractedFacts(privacy_sensitive=True),
    )


def complete_fields() -> dict[str, object]:
    return {
        "school_name": "测试大学",
        "college_name": "信息学院",
        "program_name": "信息与通信工程",
        "program_code": "081000",
        "research_directions": ["无线通信", "信号处理"],
        "degree_types": ["academic_master", "professional_master"],
        "year": 2026,
        "region": "北京",
        "rank_requirement_percent": 15,
        "preferred_rank_percent": 8,
        "expected_school_tier": 3.5,
        "research_expectation": 3,
        "competition_expectation": 2,
        "english_min": 425,
        "required_strength": 70,
        "sample_size": 0,
        "evidence_level": "A",
        "extraction_confidence": 0.8,
    }


def test_fixture_notice_requires_review_before_it_can_reach_recommender(tmp_path):
    database = tmp_path / "closed-loop.sqlite3"
    with NoticeStore(database) as store:
        notice = fixture_notice()
        assert store.upsert(notice) is True
        draft = store.create_program_draft_from_notice(notice.notice_id)
        assert draft is not None
        assert draft["status"] == "pending"
        assert "program_name" in draft["missing_fields"]
        assert store.list_published_programs() == []

    assert PublishedSqliteProgramRepository(database).list_programs() == []


def test_review_publish_recommend_unpublish_flow_and_history(tmp_path):
    database = tmp_path / "closed-loop.sqlite3"
    with NoticeStore(database) as store:
        notice = fixture_notice()
        store.upsert(notice)
        draft = store.create_program_draft_from_notice(notice.notice_id)
        assert draft is not None
        draft_id = draft["draft_id"]
        store.update_program_draft(draft_id, complete_fields(), reviewer="tester")
        assert store.review_program_draft(draft_id, reviewer="tester")["status"] == "reviewed"
        published = store.publish_program_draft(draft_id, reviewer="tester")
        assert published["status"] == "published"
        rows = store.list_published_programs()
        assert len(rows) == 1
        assert rows[0]["notice_id"] == notice.notice_id
        assert "内容已脱敏" not in rows[0]["source_title"]
        assert any(event["action"] == "publish" for event in store.get_review_events(draft_id))

    programs = PublishedSqliteProgramRepository(database).list_programs()
    assert len(programs) == 1
    assert programs[0].is_demo is False
    assert programs[0].school == "测试大学"
    assert programs[0].missing_fields == []

    with NoticeStore(database) as store:
        assert store.unpublish_program_draft(draft_id, reviewer="tester")["status"] == "reviewed"
        assert store.list_published_programs() == []
    assert PublishedSqliteProgramRepository(database).list_programs() == []


def test_sensitive_notice_is_logged_but_never_becomes_a_draft(tmp_path):
    database = tmp_path / "closed-loop.sqlite3"
    with NoticeStore(database) as store:
        notice = sensitive_notice()
        store.upsert(notice)
        assert store.create_program_draft_from_notice(notice.notice_id) is None
        assert store.list_program_drafts() == []
        log = store.connection.execute(
            "SELECT result, reason FROM draft_generation_log WHERE notice_id = ?",
            (notice.notice_id,),
        ).fetchone()
        assert log["result"] == "skipped"
        assert "privacy-sensitive" in log["reason"]
        assert store.list_published_programs() == []


def test_only_reviewed_complete_drafts_can_be_published(tmp_path):
    database = tmp_path / "closed-loop.sqlite3"
    with NoticeStore(database) as store:
        notice = fixture_notice()
        store.upsert(notice)
        draft = store.create_program_draft_from_notice(notice.notice_id)
        assert draft is not None
        with pytest.raises(ValueError, match="only reviewed"):
            store.publish_program_draft(draft["draft_id"])
        store.update_program_draft(draft["draft_id"], complete_fields())
        store.review_program_draft(draft["draft_id"])
        store.update_program_draft(draft["draft_id"], {"rank_requirement_percent": 101})
        with pytest.raises(ValueError, match="rank_requirement_percent"):
            store.publish_program_draft(draft["draft_id"])


def test_invalid_data_mode_fails_fast(monkeypatch):
    monkeypatch.setenv("APP_DATA_MODE", "not-a-mode")
    with pytest.raises(RuntimeError, match="Invalid APP_DATA_MODE"):
        get_data_mode()


def test_invalid_data_mode_fails_app_startup():
    env = os.environ.copy()
    env["APP_DATA_MODE"] = "not-a-mode"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Invalid APP_DATA_MODE" in result.stderr


def test_unknown_official_thresholds_are_not_treated_as_low_barriers():
    program = ProgramRecord(
        program_id="PUB-UNKNOWN",
        school="真实大学",
        college="信息学院",
        program_name="信息与通信工程",
        region="成都",
        directions=[],
        degree_types=["academic_master"],
        evidence_level="A",
        data_year=2026,
        source_url="https://example.edu.cn/notice/1",
        missing_fields=["min_rank_percent", "required_strength"],
    )
    profile = ApplicantProfile(
        school_name="某工科大学",
        school_tier="211",
        major="电子信息工程",
        rank_percent=8,
        gpa=3.7,
        degree_types=["academic_master"],
    )
    result = recommend(profile, [program], limit=1)[0]
    assert result.required_strength is None
    assert result.data_complete is False
    assert result.bucket == "冲刺"
    assert any("不能视为低门槛" in risk for risk in result.risks)


def test_reviewed_real_notice_can_publish_with_explicit_unknown_thresholds(tmp_path):
    database = tmp_path / "unknown-thresholds.sqlite3"
    with NoticeStore(database) as store:
        notice = fixture_notice()
        store.upsert(notice)
        draft = store.create_program_draft_from_notice(notice.notice_id)
        assert draft is not None
        draft = store.update_program_draft(
            draft["draft_id"],
            {
                "program_name": "信息与通信工程",
                "region": "成都",
                "evidence_level": "A",
                "reviewer_note": "官方未明确排名线，保留未知",
            },
            reviewer="tester",
        )
        assert "preferred_rank_percent" in draft["missing_fields"]
        store.review_program_draft(draft["draft_id"], reviewer="tester")
        published = store.publish_program_draft(draft["draft_id"], reviewer="tester")
        assert published["status"] == "published"
        row = store.list_published_programs()[0]
        assert row["preferred_rank_percent"] is None
        assert "preferred_rank_percent" in json.loads(row["missing_fields_json"])
    program = PublishedSqliteProgramRepository(database).list_programs()[0]
    assert program.preferred_rank_percent is None
    assert program.missing_fields
