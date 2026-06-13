"""브리지 P1: 쿠팡 베스트/골드박스 수집 함수 단위 테스트(네트워크 모킹)."""
from __future__ import annotations

import unittest
from unittest import mock

from app.admin.ops.services import coupang


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._p = payload

    def json(self) -> dict:
        return self._p


class _FakeClient:
    last_url: str = ""
    last_headers: dict | None = None

    def __init__(self, payload: dict) -> None:
        self._p = payload

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a) -> bool:
        return False

    async def get(self, url, headers=None, timeout=None):
        _FakeClient.last_url = url
        _FakeClient.last_headers = headers
        return _FakeResp(self._p)


def _patch_client(payload: dict):
    return mock.patch.object(coupang.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))


class TestCoupangBest(unittest.IsolatedAsyncioTestCase):
    async def test_goldbox_filters_and_normalizes(self) -> None:
        payload = {
            "rCode": "0",
            "rMessage": "",
            "data": [
                {"productId": 1, "productName": "통과상품", "productPrice": 1000,
                 "productUrl": "https://link.coupang.com/u1", "productImage": "i1",
                 "rating": 4.8, "reviewCount": 120},
                {"productId": 2, "productName": "평점미달", "productPrice": 2000,
                 "productUrl": "u2", "productImage": "i2", "rating": 4.0, "reviewCount": 120},
                {"productId": 3, "productName": "리뷰미달", "productPrice": 3000,
                 "productUrl": "u3", "productImage": "i3", "rating": 4.9, "reviewCount": 10},
            ],
        }
        with _patch_client(payload):
            res = await coupang.fetch_goldbox("ak", "sk", limit=10)
        self.assertEqual(res.raw_collected, 3)
        self.assertEqual(res.filtered_count, 1)  # 리뷰>=50 & 평점>=4.5 통과는 1개
        self.assertEqual(len(res.products), 1)
        self.assertEqual(res.products[0]["productName"], "통과상품")
        self.assertEqual(res.stop_reason, "ok")
        self.assertIn("/products/goldbox", _FakeClient.last_url)
        self.assertIn("Authorization", _FakeClient.last_headers or {})

    async def test_bestcategories_path_and_limit(self) -> None:
        payload = {"rCode": "0", "data": []}
        with _patch_client(payload):
            res = await coupang.fetch_best_categories("1010", "ak", "sk", limit=5)
        self.assertIn("/products/bestcategories/1010", _FakeClient.last_url)
        self.assertIn("limit=5", _FakeClient.last_url)
        self.assertEqual(res.filtered_count, 0)

    async def test_business_error_returns_empty(self) -> None:
        with _patch_client({"rCode": "ERROR", "rMessage": "bad"}):
            res = await coupang.fetch_goldbox("ak", "sk")
        self.assertEqual(res.products, [])
        self.assertEqual(res.stop_reason, "business_error")

    async def test_missing_key_short_circuits(self) -> None:
        res = await coupang.fetch_best_categories("1010", "", "")
        self.assertEqual(res.stop_reason, "missing_key")
        self.assertEqual(res.products, [])


if __name__ == "__main__":
    unittest.main()
