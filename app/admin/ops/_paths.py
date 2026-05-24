"""`app/admin/ops` 패키지 기준 숏크루(shortcrew) 프로젝트 루트."""
from __future__ import annotations

from pathlib import Path

_OPS_DIR = Path(__file__).resolve().parent


def project_root() -> Path:
    """`app/admin/ops` → `shortcrew/` 루트 (상위 3단: admin → app → 루트)."""
    return _OPS_DIR.parent.parent.parent
