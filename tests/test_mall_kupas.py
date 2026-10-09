"""쿠파스 몰(시트 A열 번호 그대로) 단위 테스트.

- build_items: 쿠파스 구역 분리·번호 정렬·공개시각 필터, 기존 상품은 Apps Script 응답과 동일 형태.
- /mall/upsert: 토큰 인증, 신규 추가(append)·기존 수정(batchUpdate), 대상 외 채널 거부(시트 호출 모킹).
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.client import mall_kupas as mk


def _row(no, name, *, q="", status="게시중", pub="", rating="", rc="", feats="", price="10,500", cat="cat"):
    return [str(no), cat, name, price, f"https://img/{no}", "", f"https://link.coupang.com/a/{no}",
            "", status, "2026-10-01", "", rating, rc, feats, "", pub, q]


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


class TestBuildItems(unittest.TestCase):
    def test_legacy_rows_match_apps_script_shape_and_keep_order(self) -> None:
        rows = [_row(1, "A", status="대기"), _row(2, "B"), ["3", "", ""], _row(4, "D", price="")]
        items = mk.build_items(rows, NOW)
        self.assertEqual([i["name"] for i in items], ["A", "B", "D"])  # 상태 무관·이름 없는 행 제외
        self.assertEqual(set(items[0]), {"name", "price", "image", "deepLink", "category"})
        self.assertEqual(items[0]["price"], 10500)
        self.assertEqual(items[2]["price"], "")

    def test_kupas_section_first_sorted_desc_and_filtered(self) -> None:
        rows = [
            _row(1, "old"),
            _row(3, "k3", q="쿠파스", pub="2026-10-09T10:30:00Z", rating="4.7", rc="2,949", feats="a · b · c"),
            _row(9, "k9", q="쿠파스", pub="2026-10-09T11:00:00Z"),
            _row(13, "future", q="쿠파스", pub="2026-10-10T10:30:00Z"),
            _row(5, "bad-date", q="쿠파스", pub="내일"),
            _row(6, "hidden", q="쿠파스", status="대기"),
            _row(1, "k1", q="쿠파스"),
        ]
        items = mk.build_items(rows, NOW)
        kupas = [i for i in items if i.get("section") == "kupas"]
        self.assertEqual([i["no"] for i in kupas], [9, 3, 1])
        self.assertEqual(items[-1]["name"], "old")  # 기존 구역은 뒤
        k3 = next(i for i in kupas if i["no"] == 3)
        self.assertEqual(k3["rating"], 4.7)
        self.assertEqual(k3["reviewCount"], 2949)
        self.assertEqual(k3["features"], ["a", "b", "c"])

    def test_duplicate_no_last_row_wins(self) -> None:
        rows = [_row(2, "first", q="쿠파스"), _row(2, "second", q="쿠파스")]
        items = mk.build_items(rows, NOW)
        self.assertEqual([i["name"] for i in items], ["second"])

    def test_channel_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MALL_KUPAS_CHANNELS", None)
            self.assertEqual(mk.kupas_channels(), {"02", "03", "15", "31", "35"})
        with mock.patch.dict(os.environ, {"MALL_KUPAS_CHANNELS": ""}):
            self.assertEqual(mk.kupas_channels(), set())
        with mock.patch.dict(os.environ, {"MALL_KUPAS_CHANNELS": "15 35"}):
            self.assertTrue(mk.is_kupas_channel("35"))
            self.assertFalse(mk.is_kupas_channel("02"))


class TestUpsert(unittest.TestCase):
    def setUp(self) -> None:
        from app.admin.ops.routes import mall

        app = FastAPI()
        app.include_router(mall.router, prefix="/admin/api/ops/mall")
        self.client = TestClient(app)
        self.env = mock.patch.dict(os.environ, {
            "OPS_API_TOKEN": "t", "MALL_KUPAS_CHANNELS": "35",
            "CHANNEL_35_FILE_ID": "SHEET", "CHANNEL_35_TAB": "호러펌프-상품",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        header = ["No", "상품카테고리", "상품명", "가격", "이미지URL", "쿠팡URL", "딥링크", "연관영상No",
                  "게시상태", "등록일", "subId"]
        self.sheet = [header, _row(1, "legacy-1"), _row(1, "kupas-1", q="쿠파스", rating="4.5")]
        self.updates: list = []
        self.appended: list = []

        async def get_all_rows(sid, tab, rng):
            return [list(r) for r in self.sheet]

        async def batch_update_cells(sid, data):
            self.updates.extend(data)

        async def append_rows(sid, tab, rows, column_range="A:K"):
            self.appended.extend(rows)
            self.sheet.extend(rows)

        for name, fn in (("get_all_rows", get_all_rows), ("batch_update_cells", batch_update_cells),
                         ("append_rows", append_rows)):
            p = mock.patch(f"app.admin.ops.services.google_sheets.{name}", fn)
            p.start()
            self.addCleanup(p.stop)

    def post(self, body, token="t"):
        return self.client.post("/admin/api/ops/mall/upsert", json=body, headers={"X-Ops-Token": token})

    def test_requires_token(self) -> None:
        self.assertEqual(self.post({"channel_id": "35", "no": 2, "name": "x"}, token="bad").status_code, 401)

    def test_rejects_non_kupas_channel(self) -> None:
        self.assertEqual(self.post({"channel_id": "02", "no": 2, "name": "x"}).status_code, 400)

    def test_rejects_bad_publish_at(self) -> None:
        r = self.post({"channel_id": "35", "no": 2, "name": "x", "publish_at": "tomorrow"})
        self.assertEqual(r.status_code, 400)

    def test_update_existing_kupas_row_only(self) -> None:
        r = self.post({"channel_id": "35", "no": 1, "review_count": 120, "features": ["a", "b"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["action"], "updated")
        self.assertEqual(r.json()["sheet_row"], 3)  # 기존 상품 1번(2행)이 아니라 쿠파스 1번(3행)
        header_upd, row_upd = self.updates
        self.assertEqual(header_upd["range"], "'호러펌프-상품'!L1:Q1")
        self.assertEqual(row_upd["range"], "'호러펌프-상품'!A3:Q3")
        row = row_upd["values"][0]
        self.assertEqual(row[2], "kupas-1")   # 미지정 필드 유지
        self.assertEqual(row[11], "4.5")
        self.assertEqual(row[12], "120")
        self.assertEqual(row[13], "a · b")
        self.assertEqual(row[16], "쿠파스")
        self.assertEqual(self.appended, [])

    def test_insert_new_row(self) -> None:
        r = self.post({
            "channel_id": "35", "no": 9, "name": "new", "image": "https://i", "deep_link": "https://link.coupang.com/a/x",
            "rating": 4.8, "review_count": 454, "stats_at": "2026-10-08", "publish_at": "2026-10-10T10:30:00Z",
            "video": "abc",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["action"], "inserted")
        self.assertEqual(r.json()["sheet_row"], 4)
        row = self.appended[0]
        self.assertEqual(row[0], "9")
        self.assertEqual(row[8], "게시중")
        self.assertEqual(row[14], "'2026-10-08")          # 날짜 자동변환 방지
        self.assertEqual(row[15], "'2026-10-10T10:30:00Z")
        self.assertEqual(row[16], "쿠파스")

    def test_insert_requires_name(self) -> None:
        self.assertEqual(self.post({"channel_id": "35", "no": 7}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
