from __future__ import annotations

from datetime import date

from .models import ApplicantProfile, ProgramRecord, RecommendationItem, RiskBucket


TIER_SCORE = {
    "top985": 5.0,
    "985": 4.4,
    "211": 3.6,
    "double_first_class": 3.1,
    "ordinary": 2.2,
}

EVIDENCE_BASE = {"A": 0.90, "B": 0.78, "C": 0.62, "D": 0.45}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def applicant_strength(profile: ApplicantProfile) -> float:
    tier = TIER_SCORE[profile.school_tier] / 5 * 20
    rank = (1 - min(profile.rank_percent, 50) / 50) * 30
    gpa = profile.normalized_gpa * 10
    english_score = max(profile.cet6 or 0, profile.cet4 or 0)
    english = min(english_score / 600, 1) * 8
    research = profile.research_level / 5 * 14
    publication = profile.publication_level / 5 * 7
    competition = profile.competition_level / 5 * 6
    project = profile.project_level / 5 * 5
    return round(_clamp(tier + rank + gpa + english + research + publication + competition + project), 1)


def _direction_score(profile: ApplicantProfile, program: ProgramRecord) -> tuple[float, bool]:
    if not profile.directions:
        return 7.0, False
    if not program.directions:
        return 0.0, False
    profile_dirs = {item.lower() for item in profile.directions}
    program_dirs = {item.lower() for item in program.directions}
    overlap = profile_dirs & program_dirs
    if overlap:
        return 14.0, True
    return 1.0, False


def _region_score(profile: ApplicantProfile, program: ProgramRecord) -> float:
    if not profile.preferred_regions:
        return 5.0
    return 8.0 if program.region in profile.preferred_regions else 1.0


def _degree_score(profile: ApplicantProfile, program: ProgramRecord) -> tuple[float, bool]:
    overlap = set(profile.degree_types) & set(program.degree_types)
    return (8.0, True) if overlap else (0.0, False)


def _profile_fit(profile: ApplicantProfile, program: ProgramRecord) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []
    score = 0.0

    if program.expected_school_tier is None:
        risks.append("官方公告未明确项目层次，不能据此视为低门槛")
    else:
        tier_gap = TIER_SCORE[profile.school_tier] - program.expected_school_tier
        score += _clamp(8 + tier_gap * 3, 0, 14)
        if tier_gap >= 0:
            reasons.append("本科院校背景达到项目层次画像")
        elif tier_gap < -0.8:
            risks.append("本科院校层次与项目层次画像存在差距")

    if program.preferred_rank_percent is None or program.min_rank_percent is None:
        risks.append("官方公告未明确排名线，不能视为低门槛")
    elif profile.rank_percent <= program.preferred_rank_percent:
        score += 20
        reasons.append(f"专业排名前 {profile.rank_percent:g}%，优于项目偏好线")
    elif profile.rank_percent <= program.min_rank_percent:
        score += 13
        reasons.append("专业排名满足项目基础筛选线")
    else:
        score += 2
        risks.append(f"专业排名低于项目基础线（前 {program.min_rank_percent:g}%）")

    if program.research_expectation is None:
        risks.append("官方公告未明确科研门槛，不能视为低门槛")
    else:
        research_gap = profile.research_level - program.research_expectation
        score += _clamp(9 + research_gap * 2.5, 0, 15)
        if research_gap >= 0:
            reasons.append("科研经历与项目偏好较匹配")
        elif research_gap <= -1.5:
            risks.append("科研深度可能不足，需要突出个人贡献和技术细节")

    if program.competition_expectation is None:
        risks.append("官方公告未明确竞争强度，不能视为低门槛")
    else:
        competition_gap = profile.competition_level - program.competition_expectation
        score += _clamp(5 + competition_gap * 1.5, 0, 9)
        if competition_gap >= 1:
            reasons.append("竞赛经历可形成额外加分")

    english_value = max(profile.cet6 or 0, profile.cet4 or 0)
    if program.english_min is None:
        risks.append("官方公告未明确英语分数门槛，不能视为无要求")
    elif program.english_min == 0 or english_value >= program.english_min:
        score += 7
        if english_value:
            reasons.append("英语成绩达到项目要求")
    else:
        score += 1
        risks.append(f"英语成绩未达到项目门槛 {program.english_min}")

    direction_points, direction_match = _direction_score(profile, program)
    score += direction_points
    if direction_match:
        reasons.append("研究方向存在直接交集")
    else:
        risks.append("研究方向匹配度有限，建议核对导师与实验室")

    score += _region_score(profile, program)
    if profile.preferred_regions:
        if program.region in profile.preferred_regions:
            reasons.append("项目地点符合个人地区偏好")
        else:
            risks.append("项目地点不在个人地区偏好内")
    degree_points, degree_match = _degree_score(profile, program)
    score += degree_points
    if degree_match:
        reasons.append("官方公告明确包含个人偏好的培养类型")
    else:
        risks.append("培养类型与个人偏好不一致")

    # GPA and project/publication serve as tie breakers.
    score += profile.normalized_gpa * 5
    score += profile.project_level / 5 * 3
    score += profile.publication_level / 5 * 4

    return round(_clamp(score), 1), reasons, risks


def _confidence(program: ProgramRecord) -> float:
    base = EVIDENCE_BASE[program.evidence_level]
    sample_factor = min(program.sample_size / 50, 1) * 0.07
    age = max(date.today().year - program.data_year, 0)
    age_penalty = min(age * 0.04, 0.20)
    demo_penalty = 0.18 if program.is_demo else 0.0
    missing_penalty = min(len(program.missing_fields) * 0.04, 0.28)
    return round(_clamp((base + sample_factor - age_penalty - demo_penalty - missing_penalty) * 100), 1)


def _bucket(margin: float, risk_preference: str) -> RiskBucket:
    offsets = {
        "conservative": (3.0, 13.0),
        "balanced": (-3.0, 9.0),
        "aggressive": (-8.0, 5.0),
    }
    reach_upper, safe_lower = offsets[risk_preference]
    if margin < reach_upper:
        return "冲刺"
    if margin < safe_lower:
        return "稳妥"
    return "保底"


def recommend(profile: ApplicantProfile, programs: list[ProgramRecord], limit: int = 18) -> list[RecommendationItem]:
    strength = applicant_strength(profile)
    output: list[RecommendationItem] = []

    for program in programs:
        fit_score, reasons, risks = _profile_fit(profile, program)
        if program.required_strength is None:
            margin = -20.0
            bucket = "冲刺"
            risks.insert(0, "项目综合门槛未明确，暂按高风险处理，不视为低门槛")
        else:
            margin = strength - program.required_strength
            bucket = _bucket(margin, profile.risk_preference)
        combined = round(_clamp(fit_score * 0.68 + (50 + margin * 2) * 0.32), 1)

        if program.is_demo:
            risks.append("当前为演示数据，不能用于真实申请决策")
        if program.evidence_level in {"C", "D"}:
            risks.append("证据等级较低，应补充官方通知或真实案例")

        output.append(
            RecommendationItem(
                program_id=program.program_id,
                school=program.school,
                college=program.college,
                program_name=program.program_name,
                region=program.region,
                bucket=bucket,
                match_score=combined,
                applicant_strength=strength,
                required_strength=program.required_strength,
                confidence=_confidence(program),
                reasons=reasons[:4],
                risks=risks[:4],
                evidence_level=program.evidence_level,
                data_year=program.data_year,
                source_url=program.source_url,
                is_demo=program.is_demo,
                source_title=program.source_title,
                source_date=program.source_date,
                reviewed_at=program.reviewed_at,
                published_at=program.published_at,
                missing_fields=program.missing_fields,
                data_complete=not program.missing_fields,
            )
        )

    # First preserve a useful spread across buckets, then rank inside each group.
    bucket_order = {"冲刺": 0, "稳妥": 1, "保底": 2}
    output.sort(key=lambda item: (bucket_order[item.bucket], -item.match_score, -item.confidence))

    if limit <= 0:
        return output

    target_per_bucket = max(limit // 3, 1)
    selected: list[RecommendationItem] = []
    for bucket in ("冲刺", "稳妥", "保底"):
        selected.extend([item for item in output if item.bucket == bucket][:target_per_bucket])

    if len(selected) < limit:
        selected_ids = {item.program_id for item in selected}
        selected.extend([item for item in output if item.program_id not in selected_ids][: limit - len(selected)])

    return selected[:limit]
