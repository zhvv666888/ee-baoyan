from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


NoticeType = Literal[
    "summer_camp_notice",
    "selection_notice",
    "pre_recommendation_notice",
    "interview_list",
    "excellent_camper_list",
    "proposed_admission_list",
    "admission_policy",
    "program_catalog",
    "other",
]


@dataclass(slots=True)
class SourceConfig:
    source_id: str
    school: str
    college: str
    seed_urls: list[str]
    allowed_domains: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str] = field(default_factory=list)
    detail_url_patterns: list[str] = field(default_factory=list)
    content_selectors: list[str] = field(default_factory=list)
    title_selectors: list[str] = field(default_factory=list)
    date_selectors: list[str] = field(default_factory=list)
    pagination_keywords: list[str] = field(default_factory=lambda: ["下一页", "下页", "next"])
    max_list_pages: int = 3
    max_notices_per_run: int = 80
    enabled: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceConfig":
        return cls(**payload)


@dataclass(slots=True)
class CrawlSettings:
    user_agent: str
    request_delay_seconds: float = 2.0
    timeout_seconds: float = 20.0
    cache_ttl_hours: int = 24
    max_response_bytes: int = 8_000_000
    download_pdf_text: bool = True
    max_pdf_bytes: int = 15_000_000
    privacy_mode: str = "aggregate_only"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CrawlSettings":
        return cls(**payload)


@dataclass(slots=True)
class CandidateLink:
    title: str
    url: str
    source_id: str
    list_url: str


@dataclass(slots=True)
class ExtractedFacts:
    deadline: str | None = None
    event_date: str | None = None
    eligible_cohort: str | None = None
    cet4_min: int | None = None
    cet6_min: int | None = None
    rank_percent_max: float | None = None
    quota: int | None = None
    degree_types: list[str] = field(default_factory=list)
    activity_mode: str | None = None
    conditions_text: str | None = None
    privacy_sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "deadline": self.deadline,
            "event_date": self.event_date,
            "eligible_cohort": self.eligible_cohort,
            "cet4_min": self.cet4_min,
            "cet6_min": self.cet6_min,
            "rank_percent_max": self.rank_percent_max,
            "quota": self.quota,
            "degree_types": self.degree_types,
            "activity_mode": self.activity_mode,
            "conditions_text": self.conditions_text,
            "privacy_sensitive": self.privacy_sensitive,
        }


@dataclass(slots=True)
class CrawledNotice:
    notice_id: str
    source_id: str
    school: str
    college: str
    title: str
    url: str
    published_date: date | None
    data_year: int | None
    notice_type: NoticeType
    content_text: str
    content_sha256: str
    fetched_at: datetime
    facts: ExtractedFacts
    attachment_urls: list[str] = field(default_factory=list)
    source_list_url: str | None = None
    http_status: int = 200
    needs_review: bool = True

    def to_record(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "source_id": self.source_id,
            "school": self.school,
            "college": self.college,
            "title": self.title,
            "url": self.url,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "data_year": self.data_year,
            "notice_type": self.notice_type,
            "content_text": self.content_text,
            "content_sha256": self.content_sha256,
            "fetched_at": self.fetched_at.isoformat(),
            "facts": self.facts.to_dict(),
            "attachment_urls": self.attachment_urls,
            "source_list_url": self.source_list_url,
            "http_status": self.http_status,
            "needs_review": self.needs_review,
        }
