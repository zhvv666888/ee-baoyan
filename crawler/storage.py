from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import CrawledNotice


SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    school TEXT NOT NULL,
    college TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_date TEXT,
    data_year INTEGER,
    notice_type TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    attachment_urls_json TEXT NOT NULL,
    source_list_url TEXT,
    http_status INTEGER NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 1,
    review_status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_notices_source_date ON notices(source_id, published_date);
CREATE INDEX IF NOT EXISTS idx_notices_type ON notices(notice_type);

CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source_id TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    saved_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS program_drafts (
    draft_id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id TEXT NOT NULL,
    school_name TEXT,
    college_name TEXT,
    program_name TEXT,
    program_code TEXT,
    research_directions_json TEXT NOT NULL DEFAULT '[]',
    application_stage TEXT,
    degree_types_json TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    region TEXT,
    rank_requirement_percent REAL,
    preferred_rank_percent REAL,
    expected_school_tier REAL,
    research_expectation REAL,
    competition_expectation REAL,
    cet4_requirement INTEGER,
    cet6_requirement INTEGER,
    english_min INTEGER,
    enrollment_count INTEGER,
    camp_count INTEGER,
    excellent_count INTEGER,
    requires_research INTEGER,
    requires_paper INTEGER,
    requires_contact_supervisor INTEGER,
    accepts_cross_major INTEGER,
    assessment_mode TEXT,
    assessment_content TEXT,
    application_start_date TEXT,
    application_deadline TEXT,
    activity_start_date TEXT,
    activity_end_date TEXT,
    required_strength REAL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_date TEXT,
    source_content_hash TEXT,
    evidence_level TEXT,
    extraction_confidence REAL,
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'reviewed', 'rejected', 'published')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
);
CREATE INDEX IF NOT EXISTS idx_program_drafts_status ON program_drafts(status);
CREATE INDEX IF NOT EXISTS idx_program_drafts_notice ON program_drafts(notice_id);

CREATE TABLE IF NOT EXISTS draft_generation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('created', 'skipped')),
    reason TEXT,
    draft_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
);

CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_draft_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT,
    changed_fields TEXT NOT NULL DEFAULT '{}',
    reviewer TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_draft_id) REFERENCES program_drafts(draft_id)
);
CREATE INDEX IF NOT EXISTS idx_review_events_draft ON review_events(program_draft_id, created_at);

CREATE TABLE IF NOT EXISTS published_programs (
    published_program_id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id TEXT NOT NULL UNIQUE,
    draft_id INTEGER NOT NULL UNIQUE,
    notice_id TEXT NOT NULL,
    school TEXT NOT NULL,
    college TEXT NOT NULL,
    program_name TEXT NOT NULL,
    region TEXT NOT NULL,
    directions_json TEXT NOT NULL DEFAULT '[]',
    degree_types_json TEXT NOT NULL DEFAULT '[]',
    min_rank_percent REAL,
    preferred_rank_percent REAL,
    expected_school_tier REAL,
    research_expectation REAL,
    competition_expectation REAL,
    english_min INTEGER,
    required_strength REAL,
    evidence_level TEXT NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    data_year INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_date TEXT,
    source_content_hash TEXT,
    notes TEXT,
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    published_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_updated_at TEXT NOT NULL,
    FOREIGN KEY(draft_id) REFERENCES program_drafts(draft_id),
    FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
);
CREATE INDEX IF NOT EXISTS idx_published_programs_active ON published_programs(is_active);
"""


REVIEWER_DEFAULT = "local-reviewer"
VALID_DRAFT_STATUSES = {"pending", "reviewed", "rejected", "published"}
SENSITIVE_NOTICE_TYPES = {
    "interview_list",
    "excellent_camper_list",
    "proposed_admission_list",
}
DRAFT_EDITABLE_FIELDS = {
    "school_name",
    "college_name",
    "program_name",
    "program_code",
    "research_directions",
    "application_stage",
    "degree_types",
    "year",
    "region",
    "rank_requirement_percent",
    "preferred_rank_percent",
    "expected_school_tier",
    "research_expectation",
    "competition_expectation",
    "cet4_requirement",
    "cet6_requirement",
    "english_min",
    "enrollment_count",
    "camp_count",
    "excellent_count",
    "requires_research",
    "requires_paper",
    "requires_contact_supervisor",
    "accepts_cross_major",
    "assessment_mode",
    "assessment_content",
    "application_start_date",
    "application_deadline",
    "activity_start_date",
    "activity_end_date",
    "required_strength",
    "sample_size",
    "evidence_level",
    "extraction_confidence",
    "reviewer_note",
}
JSON_FIELDS = {"research_directions": "research_directions_json", "degree_types": "degree_types_json"}
BOOLEAN_FIELDS = {
    "requires_research",
    "requires_paper",
    "requires_contact_supervisor",
    "accepts_cross_major",
}
PUBLISH_REQUIRED_FIELDS = {
    "school_name",
    "college_name",
    "program_name",
    "region",
    "degree_types",
    "year",
    "evidence_level",
}


class NoticeStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self._migrate_published_program_schema()
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NoticeStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate_published_program_schema(self) -> None:
        """Allow reviewed official notices to retain explicitly unknown thresholds."""
        info = self.connection.execute("PRAGMA table_info(published_programs)").fetchall()
        optional_columns = {
            "min_rank_percent",
            "preferred_rank_percent",
            "expected_school_tier",
            "research_expectation",
            "competition_expectation",
            "english_min",
            "required_strength",
        }
        if not info or not any(row["name"] in optional_columns and row["notnull"] for row in info):
            return
        create_sql_row = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'published_programs'"
        ).fetchone()
        if not create_sql_row or not create_sql_row["sql"]:
            return
        create_sql = create_sql_row["sql"].replace(
            "published_programs", "published_programs_migrated", 1
        )
        replacements = {
            "min_rank_percent REAL NOT NULL": "min_rank_percent REAL",
            "preferred_rank_percent REAL NOT NULL": "preferred_rank_percent REAL",
            "expected_school_tier REAL NOT NULL": "expected_school_tier REAL",
            "research_expectation REAL NOT NULL": "research_expectation REAL",
            "competition_expectation REAL NOT NULL": "competition_expectation REAL",
            "english_min INTEGER NOT NULL DEFAULT 0": "english_min INTEGER DEFAULT 0",
            "required_strength REAL NOT NULL": "required_strength REAL",
        }
        for old, new in replacements.items():
            create_sql = create_sql.replace(old, new)
        columns = [row["name"] for row in info]
        column_list = ", ".join(columns)
        self.connection.execute(create_sql)
        self.connection.execute(
            f"INSERT INTO published_programs_migrated ({column_list}) "
            f"SELECT {column_list} FROM published_programs"
        )
        self.connection.execute("DROP TABLE published_programs")
        self.connection.execute("ALTER TABLE published_programs_migrated RENAME TO published_programs")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_programs_active "
            "ON published_programs(is_active)"
        )

    def upsert(self, notice: CrawledNotice) -> bool:
        existing = self.connection.execute(
            "SELECT content_sha256 FROM notices WHERE notice_id = ?", (notice.notice_id,)
        ).fetchone()
        changed = existing is None or existing["content_sha256"] != notice.content_sha256
        self.connection.execute(
            """
            INSERT INTO notices (
                notice_id, source_id, school, college, title, url, published_date, data_year,
                notice_type, content_text, content_sha256, fetched_at, facts_json,
                attachment_urls_json, source_list_url, http_status, needs_review
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(notice_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                published_date=excluded.published_date,
                data_year=excluded.data_year,
                notice_type=excluded.notice_type,
                content_text=excluded.content_text,
                content_sha256=excluded.content_sha256,
                fetched_at=excluded.fetched_at,
                facts_json=excluded.facts_json,
                attachment_urls_json=excluded.attachment_urls_json,
                source_list_url=excluded.source_list_url,
                http_status=excluded.http_status,
                needs_review=CASE
                    WHEN notices.content_sha256 != excluded.content_sha256 THEN 1
                    ELSE notices.needs_review
                END,
                review_status=CASE
                    WHEN notices.content_sha256 != excluded.content_sha256 THEN 'pending'
                    ELSE notices.review_status
                END
            """,
            (
                notice.notice_id,
                notice.source_id,
                notice.school,
                notice.college,
                notice.title,
                notice.url,
                notice.published_date.isoformat() if notice.published_date else None,
                notice.data_year,
                notice.notice_type,
                notice.content_text,
                notice.content_sha256,
                notice.fetched_at.isoformat(),
                json.dumps(notice.facts.to_dict(), ensure_ascii=False),
                json.dumps(notice.attachment_urls, ensure_ascii=False),
                notice.source_list_url,
                notice.http_status,
                int(notice.needs_review),
            ),
        )
        self.connection.commit()
        return changed

    def rows_for_export(self, only_pending: bool = False) -> list[sqlite3.Row]:
        where = "WHERE needs_review = 1" if only_pending else ""
        return self.connection.execute(
            f"SELECT * FROM notices {where} ORDER BY COALESCE(published_date, '') DESC, school, college"
        ).fetchall()

    def record_run(self, summary: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO crawl_runs (
                started_at, finished_at, source_id, discovered_count,
                saved_count, error_count, errors_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.get("started_at"),
                summary.get("finished_at"),
                summary.get("source_id"),
                int(summary.get("notices_discovered", summary.get("discovered", 0))),
                int(summary.get("saved_or_changed", 0)),
                int(summary.get("notices_failed", len(summary.get("errors", [])))),
                json.dumps(summary.get("errors", []), ensure_ascii=False),
            ),
        )
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split("|") if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]

    @classmethod
    def _missing_fields(cls, row: sqlite3.Row | dict[str, Any]) -> list[str]:
        required = {
            "school_name": row["school_name"],
            "college_name": row["college_name"],
            "program_name": row["program_name"],
            "region": row["region"],
            "degree_types": json.loads(row["degree_types_json"]),
            "year": row["year"],
            "rank_requirement_percent": row["rank_requirement_percent"],
            "preferred_rank_percent": row["preferred_rank_percent"],
            "expected_school_tier": row["expected_school_tier"],
            "research_expectation": row["research_expectation"],
            "competition_expectation": row["competition_expectation"],
            "english_min": row["english_min"],
            "required_strength": row["required_strength"],
            "evidence_level": row["evidence_level"],
        }
        return [key for key, value in required.items() if value is None or value == [] or value == ""]

    @classmethod
    def _publish_blockers(cls, row: sqlite3.Row | dict[str, Any]) -> list[str]:
        values = {
            "school_name": row["school_name"],
            "college_name": row["college_name"],
            "program_name": row["program_name"],
            "region": row["region"],
            "degree_types": json.loads(row["degree_types_json"] or "[]"),
            "year": row["year"],
            "evidence_level": row["evidence_level"],
        }
        return [key for key in PUBLISH_REQUIRED_FIELDS if values[key] is None or values[key] == [] or values[key] == ""]

    @classmethod
    def _publish_validation_errors(cls, row: sqlite3.Row | dict[str, Any]) -> list[str]:
        errors = cls._publish_blockers(row)
        numeric_ranges = {
            "rank_requirement_percent": (0, 100),
            "preferred_rank_percent": (0, 100),
            "expected_school_tier": (0, 5),
            "research_expectation": (0, 5),
            "competition_expectation": (0, 5),
            "english_min": (0, 710),
            "required_strength": (0, 100),
            "year": (2000, 2100),
            "sample_size": (0, None),
        }
        for field_name, (minimum, maximum) in numeric_ranges.items():
            value = row[field_name]
            if value is None:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                errors.append(field_name)
                continue
            lower_bound_violation = (
                numeric_value <= minimum
                if field_name in {"rank_requirement_percent", "preferred_rank_percent"}
                else numeric_value < minimum
            )
            if lower_bound_violation:
                errors.append(field_name)
            if maximum is not None and numeric_value > maximum:
                errors.append(field_name)
        if row["evidence_level"] not in {"A", "B", "C", "D"}:
            errors.append("evidence_level")
        valid_degree_types = {"academic_master", "professional_master", "direct_phd"}
        degree_types = json.loads(row["degree_types_json"] or "[]")
        if any(degree not in valid_degree_types for degree in degree_types):
            errors.append("degree_types")
        return list(dict.fromkeys(errors))

    @staticmethod
    def _draft_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["research_directions"] = json.loads(result.pop("research_directions_json"))
        result["degree_types"] = json.loads(result.pop("degree_types_json"))
        result["missing_fields"] = json.loads(result.pop("missing_fields_json"))
        return result

    def _draft_row(self, draft_id: int) -> sqlite3.Row:
        row = self.connection.execute(
            """
            SELECT d.*, n.title AS notice_title, n.content_text AS notice_content_text,
                   n.notice_type, n.published_date AS notice_published_date
            FROM program_drafts d
            JOIN notices n ON n.notice_id = d.notice_id
            WHERE d.draft_id = ?
            """,
            (draft_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"program draft not found: {draft_id}")
        return row

    def _record_review_event(
        self,
        draft_id: int,
        action: str,
        previous_status: str | None,
        new_status: str | None,
        changed_fields: dict[str, Any] | None,
        reviewer: str,
        note: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO review_events (
                program_draft_id, action, previous_status, new_status,
                changed_fields, reviewer, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                action,
                previous_status,
                new_status,
                json.dumps(changed_fields or {}, ensure_ascii=False),
                reviewer,
                note,
                self._now(),
            ),
        )

    def _log_draft_generation(
        self, notice_id: str, result: str, reason: str | None = None, draft_id: int | None = None
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO draft_generation_log (notice_id, result, reason, draft_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (notice_id, result, reason, draft_id, self._now()),
        )

    def create_program_draft_from_notice(self, notice_id: str) -> dict[str, Any] | None:
        notice = self.connection.execute(
            "SELECT * FROM notices WHERE notice_id = ?", (notice_id,)
        ).fetchone()
        if notice is None:
            raise KeyError(f"notice not found: {notice_id}")
        existing = self.connection.execute(
            "SELECT draft_id FROM program_drafts WHERE notice_id = ? ORDER BY draft_id DESC LIMIT 1",
            (notice_id,),
        ).fetchone()
        if existing is not None:
            draft_id = int(existing["draft_id"])
            has_manual_save = self.connection.execute(
                "SELECT 1 FROM review_events WHERE program_draft_id = ? AND action = 'save' LIMIT 1",
                (draft_id,),
            ).fetchone()
            if not has_manual_save:
                refreshed_stage = notice["notice_type"]
                self.connection.execute(
                    """
                    UPDATE program_drafts
                    SET application_stage = ?, year = ?, source_url = ?, source_title = ?,
                        source_date = ?, source_content_hash = ?, updated_at = ?
                    WHERE draft_id = ?
                    """,
                    (
                        refreshed_stage,
                        notice["data_year"],
                        notice["url"],
                        notice["title"],
                        notice["published_date"],
                        notice["content_sha256"],
                        self._now(),
                        draft_id,
                    ),
                )
                self.connection.commit()
            return self._draft_dict(self._draft_row(draft_id))

        facts = json.loads(notice["facts_json"])
        if facts.get("privacy_sensitive") or notice["notice_type"] in SENSITIVE_NOTICE_TYPES:
            self._log_draft_generation(
                notice_id,
                "skipped",
                "privacy-sensitive notice cannot generate a program draft",
            )
            self.connection.commit()
            return None

        degree_types = facts.get("degree_types") or []
        english_min = max(facts.get("cet4_min") or 0, facts.get("cet6_min") or 0) or None
        values: dict[str, Any] = {
            "notice_id": notice_id,
            "school_name": notice["school"],
            "college_name": notice["college"],
            "program_name": None,
            "program_code": None,
            "research_directions_json": json.dumps([], ensure_ascii=False),
            "application_stage": notice["notice_type"],
            "degree_types_json": json.dumps(degree_types, ensure_ascii=False),
            "year": notice["data_year"],
            "region": None,
            "rank_requirement_percent": facts.get("rank_percent_max"),
            "preferred_rank_percent": None,
            "expected_school_tier": None,
            "research_expectation": None,
            "competition_expectation": None,
            "cet4_requirement": facts.get("cet4_min"),
            "cet6_requirement": facts.get("cet6_min"),
            "english_min": english_min,
            "enrollment_count": facts.get("quota"),
            "camp_count": None,
            "excellent_count": None,
            "requires_research": None,
            "requires_paper": None,
            "requires_contact_supervisor": None,
            "accepts_cross_major": None,
            "assessment_mode": facts.get("activity_mode"),
            "assessment_content": facts.get("conditions_text"),
            "application_start_date": None,
            "application_deadline": facts.get("deadline"),
            "activity_start_date": facts.get("event_date"),
            "activity_end_date": None,
            "required_strength": None,
            "sample_size": 0,
            "source_url": notice["url"],
            "source_title": notice["title"],
            "source_date": notice["published_date"],
            "source_content_hash": notice["content_sha256"],
            "evidence_level": None,
            "extraction_confidence": None,
            "status": "pending",
            "reviewer_note": None,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        self.connection.execute(
            f"INSERT INTO program_drafts ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        draft_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        row = self._draft_row(draft_id)
        missing = self._missing_fields(row)
        self.connection.execute(
            "UPDATE program_drafts SET missing_fields_json = ? WHERE draft_id = ?",
            (json.dumps(missing, ensure_ascii=False), draft_id),
        )
        self._log_draft_generation(notice_id, "created", draft_id=draft_id)
        self._record_review_event(
            draft_id,
            "create",
            None,
            "pending",
            {"missing_fields": missing},
            REVIEWER_DEFAULT,
            "automatically generated from notice; requires human review",
        )
        self.connection.commit()
        return self._draft_dict(self._draft_row(draft_id))

    def list_program_drafts(
        self,
        status: str | None = None,
        school: str | None = None,
        college: str | None = None,
        year: int | None = None,
        notice_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in VALID_DRAFT_STATUSES:
            raise ValueError(f"invalid draft status: {status}")
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("d.status = ?")
            params.append(status)
        if school:
            clauses.append("d.school_name = ?")
            params.append(school)
        if college:
            clauses.append("d.college_name = ?")
            params.append(college)
        if year is not None:
            clauses.append("d.year = ?")
            params.append(year)
        if notice_type:
            clauses.append("n.notice_type = ?")
            params.append(notice_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 100))
        rows = self.connection.execute(
            f"""
            SELECT d.*, n.title AS notice_title, n.content_text AS notice_content_text,
                   n.notice_type, n.published_date AS notice_published_date
            FROM program_drafts d
            JOIN notices n ON n.notice_id = d.notice_id
            {where}
            ORDER BY d.updated_at DESC, d.draft_id DESC
            LIMIT ?
            """,
            (*params, safe_limit),
        ).fetchall()
        return [self._draft_dict(row) for row in rows]

    def get_program_draft(self, draft_id: int) -> dict[str, Any]:
        return self._draft_dict(self._draft_row(draft_id))

    def get_review_events(self, draft_id: int) -> list[dict[str, Any]]:
        self._draft_row(draft_id)
        rows = self.connection.execute(
            "SELECT * FROM review_events WHERE program_draft_id = ? ORDER BY id",
            (draft_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["changed_fields"] = json.loads(item["changed_fields"])
            result.append(item)
        return result

    def update_program_draft(
        self,
        draft_id: int,
        fields: dict[str, Any],
        reviewer: str = REVIEWER_DEFAULT,
        note: str | None = None,
    ) -> dict[str, Any]:
        unknown = set(fields) - DRAFT_EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"unsupported draft fields: {', '.join(sorted(unknown))}")
        row = self._draft_row(draft_id)
        previous_status = row["status"]
        new_status = "pending" if previous_status == "published" else previous_status
        updates: dict[str, Any] = {}
        changed: dict[str, Any] = {}
        for field_name, value in fields.items():
            column = JSON_FIELDS.get(field_name, field_name)
            if field_name in JSON_FIELDS:
                value = json.dumps(self._list_value(value), ensure_ascii=False)
            elif field_name in BOOLEAN_FIELDS:
                value = None if value is None else int(bool(value))
            elif isinstance(value, str) and not value.strip():
                value = None
            old_value = row[column]
            if field_name in JSON_FIELDS:
                old_value = json.loads(old_value or "[]")
                comparable = json.loads(value or "[]")
            else:
                comparable = value
            if old_value != comparable:
                updates[column] = value
                changed[field_name] = {"from": old_value, "to": comparable}
        if note is not None and row["reviewer_note"] != note:
            updates["reviewer_note"] = note
            changed["reviewer_note"] = {"from": row["reviewer_note"], "to": note}
        if new_status != previous_status:
            updates["status"] = new_status
            changed["status"] = {"from": previous_status, "to": new_status}
        if updates:
            updates["updated_at"] = self._now()
            assignments = ", ".join(f"{column} = ?" for column in updates)
            self.connection.execute(
                f"UPDATE program_drafts SET {assignments} WHERE draft_id = ?",
                (*updates.values(), draft_id),
            )
            refreshed = self._draft_row(draft_id)
            missing = self._missing_fields(refreshed)
            self.connection.execute(
                "UPDATE program_drafts SET missing_fields_json = ? WHERE draft_id = ?",
                (json.dumps(missing, ensure_ascii=False), draft_id),
            )
            self._record_review_event(
                draft_id,
                "save",
                previous_status,
                new_status,
                changed,
                reviewer,
                note,
            )
        self.connection.commit()
        return self.get_program_draft(draft_id)

    def review_program_draft(self, draft_id: int, reviewer: str = REVIEWER_DEFAULT, note: str | None = None):
        return self._set_draft_status(draft_id, "reviewed", "review", {"pending"}, reviewer, note)

    def reject_program_draft(self, draft_id: int, reviewer: str = REVIEWER_DEFAULT, note: str | None = None):
        return self._set_draft_status(draft_id, "rejected", "reject", {"pending", "reviewed"}, reviewer, note)

    def restore_program_draft(self, draft_id: int, reviewer: str = REVIEWER_DEFAULT, note: str | None = None):
        return self._set_draft_status(draft_id, "pending", "restore", {"rejected"}, reviewer, note)

    def _set_draft_status(
        self,
        draft_id: int,
        new_status: str,
        action: str,
        allowed_previous: set[str],
        reviewer: str,
        note: str | None,
    ) -> dict[str, Any]:
        row = self._draft_row(draft_id)
        if row["status"] not in allowed_previous:
            raise ValueError(f"cannot {action} draft in status {row['status']}")
        self.connection.execute(
            "UPDATE program_drafts SET status = ?, reviewer_note = COALESCE(?, reviewer_note), updated_at = ? WHERE draft_id = ?",
            (new_status, note, self._now(), draft_id),
        )
        self._record_review_event(draft_id, action, row["status"], new_status, {}, reviewer, note)
        self.connection.commit()
        return self.get_program_draft(draft_id)

    def publish_program_draft(self, draft_id: int, reviewer: str = REVIEWER_DEFAULT, note: str | None = None):
        row = self._draft_row(draft_id)
        if row["status"] != "reviewed":
            raise ValueError("only reviewed drafts can be published")
        validation_errors = self._publish_validation_errors(row)
        if validation_errors:
            raise ValueError(
                "draft is missing or invalid required fields: "
                + ", ".join(validation_errors)
            )
        missing_fields = self._missing_fields(row)
        now = self._now()
        reviewed = self.connection.execute(
            """
            SELECT created_at FROM review_events
            WHERE program_draft_id = ? AND new_status = 'reviewed'
            ORDER BY id DESC LIMIT 1
            """,
            (draft_id,),
        ).fetchone()
        reviewed_at = reviewed["created_at"] if reviewed else now
        directions = json.loads(row["research_directions_json"])
        degree_types = json.loads(row["degree_types_json"])
        existing = self.connection.execute(
            "SELECT published_program_id, program_id FROM published_programs WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        program_id = existing["program_id"] if existing else f"PUB-{draft_id:06d}"
        values = {
            "program_id": program_id,
            "draft_id": draft_id,
            "notice_id": row["notice_id"],
            "school": row["school_name"],
            "college": row["college_name"],
            "program_name": row["program_name"],
            "region": row["region"],
            "directions_json": json.dumps(directions, ensure_ascii=False),
            "degree_types_json": json.dumps(degree_types, ensure_ascii=False),
            "min_rank_percent": row["rank_requirement_percent"],
            "preferred_rank_percent": row["preferred_rank_percent"],
            "expected_school_tier": row["expected_school_tier"],
            "research_expectation": row["research_expectation"],
            "competition_expectation": row["competition_expectation"],
            "english_min": row["english_min"],
            "required_strength": row["required_strength"],
            "evidence_level": row["evidence_level"],
            "sample_size": row["sample_size"],
            "data_year": row["year"],
            "source_url": row["source_url"],
            "source_title": row["source_title"],
            "source_date": row["source_date"],
            "source_content_hash": row["source_content_hash"],
            "notes": row["reviewer_note"],
            "missing_fields_json": json.dumps(missing_fields, ensure_ascii=False),
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "published_at": now,
            "is_active": 1,
            "last_updated_at": now,
        }
        if existing:
            assignments = ", ".join(f"{key} = ?" for key in values if key not in {"program_id", "draft_id"})
            update_values = [values[key] for key in values if key not in {"program_id", "draft_id"}]
            self.connection.execute(
                f"UPDATE published_programs SET {assignments} WHERE draft_id = ?",
                (*update_values, draft_id),
            )
        else:
            columns = list(values)
            placeholders = ", ".join("?" for _ in columns)
            self.connection.execute(
                f"INSERT INTO published_programs ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(values[column] for column in columns),
            )
        self.connection.execute(
            "UPDATE program_drafts SET status = 'published', reviewer_note = COALESCE(?, reviewer_note), updated_at = ? WHERE draft_id = ?",
            (note, now, draft_id),
        )
        self._record_review_event(draft_id, "publish", "reviewed", "published", {}, reviewer, note)
        self.connection.commit()
        return self.get_program_draft(draft_id)

    def unpublish_program_draft(self, draft_id: int, reviewer: str = REVIEWER_DEFAULT, note: str | None = None):
        row = self._draft_row(draft_id)
        if row["status"] != "published":
            raise ValueError("only published drafts can be unpublished")
        now = self._now()
        self.connection.execute(
            "UPDATE published_programs SET is_active = 0, last_updated_at = ? WHERE draft_id = ?",
            (now, draft_id),
        )
        self.connection.execute(
            "UPDATE program_drafts SET status = 'reviewed', reviewer_note = COALESCE(?, reviewer_note), updated_at = ? WHERE draft_id = ?",
            (note, now, draft_id),
        )
        self._record_review_event(draft_id, "unpublish", "published", "reviewed", {}, reviewer, note)
        self.connection.commit()
        return self.get_program_draft(draft_id)

    def list_published_programs(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM published_programs WHERE is_active = 1 ORDER BY published_program_id"
        ).fetchall()

    def export_csv(self, path: str | Path, only_pending: bool = False) -> int:
        rows = self.rows_for_export(only_pending=only_pending)
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "notice_id",
            "source_id",
            "school",
            "college",
            "title",
            "url",
            "published_date",
            "data_year",
            "notice_type",
            "deadline",
            "event_date",
            "eligible_cohort",
            "cet4_min",
            "cet6_min",
            "rank_percent_max",
            "quota",
            "degree_types",
            "activity_mode",
            "privacy_sensitive",
            "conditions_text",
            "attachment_urls",
            "review_status",
            "reviewer_note",
        ]
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                facts = json.loads(row["facts_json"])
                writer.writerow(
                    {
                        "notice_id": row["notice_id"],
                        "source_id": row["source_id"],
                        "school": row["school"],
                        "college": row["college"],
                        "title": row["title"],
                        "url": row["url"],
                        "published_date": row["published_date"],
                        "data_year": row["data_year"],
                        "notice_type": row["notice_type"],
                        "deadline": facts.get("deadline"),
                        "event_date": facts.get("event_date"),
                        "eligible_cohort": facts.get("eligible_cohort"),
                        "cet4_min": facts.get("cet4_min"),
                        "cet6_min": facts.get("cet6_min"),
                        "rank_percent_max": facts.get("rank_percent_max"),
                        "quota": facts.get("quota"),
                        "degree_types": "|".join(facts.get("degree_types", [])),
                        "activity_mode": facts.get("activity_mode"),
                        "privacy_sensitive": facts.get("privacy_sensitive"),
                        "conditions_text": facts.get("conditions_text"),
                        "attachment_urls": "|".join(json.loads(row["attachment_urls_json"])),
                        "review_status": row["review_status"],
                        "reviewer_note": row["reviewer_note"],
                    }
                )
        return len(rows)
