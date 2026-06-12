"""플랜 7단계: 앱 import·핵심 라우트 스모크."""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.admin.auth import admin_auth_enabled


class TestSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import main

        cls._main = main
        cls.client = TestClient(main.app)

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

    def test_www_host_redirects_to_apex(self) -> None:
        r = self.client.get(
            "/golf",
            headers={"Host": "www.shortcrew.co.kr"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers.get("location"), "https://shortcrew.co.kr/golf")

        r2 = self.client.get(
            "/",
            headers={"Host": "www.shortcrew.co.kr"},
            follow_redirects=False,
        )
        self.assertEqual(r2.status_code, 301)
        self.assertEqual(r2.headers.get("location"), "https://shortcrew.co.kr/")

        r3 = self.client.get(
            "/about?x=1",
            headers={"Host": "www.shortcrew.co.kr"},
            follow_redirects=False,
        )
        self.assertEqual(r3.status_code, 301)
        self.assertEqual(r3.headers.get("location"), "https://shortcrew.co.kr/about?x=1")

        r4 = self.client.get("/health", headers={"Host": "shortcrew.co.kr"})
        self.assertEqual(r4.status_code, 200)

    def test_about_page(self) -> None:
        r = self.client.get("/about")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        body = r.text
        self.assertIn("Shortcrew", body)
        self.assertIn("숏크루", body)
        self.assertIn("that's 숏크루", body)

    def test_openapi_includes_ops_channels(self) -> None:
        schema = self._main.app.openapi()
        paths = schema.get("paths") or {}
        self.assertIn("/admin/api/ops/channels", paths)
        self.assertIn("/admin/api/ops/ai/review-draft", paths)
        self.assertIn("/admin/api/ops/sheets/mall-import", paths)
        self.assertIn("/admin/api/ops/sheets/deeplink-preview", paths)
        self.assertIn("/admin/api/ops/shorts-review/run", paths)

    def test_admin_login_get(self) -> None:
        r = self.client.get("/admin/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    def test_ops_channels_auth_behavior(self) -> None:
        r = self.client.get("/admin/api/ops/channels", follow_redirects=False)
        if admin_auth_enabled():
            self.assertEqual(r.status_code, 302)
            loc = r.headers.get("location") or ""
            self.assertIn("/admin/login", loc)
        else:
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIn("channels", body)

    def test_admin_reviews_new_auth(self) -> None:
        r = self.client.get("/admin/reviews/new", follow_redirects=False)
        if admin_auth_enabled():
            self.assertEqual(r.status_code, 302)
            self.assertIn("/admin/login", r.headers.get("location") or "")
        else:
            self.assertEqual(r.status_code, 200)

    def test_channel_env_keys_match_CHANNEL_id_pattern(self) -> None:
        """`.env.example` 의 CHANNEL_201_* / CHANNEL_202_* 과 `channel_env()` 가 동일 규칙인지 고정."""
        from app.admin.ops.channels.env_names import channel_env

        self.assertEqual(channel_env("201", "FILE_ID"), "CHANNEL_201_FILE_ID")
        self.assertEqual(channel_env("201", "TAB"), "CHANNEL_201_TAB")
        self.assertEqual(channel_env("201", "HISTORY_TAB"), "CHANNEL_201_HISTORY_TAB")
        self.assertEqual(
            channel_env("201", "PRODUCT_DELIVERY_WEBAPP_URL"),
            "CHANNEL_201_PRODUCT_DELIVERY_WEBAPP_URL",
        )
        self.assertEqual(
            channel_env("201", "MALL_PRODUCTS_API_URL"),
            "CHANNEL_201_MALL_PRODUCTS_API_URL",
        )
        self.assertEqual(
            channel_env("201", "MALL_PRODUCTS_CHANNEL_PARAM"),
            "CHANNEL_201_MALL_PRODUCTS_CHANNEL_PARAM",
        )
        self.assertEqual(
            channel_env("201", "COUPANG_SUB_ID_PREFIX"),
            "CHANNEL_201_COUPANG_SUB_ID_PREFIX",
        )
        self.assertEqual(channel_env("202", "FILE_ID"), "CHANNEL_202_FILE_ID")
        self.assertEqual(channel_env("01", "FILE_ID"), "CHANNEL_01_FILE_ID")

    def test_missing_google_sheet_response_lists_env_key(self) -> None:
        from app.admin.ops.routes.sheets import _missing_google_sheet_response

        r = _missing_google_sheet_response("201")
        self.assertEqual(r.status_code, 400)
        data = json.loads(bytes(r.body).decode())
        err = data.get("error") or ""
        self.assertIn("CHANNEL_201_FILE_ID", err)
        self.assertIn("201", err)

    def test_mall_products_requires_channel(self) -> None:
        """`/api/mall-products` 는 channel_id 없으면 400(네트워크 호출 전 차단)."""
        r = self.client.get("/api/mall-products")
        self.assertEqual(r.status_code, 400)
        self.assertIn("channel_id", (r.json().get("detail") or ""))

    def test_routes_snapshot_unchanged(self) -> None:
        """main.py 분해(리팩토링) 시 라우트 집합이 바뀌지 않는지 고정.
        의도적으로 라우트를 추가/변경하면 tests/routes_snapshot.txt 도 함께 갱신한다."""
        import os

        snap = os.path.join(os.path.dirname(__file__), "routes_snapshot.txt")
        with open(snap, encoding="utf-8") as f:
            expected = {ln.strip() for ln in f if ln.strip()}
        current = set()
        for route in self._main.app.routes:
            path = getattr(route, "path", None)
            if path is None:
                continue
            methods = sorted(getattr(route, "methods", None) or [])
            current.add(f"{path} [{','.join(methods)}]")
        missing = sorted(expected - current)
        added = sorted(current - expected)
        self.assertEqual((missing, added), ([], []), f"\n사라진 라우트: {missing}\n새 라우트: {added}")


if __name__ == "__main__":
    unittest.main()
