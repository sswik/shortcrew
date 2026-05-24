"""리뷰 HTML 분리 유닛 테스트."""

from __future__ import annotations

import unittest

from app.client.review_html import split_shorts_review_cta


class TestSplitShortsReviewCta(unittest.TestCase):
    def test_extract_and_strip(self) -> None:
        tail = (
            '<p class="shorts-review-cta">'
            '<a href="https://link.coupang.com/a/xx" target="_blank" rel="noopener noreferrer">'
            "쿠팡에서 구매하기</a></p>"
        )
        body, url = split_shorts_review_cta("<p>본문</p>\n" + tail)
        self.assertEqual(url, "https://link.coupang.com/a/xx")
        self.assertEqual(body.strip(), "<p>본문</p>")

    def test_none_when_missing(self) -> None:
        body, url = split_shorts_review_cta("<p>만</p>")
        self.assertIsNone(url)
        self.assertEqual(body, "<p>만</p>")


if __name__ == "__main__":
    unittest.main()
