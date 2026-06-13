"""인스타 릴스 발행 엔드포인트 단위 테스트(Graph 호출 모킹).

토큰 인증, dry-run, 컨테이너→폴링→발행 성공 흐름을 검증한다.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.ops.routes import instagram_publish as ig


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ig.router, prefix="/admin/api/ops/instagram")
    return app


class _FakeAsyncClient:
    """create→status(IN_PROGRESS→FINISHED)→publish→permalink 순서를 흉내."""

    posts: list[tuple[str, dict]] = []

    def __init__(self, *a, **k) -> None:
        self._get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None):
        _FakeAsyncClient.posts.append((url, data or {}))
        if url.endswith("/media"):
            return _Resp(200, {"id": "CONTAINER123"})
        if url.endswith("/media_publish"):
            return _Resp(200, {"id": "MEDIA999"})
        return _Resp(400, {"error": "unexpected"})

    async def get(self, url, params=None):
        # 첫 폴링은 IN_PROGRESS, 그다음 FINISHED. permalink 조회는 별도.
        if "fields=permalink" in url or (params or {}).get("fields") == "permalink":
            return _Resp(200, {"permalink": "https://instagram.com/reel/abc"})
        self._get_calls += 1
        code = "FINISHED" if self._get_calls >= 2 else "IN_PROGRESS"
        return _Resp(200, {"status_code": code})


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._p = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._p


class TestPublishReel(unittest.TestCase):
    def setUp(self) -> None:
        _FakeAsyncClient.posts = []
        self._env = mock.patch.dict(os.environ, {
            "OPS_API_TOKEN": "secret-token",
            "CHANNEL_105_IG_ACCOUNT_ID": "17841422626136472",
            "CHANNEL_105_IG_ACCESS_TOKEN": "IGAF-token",
        })
        self._env.start()
        self.client = TestClient(_make_app())

    def tearDown(self) -> None:
        self._env.stop()

    def _body(self, **over):
        b = {"channel_id": "105", "video_url": "https://drive/x.mp4", "caption": "보안팁"}
        b.update(over)
        return b

    def test_missing_token_rejected(self) -> None:
        r = self.client.post("/admin/api/ops/instagram/publish-reel", json=self._body())
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_rejected(self) -> None:
        r = self.client.post(
            "/admin/api/ops/instagram/publish-reel",
            json=self._body(), headers={"X-Ops-Token": "nope"},
        )
        self.assertEqual(r.status_code, 401)

    def test_dry_run_no_network(self) -> None:
        r = self.client.post(
            "/admin/api/ops/instagram/publish-reel",
            json=self._body(dry_run=True), headers={"X-Ops-Token": "secret-token"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["ig_account_id"], "17841422626136472")
        self.assertIn("/media", data["create_url"])
        self.assertEqual(data["create_payload"]["media_type"], "REELS")

    def test_unknown_channel_400(self) -> None:
        r = self.client.post(
            "/admin/api/ops/instagram/publish-reel",
            json=self._body(channel_id="999"), headers={"X-Ops-Token": "secret-token"},
        )
        self.assertEqual(r.status_code, 400)

    def test_full_publish_flow(self) -> None:
        with mock.patch.object(ig.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(ig.asyncio, "sleep", new=_noop_sleep):
            r = self.client.post(
                "/admin/api/ops/instagram/publish-reel",
                json=self._body(), headers={"X-Ops-Token": "secret-token"},
            )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["creation_id"], "CONTAINER123")
        self.assertEqual(data["media_id"], "MEDIA999")
        self.assertEqual(data["permalink"], "https://instagram.com/reel/abc")
        urls = [u for u, _ in _FakeAsyncClient.posts]
        self.assertTrue(any(u.endswith("/media") for u in urls))
        self.assertTrue(any(u.endswith("/media_publish") for u in urls))


async def _noop_sleep(*a, **k) -> None:
    return None


class TestOpsTokenUnset(unittest.TestCase):
    def test_503_when_token_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPS_API_TOKEN", None)
            client = TestClient(_make_app())
            r = client.post(
                "/admin/api/ops/instagram/publish-reel",
                json={"channel_id": "105", "video_url": "x"},
                headers={"X-Ops-Token": "anything"},
            )
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()
