from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.repository import load_programs


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/programs.demo.csv")
    try:
        records = load_programs(path)
    except Exception as exc:  # noqa: BLE001
        print(f"校验失败：{exc}")
        return 1

    ids = [record.program_id for record in records]
    duplicates = [item for item, count in Counter(ids).items() if count > 1]
    if duplicates:
        print(f"校验失败：program_id 重复：{', '.join(duplicates)}")
        return 1

    warnings: list[str] = []
    for record in records:
        if not record.is_demo and not record.source_url:
            warnings.append(f"{record.program_id}: 真实数据缺少 source_url")
        if record.preferred_rank_percent > record.min_rank_percent:
            warnings.append(f"{record.program_id}: preferred_rank_percent 应不大于 min_rank_percent")
        if record.evidence_level == "A" and not record.source_url and not record.is_demo:
            warnings.append(f"{record.program_id}: A 级证据必须提供官方来源")

    print(f"通过结构校验：{len(records)} 条项目记录")
    if warnings:
        print("警告：")
        for warning in warnings:
            print(f"- {warning}")
        return 2
    print("无警告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
