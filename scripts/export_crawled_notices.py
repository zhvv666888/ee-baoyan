from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler.storage import NoticeStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Export crawled notices to a reviewable CSV file.")
    parser.add_argument("--database", default="data/crawler/notices.sqlite3")
    parser.add_argument("--output", default="data/crawler/review_queue.csv")
    parser.add_argument("--all", action="store_true", help="Export reviewed rows too")
    args = parser.parse_args()
    with NoticeStore(args.database) as store:
        count = store.export_csv(args.output, only_pending=not args.all)
    print(f"Exported {count} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
