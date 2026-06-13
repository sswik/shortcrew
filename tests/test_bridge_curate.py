"""브리지 큐레이션 오케스트레이션 엔드포인트 테스트(쿠팡·Gemini·DB 모킹)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.deps import get_db
from app.admin.ops.routes import bridge
from app.admin.ops.services.coupang import SearchProductsResult


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(bridge.router, prefix="/admin/api/ops/bridge")
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    return app


class _FakeDB:
    added: list = []

    def scalar(self, *a, **k):
        return None  # 중복 없음

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


def _search_ret(*a, **k):
    return SearchProductsResult(
        products=POOL, raw_collected=2, filtered_count=2, stop_reason="ok", queries_run=1,
    )


async def _fake_search(keyword, ak, sk, limit=10):
    return _search_ret()


async def _fake_pick(api_key, *, topic, candidates, persona="", temperature=0.3):
    # '홈캠' 주제면 0번, 그 외는 무관
    if "홈캠" in topic or "현관" in topic:
        return {"relevant": True, "picked": candidates[0], "selection_reason": "혼자 사는 집 필수 홈캠"}
    return {"relevant": False, "picked": None, "selection_reason": "연관 상품 없음"}


async def _fake_deeplinks(urls, ak, sk):
    return {u: u + "?lptag=deep" for u in urls}


class TestBridgeCurate(unittest.TestCase):
    def setUp(self) -> None:
        _FakeDB.added = []
        self._env = mock.patch.dict(os.environ, {
            "OPS_API_TOKEN": "tok",
            "COUPANG_ACCESS_KEY": "ak",
            "COUPANG_SECRET_KEY": "sk",
            "GOOGLE_GEMINI_KEY": "gk",
        })
        self._env.start()
        self.client = TestClient(_make_app())

    def tearDown(self) -> None:
        self._env.stop()

    def _post(self, body, token="tok"):
        h = {"X-Ops-Token": token} if token else {}
        return self.client.post("/admin/api/ops/bridge/curate", json=body, headers=h)

    def test_token_required(self) -> None:
        r = self._post({"channel_id": "105"}, token="")
        self.assertEqual(r.status_code, 401)

    def test_unknown_channel(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search):
            r = self._post({"channel_id": "999"})
        self.assertEqual(r.status_code, 404)

    def test_pool_preview_without_topics(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search):
            r = self._post({"channel_id": "105"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["mode"], "pool_preview")
        self.assertEqual(d["pool_size"], 2)

    def test_curate_dry_run_no_persist(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks):
            r = self._post({
                "channel_id": "105",
                "topics": ["현관 뚫리는 홈캠 사각지대", "우주의 기원"],
                "dry_run": True,
            })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["persisted"], 0)
        self.assertEqual(len(_FakeDB.added), 0)
        # 첫 주제는 선정, 둘째는 무관
        picks = {p["topic"]: p for p in d["picks"]}
        self.assertEqual(picks["현관 뚫리는 홈캠 사각지대"]["picked"], "샤오미 홈캠 2K")
        self.assertIn("lptag=deep", picks["현관 뚫리는 홈캠 사각지대"]["deeplink"])
        self.assertIsNone(picks["우주의 기원"]["picked"])

    def test_curate_persist_creates_product(self) -> None:
        with mock.patch.object(bridge.coupang, "search_products", _fake_search), \
                mock.patch.object(bridge.gemini_curator, "pick_product_for_topic", _fake_pick), \
                mock.patch.object(bridge.coupang, "generate_deeplinks", _fake_deeplinks):
            r = self._post({
                "channel_id": "105",
                "topics": ["현관 홈캠 사각지대"],
                "dry_run": False,
            })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["persisted"], 1)
        self.assertEqual(len(_FakeDB.added), 1)
        prod = _FakeDB.added[0]
        self.assertEqual(prod.influencer_slug, "safety")
        self.assertEqual(prod.title, "샤오미 홈캠 2K")
        self.assertIn("lptag=deep", prod.coupang_url)


if __name__ == "__main__":
    unittest.main()
