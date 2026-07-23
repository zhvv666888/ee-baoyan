from crawler.http import FetchResult, PoliteHttpClient
from crawler.models import CrawlSettings


def test_purge_cache_removes_sensitive_page_artifacts(tmp_path):
    client = PoliteHttpClient(
        CrawlSettings(user_agent="test-agent"),
        tmp_path / "cache",
    )
    url = "https://example.edu.cn/notice/1.htm"
    client._write_cache(
        url,
        FetchResult(
            url=url,
            status_code=200,
            content=b"sensitive body",
            content_type="text/html",
            from_cache=False,
        ),
    )
    body_path, meta_path = client._cache_paths(url)
    assert body_path.exists()
    assert meta_path.exists()
    client.purge_cache(url)
    assert not body_path.exists()
    assert not meta_path.exists()
    client.close()
