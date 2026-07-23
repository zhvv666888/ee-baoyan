from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from crawler.storage import NoticeStore

from .models import (
    ApplicantProfile,
    DraftUpdateRequest,
    RecommendationResponse,
    ReviewActionRequest,
)
from .recommender import applicant_strength, recommend
from .repository import DEFAULT_PUBLISHED_DATABASE, get_data_mode, get_program_repository


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
ADMIN_STATIC_DIR = STATIC_DIR
DATA_MODE = get_data_mode()
PUBLISHED_DATABASE = Path(os.getenv("APP_PUBLISHED_DATABASE", "") or DEFAULT_PUBLISHED_DATABASE)

app = FastAPI(
    title="EE 保研罗盘 API",
    version="0.2.0",
    description="面向电子信息与通信工程学生的可解释保研院校匹配与官方数据采集 MVP。",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_mode": DATA_MODE}


@app.get("/admin/review", include_in_schema=False)
def admin_review_page() -> FileResponse:
    return FileResponse(ADMIN_STATIC_DIR / "admin.html")


def _with_store():
    return NoticeStore(PUBLISHED_DATABASE)


@app.get("/api/admin/drafts")
def list_admin_drafts(
    status: str | None = Query(default=None),
    school: str | None = Query(default=None),
    college: str | None = Query(default=None),
    year: int | None = Query(default=None),
    notice_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
) -> dict[str, object]:
    try:
        with _with_store() as store:
            return {"drafts": store.list_program_drafts(status, school, college, year, notice_type, limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/drafts/{draft_id}")
def get_admin_draft(draft_id: int) -> dict[str, object]:
    try:
        with _with_store() as store:
            return {
                "draft": store.get_program_draft(draft_id),
                "history": store.get_review_events(draft_id),
            }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/notices/{notice_id}/draft")
def create_admin_draft(notice_id: str) -> dict[str, object]:
    try:
        with _with_store() as store:
            draft = store.create_program_draft_from_notice(notice_id)
            if draft is None:
                raise HTTPException(
                    status_code=409,
                    detail="This notice is privacy-sensitive or cannot generate a program draft.",
                )
            return {"draft": draft}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/admin/drafts/{draft_id}")
def update_admin_draft(draft_id: int, request: DraftUpdateRequest) -> dict[str, object]:
    try:
        with _with_store() as store:
            return {
                "draft": store.update_program_draft(
                    draft_id, request.fields, request.reviewer, request.note
                )
            }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _admin_transition(draft_id: int, action: str, request: ReviewActionRequest) -> dict[str, object]:
    try:
        with _with_store() as store:
            methods = {
                "review": store.review_program_draft,
                "approve": store.review_program_draft,
                "reject": store.reject_program_draft,
                "restore": store.restore_program_draft,
                "publish": store.publish_program_draft,
                "unpublish": store.unpublish_program_draft,
            }
            draft = methods[action](draft_id, request.reviewer, request.note)
            return {"draft": draft}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/drafts/{draft_id}/review")
def review_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "review", request)


@app.post("/api/admin/drafts/{draft_id}/approve")
def approve_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "approve", request)


@app.post("/api/admin/drafts/{draft_id}/reject")
def reject_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "reject", request)


@app.post("/api/admin/drafts/{draft_id}/restore")
def restore_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "restore", request)


@app.post("/api/admin/drafts/{draft_id}/publish")
def publish_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "publish", request)


@app.post("/api/admin/drafts/{draft_id}/unpublish")
def unpublish_admin_draft(draft_id: int, request: ReviewActionRequest) -> dict[str, object]:
    return _admin_transition(draft_id, "unpublish", request)


@app.post("/api/recommend", response_model=RecommendationResponse)
def create_recommendation(
    profile: ApplicantProfile,
    limit: int = Query(default=18, ge=3, le=60),
) -> RecommendationResponse:
    try:
        programs = get_program_repository(DATA_MODE).list_programs()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = recommend(profile, programs, limit=limit)
    if DATA_MODE == "published":
        disclaimer = (
            "当前推荐仅使用已审核发布的院校项目数据。匹配分用于排序和解释，不是录取概率。"
        )
        data_notice = (
            "当前没有已审核发布的真实院校项目数据。"
            if not programs
            else "结果来自 published 数据；请继续核对官方公告和数据更新时间。"
        )
    else:
        disclaimer = (
            "本版本使用演示院校画像，仅用于验证产品流程与算法解释方式。"
            "不得将冲稳保标签或匹配分视为录取概率；真实使用前必须替换为可追溯数据。"
        )
        data_notice = "当前为 demo 模式，结果不代表真实招生结论。"
    return RecommendationResponse(
        disclaimer=disclaimer,
        profile_summary={
            "school": profile.school_name,
            "major": profile.major,
            "rank_percent": profile.rank_percent,
            "applicant_strength": applicant_strength(profile),
            "risk_preference": profile.risk_preference,
        },
        recommendations=results,
        data_mode=DATA_MODE,
        data_notice=data_notice,
    )
