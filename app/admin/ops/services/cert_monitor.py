"""Cloud Run 관리형 인증서 만료 감시.

왜 필요한가
----------
`shortcrew.co.kr` 은 Cloud Run 도메인 매핑의 **Google 관리형 인증서**를 쓴다. 이 인증서는
약 90일마다 자동 갱신되는데, 갱신에는 ACME HTTP-01 챌린지(평문 80포트)가 도메인까지
도달해야 한다. Cloudflare 프록시(주황 구름)를 켜고 `Always Use HTTPS` 나 리다이렉트 규칙이
80포트를 엣지에서 가로채면 챌린지가 구글에 닿지 못해 **갱신이 조용히 실패**한다.

사이트는 기존 인증서가 살아 있는 동안 멀쩡히 돌다가, 만료되는 순간 전체가 죽는다.
그래서 매일 만료일을 확인해 임계일 미만이면 디스코드로 알린다.

왜 도메인이 아니라 IP 로 직접 붙는가
--------------------------------
프록시가 켜져 있으면 `https://shortcrew.co.kr` 에 붙었을 때 보이는 것은 **Cloudflare 의
인증서**다. 감시 대상인 구글 인증서를 보려면 Cloud Run 프론트엔드 IP 에 직접 TCP 연결하고
SNI 로 도메인을 넘겨야 한다.

env
---
- CERT_MONITOR_DOMAIN     : 감시 도메인(기본 shortcrew.co.kr)
- CERT_MONITOR_IP         : 접속할 Cloud Run 프론트엔드 IP(기본 216.239.32.21)
- CERT_MONITOR_WARN_DAYS  : 이 일수 미만이면 경고(기본 30)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import ssl
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_DOMAIN = "shortcrew.co.kr"
# Cloud Run 도메인 매핑이 안내하는 A 레코드 중 하나. 애니캐스트라 어느 것이든 같은 인증서.
_DEFAULT_IP = "216.239.32.21"


def _domain() -> str:
    return (os.environ.get("CERT_MONITOR_DOMAIN") or _DEFAULT_DOMAIN).strip()


def _ip() -> str:
    return (os.environ.get("CERT_MONITOR_IP") or _DEFAULT_IP).strip()


def _warn_days() -> int:
    try:
        return int((os.environ.get("CERT_MONITOR_WARN_DAYS") or "30").strip())
    except ValueError:
        return 30


def _peer_cert(host: str, ip: str, timeout: float = 15.0) -> dict:
    """IP 에 직접 붙어 SNI=host 로 받은 인증서 정보."""
    ctx = ssl.create_default_context()
    with socket.create_connection((ip, 443), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert() or {}


def _parse_not_after(cert: dict) -> datetime | None:
    raw = str(cert.get("notAfter") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def check_cert(*, notify: bool = True) -> dict:
    """인증서 만료일 확인. 임계일 미만이면 디스코드 경고."""
    host, ip, warn = _domain(), _ip(), _warn_days()
    out: dict = {"domain": host, "ip": ip, "warn_days": warn}
    try:
        cert = await asyncio.to_thread(_peer_cert, host, ip)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:200]
        if notify:
            await _notify(f"🔴 인증서 확인 실패 [{host}]: {out['error']}")
        return out

    not_after = _parse_not_after(cert)
    if not_after is None:
        out["error"] = f"notAfter 파싱 실패: {cert.get('notAfter')!r}"
        if notify:
            await _notify(f"🔴 인증서 만료일 파싱 실패 [{host}]")
        return out

    left = int((not_after - datetime.now(timezone.utc)).total_seconds() // 86400)
    issuer = dict(x[0] for x in cert.get("issuer") or ()) if cert.get("issuer") else {}
    out.update(
        not_after=not_after.isoformat(),
        days_left=left,
        issuer=issuer.get("organizationName") or issuer.get("commonName") or "",
        ok=left >= warn,
    )
    if left < warn and notify:
        await _notify(
            f"🟠 인증서 만료 임박 [{host}] {left}일 남음 (만료 {not_after:%Y-%m-%d})\n"
            f"Cloud Run 관리형 인증서 갱신이 막혔을 수 있습니다. "
            f"Cloudflare 프록시가 ACME HTTP-01 챌린지를 가로채는지 확인하세요."
        )
    return out


async def _notify(msg: str) -> None:
    try:
        from app.admin.ops.services import discord_notify

        await discord_notify.notify(msg, env_key="DISCORD_WEBHOOK_FAIL")
    except Exception as e:
        logger.warning("cert_monitor: 디스코드 알림 실패 (%s)", str(e)[:80])
