"""Google Sheets API v4 호출. 루트의 google-key.json 파일로 인증."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import httpx
from google.oauth2 import service_account

from app.admin.ops._paths import project_root

logger = logging.getLogger(__name__)

GOOGLE_SHEETS_BASE = "https://sheets.googleapis.com/v4"


def _google_api_error_message(resp: httpx.Response) -> str:
    """Google API JSON 오류에서 짧은 message 문자열만 추출."""
    try:
        data = resp.json()
        err = data.get("error")
        if isinstance(err, dict):
            return (err.get("message") or "").strip()
        if isinstance(err, str):
            return err.strip()
    except Exception:
        pass
    return (resp.text or "")[:280].strip()


def _friendly_sheets_read_error(resp: httpx.Response, tab_name: str) -> str:
    """사용자·프론트에 보일 짧은 한국어 설명(긴 URL은 넣지 않음)."""
    api = _google_api_error_message(resp)
    hint = (
        f"시트를 읽을 수 없습니다(HTTP {resp.status_code}). "
        f"요청 탭 이름: {tab_name!r} — 스프레드시트 하단 탭과 `.env`의 CHANNEL_*_TAB 이 "
        f"한 글자까지 동일한지 확인하세요(오타·중복 글자 흔함). "
        f"google-key.json 서비스 계정에 해당 스프레드시트 편집 권한이 있어야 합니다."
    )
    if api and len(api) < 240:
        return hint + " Google: " + api
    return hint
SCOPE = "https://www.googleapis.com/auth/spreadsheets"

# 프로젝트 루트 기준 google-key.json
_KEY_FILE = project_root() / "google-key.json"


def _get_access_token_from_keyfile() -> str:
    """프로젝트 루트의 google-key.json을 읽어 액세스 토큰 반환."""
    if not _KEY_FILE.exists():
        raise FileNotFoundError(
            "프로젝트 루트에 google-key.json 파일이 없습니다. "
            "구글 클라우드 콘솔에서 서비스 계정 키 JSON을 다운로드한 뒤, "
            "해당 내용을 프로젝트 루트에 google-key.json으로 저장하세요."
        )
    credentials = service_account.Credentials.from_service_account_file(
        str(_KEY_FILE), scopes=[SCOPE]
    )
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    return credentials.token


async def append_rows(
    spreadsheet_id: str,
    sheet_tab_name: str,
    rows: list[list[Any]],
    column_range: str = "A:K",
) -> None:
    """Sheets API v4로 행 추가. range_param을 '탭이름'!열범위 형태로 고정해 다른 탭에 간섭하지 않음."""
    import asyncio
    access_token = await asyncio.to_thread(_get_access_token_from_keyfile)

    # 반드시 '{sheet_tab_name}'!{column_range} 형태로 생성해 다른 탭(유튜브 등) 미침
    if " " in sheet_tab_name or "'" in sheet_tab_name:
        range_param = f"'{sheet_tab_name}'!{column_range}"
    else:
        range_param = f"{sheet_tab_name}!{column_range}"

    url = f"{GOOGLE_SHEETS_BASE}/spreadsheets/{spreadsheet_id}/values/{range_param}:append"

    params = {
        "valueInputOption": "USER_ENTERED",
        "insertDataOption": "INSERT_ROWS",
    }
    body = {"values": rows}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params=params,
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()


def build_history_rows(
    items: list[dict],
    custom_prompt: str,
) -> list[list[Any]]:
    """
    AI 큐레이션 결과를 히스토리 시트용 행으로 변환.
    열 구성: A=No, B=일시, C=지시사항, D=키워드, E=추천사유, F=쿠팡검색어
    """
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for item in items:
        if isinstance(item, dict):
            keyword = item.get("original_keyword") or ""
            reason = item.get("reason") or ""
            search_query = item.get("coupang_search_query") or ""
        else:
            keyword = getattr(item, "original_keyword", "") or ""
            reason = getattr(item, "reason", "") or ""
            search_query = getattr(item, "coupang_search_query", "") or ""
        row = ["=ROW()-1", now, custom_prompt, keyword, reason, search_query]
        rows.append(row)
    return rows


def build_rows(products: list[dict], channel_id: str = "unknown") -> list[list[Any]]:
    """
    기획안 스펙 반영 (A~K열 총 11개 컬럼)
    A(No), B(카테고리), C(상품명), D(가격), E(이미지URL), F(쿠팡URL),
    G(딥링크), H(영상No), I(게시상태), J(등록일), K(subId)
    K열 값은 딥링크 API subId 와 동일(고정 shortcrew) — short-mall 과 동일 규칙.
    """
    from datetime import datetime

    from app.admin.ops.services.coupang import COUPANG_DEEPLINK_API_SUB_ID

    channel_id = channel_id or "unknown"
    rows = []
    for p in products:
        video_no = p.get("videoNo") or ""

        row = [
            "=ROW()-1",  # A: No (구글 시트 수식, 2행이면 2-1=1로 자동 번호)
            p.get("category") or "",  # B: 상품카테고리
            p.get("productName") or "",  # C: 상품명
            p.get("price") or 0,  # D: 가격
            p.get("imageUrl") or "",  # E: 이미지URL
            p.get("productUrl") or "",  # F: 쿠팡URL
            p.get("deepLink") or "",  # G: 딥링크 (FastAPI 파트너스 API가 자동 생성)
            video_no,  # H: 연관영상No
            "대기",  # I: 게시상태 (고정)
            datetime.now().strftime("%Y-%m-%d"),  # J: 등록일
            COUPANG_DEEPLINK_API_SUB_ID,  # K: subId (딥링크 API subId 와 동일·고정)
        ]
        rows.append(row)
    return rows


async def get_existing_values(
    spreadsheet_id: str,
    sheet_tab_name: str,
    column: str = "F",
) -> set[str]:
    """시트의 특정 열(기본 F열, 쿠팡 URL) 값을 읽어 중복 체크용 set으로 반환."""
    access_token = await asyncio.to_thread(_get_access_token_from_keyfile)

    if " " in sheet_tab_name or "'" in sheet_tab_name:
        range_param = f"'{sheet_tab_name}'!{column}:{column}"
    else:
        range_param = f"{sheet_tab_name}!{column}:{column}"

    encoded_range = quote(range_param, safe="")
    url = f"{GOOGLE_SHEETS_BASE}/spreadsheets/{spreadsheet_id}/values/{encoded_range}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        resp.raise_for_status()

    data = resp.json()
    raw_values = data.get("values", [])
    result: set[str] = set()
    for row in raw_values:
        for cell in row:
            s = str(cell).strip()
            if s:
                result.add(s)
    return result


async def get_all_rows(
    spreadsheet_id: str,
    sheet_tab_name: str,
    range_param: str = "A:K",
) -> list[list[Any]]:
    """지정 범위의 전체 데이터를 2차원 리스트로 반환."""
    access_token = await asyncio.to_thread(_get_access_token_from_keyfile)

    if " " in sheet_tab_name or "'" in sheet_tab_name:
        range_str = f"'{sheet_tab_name}'!{range_param}"
    else:
        range_str = f"{sheet_tab_name}!{range_param}"

    encoded_range = quote(range_str, safe="")
    url = f"{GOOGLE_SHEETS_BASE}/spreadsheets/{spreadsheet_id}/values/{encoded_range}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise ValueError(_friendly_sheets_read_error(resp, sheet_tab_name))

    data = resp.json()
    return data.get("values", [])


async def get_spreadsheet_sheet_titles(spreadsheet_id: str) -> list[str]:
    """스프레드시트에 정의된 시트 탭 제목을 UI 순서대로 반환."""
    access_token = await asyncio.to_thread(_get_access_token_from_keyfile)
    url = f"{GOOGLE_SHEETS_BASE}/spreadsheets/{spreadsheet_id}"
    params = {"fields": "sheets.properties.title"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise ValueError(_friendly_sheets_read_error(resp, spreadsheet_id[:12]))
    data = resp.json()
    sheets = data.get("sheets") or []
    out: list[str] = []
    for s in sheets:
        if not isinstance(s, dict):
            continue
        prop = s.get("properties") or {}
        t = (prop.get("title") or "").strip()
        if t:
            out.append(t)
    return out


async def batch_update_cells(spreadsheet_id: str, data: list[dict]) -> None:
    """values:batchUpdate로 여러 셀을 일괄 수정. data는 [{"range": "탭!I5", "values": [["게시중"]]}, ...] 형태."""
    access_token = await asyncio.to_thread(_get_access_token_from_keyfile)
    url = f"{GOOGLE_SHEETS_BASE}/spreadsheets/{spreadsheet_id}/values:batchUpdate"
    body = {"valueInputOption": "USER_ENTERED", "data": data}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()


async def notify_product_delivery_webapp(url: str, payload: dict) -> None:
    """구글 Apps Script 등 상품 전달용 웹훅 URL로 JSON POST. 실패해도 예외를 올리지 않고 로그만 남긴다."""
    target = (url or "").strip()
    if not target:
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60.0,
                follow_redirects=True,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "product_delivery_webapp_http_error status=%s body=%s",
                    resp.status_code,
                    (resp.text or "")[:800],
                )
    except Exception:
        logger.exception("product_delivery_webapp_request_failed url=%s", target[:120])
