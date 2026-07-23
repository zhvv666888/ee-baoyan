from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path
from typing import Protocol

from crawler.storage import NoticeStore

from .models import ProgramRecord


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "programs.demo.csv"
DEFAULT_PUBLISHED_DATABASE = BASE_DIR / "data" / "crawler" / "notices.sqlite3"
ALLOWED_DATA_MODES = {"demo", "published"}


def _split_pipe(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _optional_float(value: object) -> float | None:
    return None if value is None or value == "" else float(value)


def load_programs(path: Path = DEFAULT_DATA_FILE) -> list[ProgramRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Program data not found: {path}")

    records: list[ProgramRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_num, row in enumerate(reader, start=2):
            try:
                records.append(
                    ProgramRecord(
                        program_id=row["program_id"],
                        school=row["school"],
                        college=row["college"],
                        program_name=row["program_name"],
                        region=row["region"],
                        directions=_split_pipe(row["directions"]),
                        degree_types=_split_pipe(row["degree_types"]),
                        min_rank_percent=float(row["min_rank_percent"]),
                        preferred_rank_percent=float(row["preferred_rank_percent"]),
                        expected_school_tier=float(row["expected_school_tier"]),
                        research_expectation=float(row["research_expectation"]),
                        competition_expectation=float(row["competition_expectation"]),
                        english_min=int(row["english_min"] or 0),
                        required_strength=float(row["required_strength"]),
                        evidence_level=row["evidence_level"],
                        sample_size=int(row["sample_size"] or 0),
                        data_year=int(row["data_year"]),
                        source_url=row.get("source_url") or None,
                        notes=row.get("notes") or None,
                        is_demo=(row.get("is_demo", "true").lower() == "true"),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Invalid program row {row_num}: {exc}") from exc
    return records


class ProgramRepository(Protocol):
    def list_programs(self) -> list[ProgramRecord]:
        ...


class DemoCsvProgramRepository:
    def __init__(self, path: Path = DEFAULT_DATA_FILE):
        self.path = path

    def list_programs(self) -> list[ProgramRecord]:
        return load_programs(self.path)


class PublishedSqliteProgramRepository:
    def __init__(self, database_path: Path = DEFAULT_PUBLISHED_DATABASE):
        self.database_path = database_path

    def list_programs(self) -> list[ProgramRecord]:
        with NoticeStore(self.database_path) as store:
            rows = store.list_published_programs()
            programs: list[ProgramRecord] = []
            for row in rows:
                try:
                    programs.append(
                        ProgramRecord(
                            program_id=row["program_id"],
                            school=row["school"],
                            college=row["college"],
                            program_name=row["program_name"],
                            region=row["region"],
                            directions=json.loads(row["directions_json"]),
                            degree_types=json.loads(row["degree_types_json"]),
                            min_rank_percent=_optional_float(row["min_rank_percent"]),
                            preferred_rank_percent=_optional_float(row["preferred_rank_percent"]),
                            expected_school_tier=_optional_float(row["expected_school_tier"]),
                            research_expectation=_optional_float(row["research_expectation"]),
                            competition_expectation=_optional_float(row["competition_expectation"]),
                            english_min=None if row["english_min"] is None else int(row["english_min"]),
                            required_strength=_optional_float(row["required_strength"]),
                            evidence_level=row["evidence_level"],
                            sample_size=int(row["sample_size"] or 0),
                            data_year=int(row["data_year"]),
                            source_url=row["source_url"],
                            notes=row["notes"],
                            is_demo=False,
                            source_title=row["source_title"],
                            source_date=row["source_date"],
                            reviewed_at=row["reviewed_at"],
                            published_at=row["published_at"],
                            missing_fields=json.loads(row["missing_fields_json"] or "[]"),
                        )
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid published program {row['program_id']}: {exc}"
                    ) from exc
            return programs


def get_data_mode() -> str:
    mode = os.getenv("APP_DATA_MODE", "demo").strip().lower()
    if mode not in ALLOWED_DATA_MODES:
        raise RuntimeError(
            f"Invalid APP_DATA_MODE={mode!r}; expected one of: demo, published"
        )
    return mode


def get_program_repository(
    mode: str | None = None,
    database_path: Path | None = None,
) -> ProgramRepository:
    selected_mode = mode or get_data_mode()
    if selected_mode == "demo":
        return DemoCsvProgramRepository()
    if selected_mode == "published":
        configured_path = os.getenv("APP_PUBLISHED_DATABASE", "").strip()
        path = database_path or Path(configured_path or DEFAULT_PUBLISHED_DATABASE)
        return PublishedSqliteProgramRepository(path)
    raise RuntimeError(
        f"Invalid APP_DATA_MODE={selected_mode!r}; expected one of: demo, published"
    )
