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

    def test_default_channel_id_is_201(self) -> None:
        from app.admin.ops.channels import get_channels

        ch = get_channels()
        self.assertTrue(ch)
        self.assertEqual(ch[0]["channel_id"], "201")

    def test_missing_google_sheet_response_lists_env_key(self) -> None:
        from app.admin.ops.routes.sheets import _missing_google_sheet_response

        r = _missing_google_sheet_response("201")
        self.assertEqual(r.status_code, 400)
        data = json.loads(bytes(r.body).decode())
        err = data.get("error") or ""
        self.assertIn("CHANNEL_201_FILE_ID", err)
        self.assertIn("201", err)


if __name__ == "__main__":
    unittest.main()
