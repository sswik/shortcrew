"""쇼츠 시트 매칭·정규화 단위 테스트."""

from __future__ import annotations

import unittest
from datetime import date

from app.admin.ops.services.shorts_name_normalize import names_equivalent, normalize_match_key_strict
from app.admin.ops.services.shorts_review_config import ShortsReviewConfig
from app.admin.ops.services.shorts_sheet_matcher import (
    match_shorts_sheet_rows,
    parse_sheet_date_cell,
    youtube_video_id_from_url,
)


def _cfg() -> ShortsReviewConfig:
    return ShortsReviewConfig(
        channel_id="104",
        spreadsheet_id="dummy",
        mall_influencer_slug="shop",
        plan_tab="기획",
        product_tab="상품목록",
        plan_range="A:W",
        product_range="A:K",
        plan_status_col=2,
        plan_date_col=3,
        plan_date_tz="Asia/Seoul",
        plan_youtube_col=22,
        plan_product_col=5,
        plan_status_value="완료",
        product_status_col=8,
        product_name_col=2,
        product_deeplink_col=6,
        product_status_value="게시중",
    )


def _pad(row: list[str], length: int) -> list[str]:
    return row + [""] * (length - len(row))


class TestYoutubeVideoId(unittest.TestCase):
    def test_watch(self) -> None:
        self.assertEqual(
            youtube_video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_shorts(self) -> None:
        self.assertEqual(
            youtube_video_id_from_url("https://www.youtube.com/shorts/abc123xyz"),
            "abc123xyz",
        )

    def test_youtu_be(self) -> None:
        self.assertEqual(youtube_video_id_from_url("https://youtu.be/ZZ11"), "ZZ11")


class TestNormalize(unittest.TestCase):
    def test_equivalent_spacing(self) -> None:
        self.assertTrue(names_equivalent("  허니  꿀  ", "허니꿀"))

    def test_strict_key(self) -> None:
        self.assertEqual(normalize_match_key_strict("  Foo-Bar  "), "foobar")


class TestMatchShortsSheetRows(unittest.TestCase):
    def test_join_one_row(self) -> None:
        cfg = _cfg()
        header = _pad(["h"] * 23, 23)
        plan = _pad(
            [
                "h",
                "",
                "완료",
                "2030-01-15",
                "",
                "상품A",
            ],
            23,
        )
        plan[22] = "https://youtu.be/vidone01"
        product_header = _pad(["h"] * 11, 11)
        prod = _pad(
            [
                "h",
                "",
                "상품 A",
                "",
                "",
                "",
                "https://deeplink.example/p/1",
                "",
                "게시중",
            ],
            11,
        )
        matches = match_shorts_sheet_rows(
            cfg, [header, plan], [product_header, prod], date(2030, 1, 15)
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].video_id, "vidone01")
        self.assertIn("deeplink.example", matches[0].deep_link)

    def test_skip_without_product_match(self) -> None:
        cfg = _cfg()
        header = _pad(["h"] * 23, 23)
        plan = _pad(["h", "", "완료", "2030-02-01", "", "없는상품"], 23)
        plan[22] = "https://youtu.be/xx"
        ph = _pad(["h"] * 11, 11)
        pr = _pad(["h", "", "다른상품", "", "", "", "https://d", "", "게시중"], 11)
        matches = match_shorts_sheet_rows(cfg, [header, plan], [ph, pr], date(2030, 2, 1))
        self.assertEqual(len(matches), 0)

    def test_skip_when_plan_date_not_reference(self) -> None:
        cfg = _cfg()
        header = _pad(["h"] * 23, 23)
        plan = _pad(["h", "", "완료", "2030-01-01", "", "상품A"], 23)
        plan[22] = "https://youtu.be/vidone01"
        ph = _pad(["h"] * 11, 11)
        pr = _pad(
            [
                "h",
                "",
                "상품 A",
                "",
                "",
                "",
                "https://deeplink.example/p/1",
                "",
                "게시중",
            ],
            11,
        )
        matches = match_shorts_sheet_rows(
            cfg, [header, plan], [ph, pr], date(2030, 1, 15)
        )
        self.assertEqual(len(matches), 0)


class TestParseSheetDateCell(unittest.TestCase):
    def test_iso_string(self) -> None:
        self.assertEqual(parse_sheet_date_cell("2030-04-19"), date(2030, 4, 19))

    def test_serial(self) -> None:
        d = parse_sheet_date_cell(47498.0)
        self.assertIsNotNone(d)
        self.assertEqual(d, date(2030, 1, 15))
