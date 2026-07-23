from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http import FetchResult, PoliteHttpClient
from .models import CandidateLink, CrawledNotice, ExtractedFacts, NoticeType, SourceConfig


PRIVACY_NOTICE_PLACEHOLDER = "[隐私敏感名单公告：正文和附件个人明细未持久化，仅保留官方来源与内容哈希。]"


DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[年./-]\s*(?P<m>\d{1,2})[月./-]\s*(?P<d>\d{1,2})日?"),
    re.compile(r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})"),
]


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = " ".join(node.stripped_strings).strip()
            if value:
                return value
    return None


def _pick_content_node(soup: BeautifulSoup, selectors: list[str]):
    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) >= 80:
            return node
    for selector in ("article", ".v_news_content", ".content", ".article", "main"):
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) >= 80:
            return node
    return soup.body or soup


def _clean_text(node) -> str:
    for tag in node.select("script, style, nav, footer, form, noscript"):
        tag.decompose()
    lines = [re.sub(r"\s+", " ", line).strip() for line in node.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)



def redact_personal_data(text: str) -> str:
    """Remove direct contact and identity-like strings before persistence."""
    patterns = [
        (r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL_REDACTED]"),
        (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[PHONE_REDACTED]"),
        (r"(?<!\d)0\d{2,3}[-— ]?\d{7,8}(?!\d)", "[PHONE_REDACTED]"),
        (r"(?i)(?:QQ群|QQ|群号|交流群)\s*[：:]?\s*\d{5,12}", "[GROUP_REDACTED]"),
        (r"(?<!\d)\d{17}[0-9Xx](?!\d)", "[ID_REDACTED]"),
    ]
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted

def parse_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            return date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        except ValueError:
            continue
    return None


def classify_notice(title: str, content: str) -> NoticeType:
    # Prefer an explicit title label over related notices quoted in the body.
    # A summer-camp notice may link to an excellent-undergraduate selection
    # plan without becoming a selection notice itself.
    if "拟录取名单" in title or "拟录取结果" in title:
        return "proposed_admission_list"
    if "优秀营员名单" in title or "优秀营员结果" in title:
        return "excellent_camper_list"
    if "面试名单" in title or "复试名单" in title or "入围名单" in title:
        return "interview_list"
    if "夏令营" in title:
        return "summer_camp_notice"
    if "优秀本科生选拔计划" in title or "优本计划" in title:
        return "selection_notice"
    text = f"{title}\n{content[:1200]}"
    rules: list[tuple[NoticeType, tuple[str, ...]]] = [
        ("proposed_admission_list", ("拟录取名单", "拟录取结果")),
        ("excellent_camper_list", ("优秀营员名单", "优营名单", "优秀营员结果")),
        ("interview_list", ("面试名单", "复试名单", "入围名单", "入选营员名单")),
        ("pre_recommendation_notice", ("预推免", "接收推荐免试", "推免报名通知", "九推")),
        ("selection_notice", ("优秀本科生选拔计划", "优选计划", "遴选计划")),
        ("summer_camp_notice", ("夏令营通知", "暑期夏令营", "优秀大学生夏令营")),
        ("admission_policy", ("实施办法", "接收办法", "招生办法", "申请条件")),
        ("program_catalog", ("招生目录", "专业目录")),
    ]
    for notice_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return notice_type
    return "other"


def is_privacy_sensitive_notice(title: str, content: str, notice_type: NoticeType) -> bool:
    """Detect result/list notices before any body text is persisted."""
    sensitive_types = {
        "interview_list",
        "excellent_camper_list",
        "proposed_admission_list",
    }
    sensitive_markers = (
        "面试名单",
        "复试名单",
        "入围名单",
        "入选营员名单",
        "优秀营员名单",
        "优营名单",
        "拟录取名单",
        "考核结果",
        "在校生注册学号",
    )
    title_type = classify_notice(title, "")
    combined = f"{title}\n{content[:2000]}"
    has_identity_columns = "姓名" in combined and (
        "在校生注册学号" in combined
        or ("学号" in combined and any(marker in combined for marker in ("成绩", "报名专业", "录取结果")))
    )
    return title_type in sensitive_types or any(marker in title for marker in sensitive_markers) or has_identity_columns


def _extract_conditions(text: str) -> str | None:
    start = re.search(r"(?:^|\n)[一二三四五六七八九十\d、.．\s]*申请条件\s*", text)
    if not start:
        return None
    tail = text[start.end() :]
    end = re.search(r"\n[一二三四五六七八九十][、.．\s]+(?:申请|报名|活动|材料|流程|时间|安排)", tail)
    section = tail[: end.start()] if end else tail[:1800]
    section = section.strip()
    return section[:1800] or None


def extract_facts(title: str, text: str, notice_type: NoticeType) -> ExtractedFacts:
    original_text = text
    # Official pages frequently insert line breaks inside dates and times.
    # Normalize scalar fact extraction while retaining original formatting for
    # the conditions excerpt.
    text = re.sub(r"\s+", " ", text).strip()
    deadline_match = re.search(
        r"(?:报名|申请|提交)?截止(?:时间|日期)?\s*[：:]?\s*([^。；;\n]{4,50})",
        text,
    )
    event_match = re.search(
        r"(?:将于|活动时间|面试时间|考核时间)\s*[：:]?\s*((?:20\d{2}年)?\s*\d{1,2}月\s*\d{1,2}\s*日(?:[^。；;\n]{0,20})?)",
        text,
    )
    cohort_match = re.search(r"(20\d{2})\s*级(?:本科)?", text)

    cet4 = None
    cet6 = None
    for match in re.finditer(r"(?:CET\s*[-－]?\s*([46])|大学英语([四六])级)[^\d]{0,16}(\d{3})", text, re.I):
        level = match.group(1) or ("4" if match.group(2) == "四" else "6")
        score = int(match.group(3))
        if level == "4":
            cet4 = max(cet4 or 0, score)
        else:
            cet6 = max(cet6 or 0, score)

    rank = None
    rank_patterns = [
        r"(?:专业|综合)?排名\s*(?:位于|为)?\s*(?:前|不低于|达到)?\s*(\d+(?:\.\d+)?)\s*%",
        r"前\s*(\d+(?:\.\d+)?)\s*%",
    ]
    for pattern in rank_patterns:
        match = re.search(pattern, text)
        if match:
            rank = float(match.group(1))
            break

    quota_match = re.search(r"拟(?:招收|接收|选拔|录取)[^\d]{0,8}(\d{1,4})\s*人", text)
    degree_types: list[str] = []
    if "硕士" in text or "硕士研究生" in text:
        degree_types.extend(["academic_master", "professional_master"])
    if "博士" in text or "直博" in text:
        degree_types.append("direct_phd")
    degree_types = list(dict.fromkeys(degree_types))

    mode = None
    if "线上" in text or "在线" in text:
        mode = "online"
    if "线下" in text or "现场" in text:
        mode = "hybrid" if mode == "online" else "offline"

    deadline_value = deadline_match.group(1).strip() if deadline_match else None
    if deadline_value:
        deadline_value = re.split(r"\s*(?:报名链接|申请链接|填报链接|链接)", deadline_value)[0].strip(" ，,")
    event_value = event_match.group(1).strip() if event_match else None
    if event_value:
        date_value = re.search(
            r"(?:20\d{2}年\s*)?\d{1,2}月\s*\d{1,2}\s*日"
            r"(?:\s*\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?)?",
            event_value,
        )
        event_value = date_value.group(0).strip() if date_value else event_value

    privacy_sensitive = is_privacy_sensitive_notice(title, text, notice_type)
    return ExtractedFacts(
        deadline=deadline_value,
        event_date=event_value,
        eligible_cohort=cohort_match.group(1) if cohort_match else None,
        cet4_min=cet4,
        cet6_min=cet6,
        rank_percent_max=rank,
        quota=int(quota_match.group(1)) if quota_match else None,
        degree_types=degree_types,
        activity_mode=mode,
        conditions_text=_extract_conditions(original_text),
        privacy_sensitive=privacy_sensitive,
    )


def _attachment_urls(node, base_url: str, allowed_domains: list[str]) -> list[str]:
    from .discovery import is_allowed_domain

    links: list[str] = []
    for anchor in node.select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        url = urljoin(base_url, href)
        lower = url.lower().split("?", 1)[0]
        if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")) and is_allowed_domain(url, allowed_domains):
            if url not in links:
                links.append(url)
    return links


def extract_pdf_text(client: PoliteHttpClient, url: str, max_bytes: int) -> str:
    result = client.fetch(url, max_bytes=max_bytes)
    reader = PdfReader(io.BytesIO(result.content))
    pages: list[str] = []
    for page in reader.pages[:80]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def extract_notice(
    result: FetchResult,
    candidate: CandidateLink,
    source: SourceConfig,
) -> CrawledNotice:
    soup = BeautifulSoup(result.text, "lxml")
    title = _first_text(soup, source.title_selectors) or _first_text(soup, ["h1", "h2", "title"]) or candidate.title
    content_node = _pick_content_node(soup, source.content_selectors)
    original_content_text = _clean_text(content_node)

    date_text = _first_text(soup, source.date_selectors)
    publication_match = re.search(
        r"(?:发布时间|发布日期|发布于)\s*[：:]\s*(20\d{2}[-/]\d{1,2}[-/]\d{1,2})",
        result.text[:30000],
    )
    published_date = parse_date(publication_match.group(1)) if publication_match else parse_date(date_text or result.text[:4000])
    notice_type = classify_notice(title, original_content_text)
    facts = extract_facts(title, original_content_text, notice_type)
    content_sha256 = hashlib.sha256(original_content_text.encode("utf-8")).hexdigest()
    if facts.privacy_sensitive:
        content_text = PRIVACY_NOTICE_PLACEHOLDER
    else:
        content_text = redact_personal_data(original_content_text)
    notice_id = hashlib.sha256(result.url.encode("utf-8")).hexdigest()[:24]
    year_match = re.search(r"20\d{2}", title)
    data_year = int(year_match.group()) if year_match else (published_date.year if published_date else None)

    return CrawledNotice(
        notice_id=notice_id,
        source_id=source.source_id,
        school=source.school,
        college=source.college,
        title=title[:500],
        url=result.url,
        published_date=published_date,
        data_year=data_year,
        notice_type=notice_type,
        content_text=content_text,
        content_sha256=content_sha256,
        fetched_at=datetime.now(timezone.utc),
        facts=facts,
        attachment_urls=_attachment_urls(content_node, result.url, source.allowed_domains),
        source_list_url=candidate.list_url,
        http_status=result.status_code,
        needs_review=True,
    )
