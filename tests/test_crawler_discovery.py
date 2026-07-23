from pathlib import Path

from crawler.discovery import discover_candidates
from crawler.http import FetchResult
from crawler.models import SourceConfig


class FakeClient:
    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages

    def fetch(self, url: str):
        return FetchResult(
            url=url,
            status_code=200,
            content=self.pages[url],
            content_type="text/html",
            from_cache=False,
        )


def test_discovery_filters_keywords_and_domains():
    fixture = (Path(__file__).parent / "fixtures" / "list_page.html").read_bytes()
    next_page = b'<html><body><a href="/info/1142/20000.htm">2025\xe5\xb9\xb4\xe6\x8e\xa8\xe5\x85\x8d\xe9\x80\x9a\xe7\x9f\xa5</a></body></html>'
    pages = {
        "https://ee.example.edu.cn/notices.htm": fixture,
        "https://ee.example.edu.cn/yjsk/2.htm": next_page,
    }
    source = SourceConfig(
        source_id="test",
        school="某大学",
        college="信息学院",
        seed_urls=["https://ee.example.edu.cn/notices.htm"],
        allowed_domains=["ee.example.edu.cn"],
        include_keywords=["夏令营", "优秀本科生选拔", "推免"],
        exclude_keywords=["课程"],
        detail_url_patterns=[r"/info/\d+/\d+\.htm"],
        max_list_pages=2,
    )
    links = discover_candidates(FakeClient(pages), source)
    titles = {link.title for link in links}
    assert "某大学信息学院2026年暑期夏令营通知" in titles
    assert "某大学信息学院2026年优秀本科生选拔计划" in titles
    assert "2025年推免通知" in titles
    assert all("课程" not in title for title in titles)
