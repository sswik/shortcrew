"""브리지 P2: 하이브리드 상품 선택기(pick_product_for_topic) 단위 테스트(Gemini 모킹)."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from app.admin.ops.services import gemini_curator


class _FakeModels:
    last_kwargs: dict = {}

    def __init__(self, text: str) -> None:
        self._t = text

    async def generate_content(self, **kwargs):
        _FakeModels.last_kwargs = kwargs
        return SimpleNamespace(text=self._t)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.aio = SimpleNamespace(models=_FakeModels(text))


def _patch_gemini(payload: dict):
    text = json.dumps(payload, ensure_ascii=False)
    return mock.patch.object(gemini_curator.genai, "Client", lambda api_key=None: _FakeClient(text))


CANDS = [
    {"productName": "샤오미 홈캠 2K 실내용", "price": 39900, "category": "가전디지털"},
    {"productName": "에버콜라겐 타임", "price": 78900, "category": "건강식품"},
    {"productName": "스마트 도어락 지문인식", "price": 159000, "category": "생활"},
]


class TestPickProductForTopic(unittest.IsolatedAsyncioTestCase):
    async def test_picks_relevant_product(self) -> None:
        with _patch_gemini({"relevant": True, "picked_index": 0, "selection_reason": "혼자 사는 사람 필수 홈캠"}):
            res = await gemini_curator.pick_product_for_topic(
                "key", topic="홈 보안/CCTV/도어락", candidates=CANDS, persona="보안덕후 안지아",
            )
        self.assertTrue(res["relevant"])
        self.assertEqual(res["picked"]["productName"], "샤오미 홈캠 2K 실내용")
        self.assertIn("홈캠", res["selection_reason"])

    async def test_no_relevant_falls_back(self) -> None:
        with _patch_gemini({"relevant": False, "picked_index": -1, "selection_reason": "보안과 무관"}):
            res = await gemini_curator.pick_product_for_topic("key", topic="홈 보안", candidates=CANDS)
        self.assertFalse(res["relevant"])
        self.assertIsNone(res["picked"])

    async def test_out_of_range_index_guarded(self) -> None:
        with _patch_gemini({"relevant": True, "picked_index": 99, "selection_reason": "x"}):
            res = await gemini_curator.pick_product_for_topic("key", topic="t", candidates=CANDS)
        self.assertFalse(res["relevant"])
        self.assertIsNone(res["picked"])

    async def test_empty_candidates_no_call(self) -> None:
        res = await gemini_curator.pick_product_for_topic("key", topic="t", candidates=[])
        self.assertFalse(res["relevant"])
        self.assertIsNone(res["picked"])

    async def test_missing_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            await gemini_curator.pick_product_for_topic("", topic="t", candidates=CANDS)


if __name__ == "__main__":
    unittest.main()
