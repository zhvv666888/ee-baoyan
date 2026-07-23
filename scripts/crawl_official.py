from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler.config import load_config
from crawler.pipeline import CrawlPipeline
from crawler.storage import NoticeStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl official graduate admission notices politely.")
    parser.add_argument("--config", default="config/sources.official.json")
    parser.add_argument("--source", action="append", help="Source ID to crawl; may be repeated")
    parser.add_argument("--since", help="Only keep notices on/after YYYY-MM-DD")
    parser.add_argument("--database", default="data/crawler/notices.sqlite3")
    parser.add_argument("--cache-dir", default="data/crawler/cache")
    parser.add_argument("--export", default="data/crawler/review_queue.csv")
    parser.add_argument("--summary", default="data/crawler/last_run.json")
    parser.add_argument("--list-sources", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings, sources = load_config(args.config)

    if args.list_sources:
        for source in sources:
            status = "enabled" if source.enabled else "disabled"
            print(f"{source.source_id}\t{status}\t{source.school}\t{source.college}")
        return 0

    selected = set(args.source or [])
    if selected:
        sources = [source for source in sources if source.source_id in selected]
        missing = selected - {source.source_id for source in sources}
        if missing:
            print(f"Unknown source IDs: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    since = date.fromisoformat(args.since) if args.since else None
    pipeline = CrawlPipeline(settings, database_path=args.database, cache_dir=args.cache_dir)
    summaries = pipeline.run_many(sources, since=since)
    pipeline.write_summary(summaries, args.summary)

    with NoticeStore(args.database) as store:
        exported = store.export_csv(args.export, only_pending=True)

    for summary in summaries:
        print(
            f"[{summary.source_id}] discovered={summary.discovered} fetched={summary.fetched} "
            f"changed={summary.saved_or_changed} errors={len(summary.errors)}"
        )
        for error in summary.errors[:5]:
            print(f"  - {error}")
    print(f"Pending review rows exported: {exported} -> {args.export}")
    return 0 if not any(summary.errors for summary in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
