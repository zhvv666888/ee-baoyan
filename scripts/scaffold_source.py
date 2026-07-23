from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not value:
        raise ValueError("source ID must contain ASCII letters or digits")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a crawler source configuration stub.")
    parser.add_argument("--source-id", required=True, help="ASCII ID, for example xidian-telecom")
    parser.add_argument("--school", required=True)
    parser.add_argument("--college", required=True)
    parser.add_argument("--url", required=True, help="Official notice list URL")
    parser.add_argument("--config", default="config/sources.official.json")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()

    source_id = slugify(args.source_id)
    parsed = urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--url must be a complete HTTP(S) URL")

    path = Path(args.config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if any(item["source_id"] == source_id for item in payload["sources"]):
        raise SystemExit(f"source already exists: {source_id}")

    payload["sources"].append(
        {
            "source_id": source_id,
            "school": args.school,
            "college": args.college,
            "seed_urls": [args.url],
            "allowed_domains": [parsed.netloc],
            "include_keywords": ["夏令营", "推免", "推荐免试", "优秀营员", "拟录取"],
            "exclude_keywords": ["统考", "调剂", "课程", "奖学金"],
            "detail_url_patterns": ["/info/\\d+/\\d+\\.htm", "/20\\d{2}/.*(?:page|content)\\.htm"],
            "content_selectors": [".v_news_content", ".wp_articlecontent", ".article-content", "article"],
            "title_selectors": ["h1", "h2", ".article-title"],
            "date_selectors": [".info", ".time", ".arti_metas"],
            "pagination_keywords": ["下一页", "下页", "next"],
            "max_list_pages": 1,
            "max_notices_per_run": 10,
            "enabled": args.enable,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Added {source_id} to {path}. Run a small crawl and tune selectors before increasing limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
