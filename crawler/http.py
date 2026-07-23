from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .models import CrawlSettings


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    from_cache: bool

    @property
    def text(self) -> str:
        for encoding in ("utf-8", "gb18030", "gbk"):
            try:
                return self.content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")


class PoliteHttpClient:
    """HTTP client with robots.txt, per-host throttling, retries and disk cache."""

    def __init__(self, settings: CrawlSettings, cache_dir: str | Path):
        self.settings = settings
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=settings.timeout_seconds,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request_at: dict[str, float] = {}
        self.request_count = 0
        self.cache_hit_count = 0
        self._robots_denied = False

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        body_path, meta_path = self._cache_paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = time.time() - float(meta["saved_at"])
            if age > self.settings.cache_ttl_hours * 3600:
                return None
            return FetchResult(
                url=meta["final_url"],
                status_code=int(meta["status_code"]),
                content=body_path.read_bytes(),
                content_type=meta.get("content_type", ""),
                from_cache=True,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def _write_cache(self, requested_url: str, result: FetchResult) -> None:
        body_path, meta_path = self._cache_paths(requested_url)
        body_path.write_bytes(result.content)
        meta_path.write_text(
            json.dumps(
                {
                    "saved_at": time.time(),
                    "final_url": result.url,
                    "status_code": result.status_code,
                    "content_type": result.content_type,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def purge_cache(self, url: str) -> None:
        """Remove a cached page once extraction identifies it as privacy-sensitive."""
        for path in self._cache_paths(url):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _robots_for(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]

        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.client.get(robots_url)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                self._robots[origin] = parser
            else:
                self._robots[origin] = None
        except httpx.HTTPError:
            self._robots[origin] = None
        return self._robots[origin]

    def allowed_by_robots(self, url: str) -> bool:
        parser = self._robots_for(url)
        allowed = True if parser is None else parser.can_fetch(self.settings.user_agent, url)
        if not allowed:
            self._robots_denied = True
        return allowed

    @property
    def robots_allowed(self) -> bool:
        return not self._robots_denied

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        delay = self.settings.request_delay_seconds
        parser = self._robots_for(url)
        if parser is not None:
            robots_delay = parser.crawl_delay(self.settings.user_agent) or parser.crawl_delay("*")
            if robots_delay:
                delay = max(delay, float(robots_delay))
        elapsed = time.monotonic() - self._last_request_at.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_at[host] = time.monotonic()

    def fetch(self, url: str, *, use_cache: bool = True, max_bytes: int | None = None) -> FetchResult:
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                self.cache_hit_count += 1
                return cached

        if not self.allowed_by_robots(url):
            raise PermissionError(f"robots.txt disallows crawling: {url}")

        self._throttle(url)
        limit = max_bytes or self.settings.max_response_bytes
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self.request_count += 1
                with self.client.stream("GET", url) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"response exceeds {limit} bytes: {url}")
                        chunks.append(chunk)
                    result = FetchResult(
                        url=str(response.url),
                        status_code=response.status_code,
                        content=b"".join(chunks),
                        content_type=response.headers.get("content-type", ""),
                        from_cache=False,
                    )
                    if use_cache:
                        self._write_cache(url, result)
                    return result
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error
