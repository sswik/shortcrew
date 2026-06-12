"""접속 상세 로그 미들웨어: 요청당 한 줄(JSON)을 일별 텍스트 파일에 기록."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import KST
from app.core.helpers import _client_ip_from_request

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_ACCESS_LOG_DIR = _ROOT / "logs"
_access_log_lock = Lock()


def _append_access_detail_log(
    *,
    request: Request,
    status_code: int,
    duration_ms: float,
) -> None:
    """접속자·요청 상세를 일별 텍스트 파일에 한 줄(JSON)로 남긴다."""
    now = datetime.now(KST)
    rec: dict[str, object] = {
        "ts": now.isoformat(timespec="milliseconds"),
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query": request.url.query or "",
        "client_ip": _client_ip_from_request(request),
        "forwarded_for": (request.headers.get("x-forwarded-for") or "").strip() or None,
        "user_agent": (request.headers.get("user-agent") or "").strip() or None,
        "referer": (request.headers.get("referer") or "").strip() or None,
        "accept_language": (request.headers.get("accept-language") or "").strip() or None,
        "host": (request.headers.get("host") or "").strip() or None,
        "scheme": request.url.scheme,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
    }
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    day = now.strftime("%Y-%m-%d")
    path = _ACCESS_LOG_DIR / f"access-{day}.txt"
    try:
        _ACCESS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _access_log_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as e:
        logger.warning("access_detail_log_write_failed path=%s err=%s", path, e)


class AccessDetailLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0
        _append_access_detail_log(
            request=request,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
