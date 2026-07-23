from datetime import date
from pathlib import Path

from crawler.extract import classify_notice, extract_facts, extract_notice, redact_personal_data
from crawler.http import FetchResult
from crawler.models import CandidateLink, SourceConfig


FIXTURES = Path(__file__).parent / "fixtures"


def make_source() -> SourceConfig:
    return SourceConfig(
        source_id="test-source",
        school="某大学",
        college="信息学院",
        seed_urls=["https://ee.example.edu.cn/notices.htm"],
        allowed_domains=["ee.example.edu.cn"],
        include_keywords=["夏令营", "推免"],
        content_selectors=[".v_news_content"],
        title_selectors=["h1"],
        date_selectors=[".info"],
    )


def test_classify_and_extract_facts():
    text = "专业排名前15%；大学英语六级425分以上；报名截止时间：2026年7月6日10:00。拟招收100人，线上活动。"
    notice_type = classify_notice("2026年暑期夏令营通知", text)
    facts = extract_facts("2026年暑期夏令营通知", text, notice_type)
    assert notice_type == "summer_camp_notice"
    assert facts.rank_percent_max == 15
    assert facts.cet6_min == 425
    assert facts.quota == 100
    assert facts.activity_mode == "online"
    assert facts.deadline.startswith("2026年7月6日")


def test_extract_notice_from_html_fixture():
    html = (FIXTURES / "detail_page.html").read_bytes()
    result = FetchResult(
        url="https://ee.example.edu.cn/info/1142/16512.htm",
        status_code=200,
        content=html,
        content_type="text/html",
        from_cache=False,
    )
    candidate = CandidateLink(
        title="夏令营通知",
        url=result.url,
        source_id="test-source",
        list_url="https://ee.example.edu.cn/notices.htm",
    )
    notice = extract_notice(result, candidate, make_source())
    assert notice.published_date == date(2026, 7, 1)
    assert notice.data_year == 2026
    assert notice.notice_type == "summer_camp_notice"
    assert notice.facts.eligible_cohort == "2023"
    assert notice.facts.cet6_min == 425
    assert notice.facts.rank_percent_max == 15
    assert notice.facts.quota == 100
    assert notice.attachment_urls == ["https://ee.example.edu.cn/files/application.pdf"]


def test_redact_personal_data():
    text = "联系邮箱 test@example.edu.cn，电话13800138000，QQ群：123456789。"
    redacted = redact_personal_data(text)
    assert "test@example.edu.cn" not in redacted
    assert "13800138000" not in redacted
    assert "123456789" not in redacted


def test_sensitive_list_body_is_not_persisted():
    html = """<html><body><h1>2026年拟录取名单</h1><div class='info'>2026-07-01</div><div class='v_news_content'><p>张三 20260001</p></div></body></html>""".encode("utf-8")
    result = FetchResult(
        url="https://ee.example.edu.cn/info/1/2.htm",
        status_code=200,
        content=html,
        content_type="text/html",
        from_cache=False,
    )
    candidate = CandidateLink(
        title="拟录取名单",
        url=result.url,
        source_id="test-source",
        list_url="https://ee.example.edu.cn/notices.htm",
    )
    notice = extract_notice(result, candidate, make_source())
    assert notice.facts.privacy_sensitive is True
    assert "张三" not in notice.content_text
    assert "未持久化" in notice.content_text


def test_sensitive_assessment_result_body_is_not_persisted():
    html = """<html><body><title>2025年夏令营活动综合能力考核结果（本校生源）</title><div class='v_news_content'>在校生注册学号 姓名 61822105 黄浩珉</div></body></html>""".encode("utf-8")
    result = FetchResult(
        url="https://ee.example.edu.cn/info/1/3.htm",
        status_code=200,
        content=html,
        content_type="text/html",
        from_cache=False,
    )
    candidate = CandidateLink(
        title="考核结果",
        url=result.url,
        source_id="test-source",
        list_url="https://ee.example.edu.cn/notices.htm",
    )
    notice = extract_notice(result, candidate, make_source())
    assert notice.facts.privacy_sensitive is True
    assert "黄浩珉" not in notice.content_text
    assert "61822105" not in notice.content_text


def test_title_priority_and_line_break_date_normalization():
    title = "\u7535\u5b50\u79d1\u6280\u5927\u5b66\u4fe1\u606f\u4e0e\u901a\u4fe1\u5de5\u7a0b\u5b66\u96622026\u5e74\u6691\u671f\u590f\u4ee4\u8425\u901a\u77e5"
    content = (
        "\u76f8\u5173\u4fe1\u606f\uff1a\u4f18\u79c0\u672c\u79d1\u751f\u9009\u62d4\u8ba1\u5212\u3002"
        "\u5b66\u9662\u5c06\u4e8e\n2026\u5e747\u6708\n7\n\u65e5\n\u4e3e\u529e\u590f\u4ee4\u8425\u3002"
        "\u62a5\u540d\u622a\u6b62\u65e5\u671f\uff1a\n2026\u5e747\u6708\n6\n\u65e5\n10:00\u3002"
    )
    assert classify_notice(title, content) == "summer_camp_notice"
    facts = extract_facts(title, content, "summer_camp_notice")
    assert facts.deadline.startswith("2026\u5e747\u6708")
    assert facts.event_date.startswith("2026\u5e747\u6708")
