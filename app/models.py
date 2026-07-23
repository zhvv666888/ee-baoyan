from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


SchoolTier = Literal["top985", "985", "211", "double_first_class", "ordinary"]
DegreeType = Literal["academic_master", "professional_master", "direct_phd"]
RiskBucket = Literal["冲刺", "稳妥", "保底"]


class ApplicantProfile(BaseModel):
    school_name: str = Field(min_length=1, max_length=100)
    school_tier: SchoolTier
    major: str = Field(min_length=1, max_length=100)
    rank_percent: float = Field(gt=0, le=100, description="专业排名百分比，越小越好")
    gpa: float = Field(ge=0, le=5)
    gpa_scale: float = Field(default=4.0, gt=0, le=5)
    cet4: int | None = Field(default=None, ge=0, le=710)
    cet6: int | None = Field(default=None, ge=0, le=710)
    english_other: str | None = Field(default=None, max_length=100)
    research_level: int = Field(default=0, ge=0, le=5)
    competition_level: int = Field(default=0, ge=0, le=5)
    publication_level: int = Field(default=0, ge=0, le=5)
    project_level: int = Field(default=0, ge=0, le=5)
    directions: list[str] = Field(default_factory=list)
    preferred_regions: list[str] = Field(default_factory=list)
    degree_types: list[DegreeType] = Field(default_factory=lambda: ["academic_master", "professional_master"])
    risk_preference: Literal["conservative", "balanced", "aggressive"] = "balanced"

    @field_validator("directions", "preferred_regions")
    @classmethod
    def clean_text_list(cls, values: list[str]) -> list[str]:
        cleaned = []
        for item in values:
            item = item.strip()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @property
    def normalized_gpa(self) -> float:
        return min(max(self.gpa / self.gpa_scale, 0), 1)


class ProgramRecord(BaseModel):
    program_id: str
    school: str
    college: str
    program_name: str
    region: str
    directions: list[str]
    degree_types: list[DegreeType]
    min_rank_percent: float | None = Field(default=None, gt=0, le=100)
    preferred_rank_percent: float | None = Field(default=None, gt=0, le=100)
    expected_school_tier: float | None = Field(default=None, ge=0, le=5)
    research_expectation: float | None = Field(default=None, ge=0, le=5)
    competition_expectation: float | None = Field(default=None, ge=0, le=5)
    english_min: int | None = Field(default=None, ge=0, le=710)
    required_strength: float | None = Field(default=None, ge=0, le=100)
    evidence_level: Literal["A", "B", "C", "D"]
    sample_size: int = Field(default=0, ge=0)
    data_year: int = Field(ge=2000, le=2100)
    source_url: str | None = None
    notes: str | None = None
    is_demo: bool = True
    source_title: str | None = None
    source_date: str | None = None
    reviewed_at: str | None = None
    published_at: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    program_id: str
    school: str
    college: str
    program_name: str
    region: str
    bucket: RiskBucket
    match_score: float
    applicant_strength: float
    required_strength: float | None
    confidence: float
    reasons: list[str]
    risks: list[str]
    evidence_level: str
    data_year: int
    source_url: str | None
    is_demo: bool
    source_title: str | None = None
    source_date: str | None = None
    reviewed_at: str | None = None
    published_at: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    data_complete: bool = True


class RecommendationResponse(BaseModel):
    disclaimer: str
    profile_summary: dict[str, str | float | int]
    recommendations: list[RecommendationItem]
    data_mode: Literal["demo", "published"] = "demo"
    data_notice: str | None = None


class DraftUpdateRequest(BaseModel):
    fields: dict[str, object] = Field(default_factory=dict)
    reviewer: str = "local-reviewer"
    note: str | None = None


class ReviewActionRequest(BaseModel):
    reviewer: str = "local-reviewer"
    note: str | None = None
