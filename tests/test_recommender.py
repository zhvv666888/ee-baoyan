from app.models import ApplicantProfile, ProgramRecord
from app.recommender import applicant_strength, recommend


def profile(**overrides):
    data = {
        "school_name": "测试大学",
        "school_tier": "211",
        "major": "通信工程",
        "rank_percent": 8,
        "gpa": 3.7,
        "gpa_scale": 4.0,
        "cet4": 560,
        "cet6": 510,
        "research_level": 3,
        "competition_level": 3,
        "publication_level": 1,
        "project_level": 3,
        "directions": ["无线通信", "信号处理"],
        "preferred_regions": ["北京"],
        "degree_types": ["academic_master", "professional_master"],
        "risk_preference": "balanced",
    }
    data.update(overrides)
    return ApplicantProfile(**data)


def program(program_id: str, required_strength: float, direction: str = "无线通信"):
    return ProgramRecord(
        program_id=program_id,
        school="示例大学",
        college="信息学院",
        program_name="信息与通信工程",
        region="北京",
        directions=[direction],
        degree_types=["academic_master"],
        min_rank_percent=15,
        preferred_rank_percent=8,
        expected_school_tier=3.5,
        research_expectation=3,
        competition_expectation=2,
        english_min=450,
        required_strength=required_strength,
        evidence_level="B",
        sample_size=30,
        data_year=2026,
        is_demo=True,
    )


def test_strength_increases_for_better_profile():
    baseline = applicant_strength(profile())
    stronger = applicant_strength(
        profile(
            school_tier="985",
            rank_percent=2,
            research_level=5,
            publication_level=4,
        )
    )
    assert stronger > baseline


def test_recommendations_have_all_three_buckets():
    programs = [
        program("reach", 92),
        program("steady", 75),
        program("safe", 60),
    ]
    buckets = {item.bucket for item in recommend(profile(), programs, limit=3)}
    assert buckets == {"冲刺", "稳妥", "保底"}


def test_direction_match_ranks_higher():
    programs = [
        program("match", 72, "无线通信"),
        program("mismatch", 72, "集成电路"),
    ]
    result = recommend(profile(), programs, limit=6)
    by_id = {item.program_id: item for item in result}
    assert by_id["match"].match_score > by_id["mismatch"].match_score


def test_demo_data_is_flagged():
    item = recommend(profile(), [program("demo", 70)], limit=3)[0]
    assert item.is_demo is True
    assert any("演示数据" in risk for risk in item.risks)
