"""브리지 큐레이션 오케스트레이션 테스트(쿠팡·Gemini·시트·DB 모킹).

상품은 시트(append_rows)로, 블로그는 DB Review(sheet_product_* 연결)로 적재한다.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.deps import get_db
from app.admin.ops.routes import bridge
from app.admin.ops.services import google_sheets
from app.admin.ops.services.coupang import SearchProductsResult


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(bridge.router, prefix="/admin/api/ops/bridge")
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    return app


class _FakeDB:
    added: list = []

    def scalar(self, *a, **k):
        return None  # 인플루언서 없음 → 표시명 slug 폴백

    def add(self, obj):
        _FakeDB.added.append(obj)

    def commit(self):
        pass


POOL = [
    {"productId": "1", "productName": "샤오미 홈캠 2K", "price": 39900,
     "productUrl": "https://link.coupang.com/a/cam", "imageUrl": "i1", "category": "가전"},
    {"productId": "2", "productName": "스마트 도어락 지문", "price": 159000,
     "productUrl": "https://link.coupang.com/a/lock", "imageUrl": "i2", "category": "생활"},
]

_APPENDED: list = []


def _fake_search_ret():
    return SearchProductsResult(
        products=POOL, raw_collected=2, filtered_count=2, stop_reason="ok", queries_run=1,
    )


async def _fake_search(keyword, ak, sk, limit=10):
    return _fake_search_ret()


async def _fake_pick(api_key, *, topic, candidates, persona="", temperature=0.3):
    if "홈캠" in topic or "현관" in topic:
        return {"relevant": True, "picked": candidates[0], "selection_reason": "혼자 사는 집 필수 홈캠"}
    return {"relevant": False, "picked": None, "selection_reason": "연관 상품 없음"}


async def _fake_deeplinks(urls, ak, sk):
    return {u: u + "?lptag=deep" for u in urls}


async def _fake_existing(sheet_id, tab, column="F"):
    return set()


async def _fake_append(sheet_id, tab, rows):
    _APPENDED.append((sheet_id, tab, rows))


async def _fake_review_draft(api_key, **kwargs):
    return {"title": f"[리뷰] {kwargs.get('product_title')}", "html": "<p>안전 강추</p>"}


class TestBridgeCurate(unittest.TestCase):
    def setUp(self) -> None:
        _FakeDB.added = []
        _APPENDED.clear()
        self._env = mock.patch.dict(os.environ, {
            "OPS_API_TOKEN": "tok",
            "COUPANG_ACCESS_KEY": "ak",
            "COUPANG_SECRET_KEY": "sk",
            "GOOGLE_GEMINI_KEY": "gk",
            "CHANNEL_105_FILE_ID": "SHEET_X",
            "CHANNEL_105_TAB": "안지아픽-상품",
        })
        self._env.start()
        self.client = TestClient(_make_app())

    def tearDown(self) -> None:
        self._env.stop()

    def _post(self, body, token="tok"):
        h = {"X-Ops-Token": token} if token else {}
        return self.client.post("/admin/api/ops/bridge/curate", json=body, headers=h)

    def test_token_required(self) -> None:
        self.assertEqual(self._post({"channel_id": "105"}, token="").status_code, 401)

    def test_unknown_channel(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search):
            self.assertEqual(self._post({"channel_id": "999"}).status_code, 404)

    def test_no_topics_uses_trend_keywords(self) -> None:
        # 주제 미지정이면 채널 trend_keywords 를 주제로 사용(확장 기본)
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks):
            r = self._post({"channel_id": "105", "dry_run": True})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["mode"], "curate")
        # 105 trend_keywords 중 '홈캠' 주제가 상품 선정됨
        picked = [p for p in d["picks"] if p["picked"]]
        self.assertTrue(len(picked) >= 1)

    def test_dry_run_no_sheet_write(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks):
            r = self._post({"channel_id": "105", "topics": ["현관 홈캠", "우주의 기원"], "dry_run": True})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["written_to_sheet"], 0)
        self.assertEqual(len(_APPENDED), 0)
        picks = {p["topic"]: p for p in d["picks"]}
        self.assertIn("lptag=deep", picks["현관 홈캠"]["deeplink"])
        self.assertIsNone(picks["우주의 기원"]["picked"])

    def test_writes_products_to_sheet(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks), \
                mock.patch.object(google_sheets, "get_existing_values", _fake_existing), \
                mock.patch.object(google_sheets, "append_rows", _fake_append):
            r = self._post({"channel_id": "105", "topics": ["현관 홈캠 사각지대"], "dry_run": False})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["written_to_sheet"], 1)
        self.assertEqual(len(_APPENDED), 1)
        sheet_id, tab, rows = _APPENDED[0]
        self.assertEqual(sheet_id, "SHEET_X")
        self.assertEqual(tab, "안지아픽-상품")
        self.assertEqual(len(rows), 1)
        # build_rows: C열=상품명, F열=쿠팡URL, G열=딥링크
        self.assertEqual(rows[0][2], "샤오미 홈캠 2K")
        self.assertIn("lptag=deep", rows[0][6])

    def test_sheet_missing_returns_503(self) -> None:
        with mock.patch.dict(os.environ, {"CHANNEL_105_FILE_ID": ""}), \
                mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks):
            r = self._post({"channel_id": "105", "topics": ["현관 홈캠"], "dry_run": False})
        self.assertEqual(r.status_code, 503)

    def test_auto_blog_creates_review_with_sheet_fields(self) -> None:
        from models import Review
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks), \
                mock.patch.object(google_sheets, "get_existing_values", _fake_existing), \
                mock.patch.object(google_sheets, "append_rows", _fake_append), \
                mock.patch.object(bridge, "generate_review_draft", _fake_review_draft):
            r = self._post({
                "channel_id": "105", "topics": ["현관 홈캠 사각지대"],
                "dry_run": False, "auto_blog": True,
            })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["written_to_sheet"], 1)
        self.assertEqual(d["blogs_created"], 1)
        revs = [o for o in _FakeDB.added if isinstance(o, Review)]
        self.assertEqual(len(revs), 1)
        self.assertIsNone(revs[0].product_id)
        self.assertEqual(revs[0].sheet_product_title, "샤오미 홈캠 2K")
        self.assertIn("lptag=deep", revs[0].sheet_product_deeplink)
        self.assertEqual(revs[0].influencer_slug, "safety")

    def test_auto_dm_creates_rule(self) -> None:
        from models import DmAutomation
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks), \
                mock.patch.object(google_sheets, "get_existing_values", _fake_existing), \
                mock.patch.object(google_sheets, "append_rows", _fake_append):
            r = self._post({
                "channel_id": "105", "topics": ["현관 홈캠 사각지대"],
                "dry_run": False, "auto_dm": True,  # dm_gemini 미지정 → 템플릿
            })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["dm_rules_created"], 1)
        dms = [o for o in _FakeDB.added if isinstance(o, DmAutomation)]
        self.assertEqual(len(dms), 1)
        self.assertEqual(dms[0].channel_id, "105")
        self.assertEqual(dms[0].target_mode, "next")
        self.assertIn("lptag=deep", dms[0].dm_link)
        self.assertIn("샤오미 홈캠 2K", dms[0].dm_message)


if __name__ == "__main__":
    unittest.main()
