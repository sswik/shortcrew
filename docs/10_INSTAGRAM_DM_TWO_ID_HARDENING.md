# 10 — 인스타 DM 자동화: 두-ID 견고화 (short-mall 이식)

short-mall 에서 먼저 적용한 **댓글→DM 웹훅 견고화**를 shortcrew(인플루언서 제품, 별도 Meta 앱)에 동일하게 이식한 기록.

> shortcrew 와 short-mall 은 **같은 코드 골격**(멀티채널 `CHANNEL_{ID}_IG_*`, `app/webhooks/instagram.py`, `app/admin/ops/routes/dm.py`, `models.DmAutomation`)을 쓴다. 차이는 채널 구성과 **별도 Meta 앱**(앱 ID/시크릿/verify token)뿐이다.
>
> 관련: [09 댓글→DM 설계](09_INSTAGRAM_COMMENT_TO_DM.md) · 코드 [app/webhooks/instagram.py](../app/webhooks/instagram.py)

---

## 1. 기존 구현 vs 이번 구현

| 항목 | 기존(이번 전) | 이번 적용 |
|------|--------------|-----------|
| 계정 ID | `CHANNEL_{ID}_IG_ACCOUNT_ID` 1종(네이티브 user_id)만 사용 | + `CHANNEL_{ID}_IG_APP_SCOPED_ID`(앱스코프 id) 추가 |
| 채널 해석 | `entry.id == IG_ACCOUNT_ID` 단일 비교 | `entry.id ∈ {네이티브, 앱스코프}` 집합 비교 |
| 루프 방지 | `from_id == account_id`(앱스코프 단일) | `from_id ∈ {네이티브, 앱스코프}` 집합 + **채널 해석 이후**로 이동 |
| DM 발송 계정 | `entry.id` 그대로 `/messages` 호출 | 항상 네이티브 `IG_ACCOUNT_ID`(`send_id`)로 호출(entry.id 가 앱스코프여도 안전) |

### 왜 (한 계정 = 두 ID)
`GET /me` 는 IG 계정마다 **두 ID** 를 돌려준다:

| 필드 | 용도 | env |
|------|------|-----|
| `user_id` | 네이티브 IG 계정 ID — `/media`·`/messages` 등 Graph 리소스 호출용 | `CHANNEL_{ID}_IG_ACCOUNT_ID` |
| `id` | 앱스코프 ID — 웹훅 `entry.id`/`from.id` 가 이 값으로 올 수 있음 | `CHANNEL_{ID}_IG_APP_SCOPED_ID` |

웹훅이 둘 중 어느 ID를 보낼지 보장되지 않아(실댓글 검증 전), **채널 해석·루프 방지 모두 두 ID로** 판정하고 **Graph 발송은 네이티브 ID로** 고정한다. 운영 계정의 공개 답글/DM 이 다시 웹훅으로 들어올 때 본인으로 못 걸러 무한 루프 도는 것을 막는 핵심 가드.

---

## 2. 코드 변경 ([app/webhooks/instagram.py](../app/webhooks/instagram.py))

short-mall 과 **동일 패치**:
1. `_channel_ig_ids(channel_id)` — 네이티브+앱스코프 ID 집합 헬퍼.
2. `_resolve_ig_channel` — 단일 `IG_ACCOUNT_ID` 비교 → `entry.id in _channel_ig_ids(cid)`.
3. 루프 방지를 채널 해석 이후로 옮기고 두 ID로 판정.
4. `_send_account_id(channel_id)` — `/messages` 는 항상 네이티브 ID(`send_id`)로.

---

## 3. 설정 ([.env](../.env))

채널 102(seryeon.golf)·103(serim.tennis) 에 `APP_SCOPED_ID` 추가 완료.

```
CHANNEL_102_IG_USERNAME=seryeon.golf
CHANNEL_102_IG_ACCOUNT_ID=17841480125942110      # user_id (네이티브)
CHANNEL_102_IG_APP_SCOPED_ID=26589649427384115   # id (앱스코프)
CHANNEL_102_IG_ACCESS_TOKEN=IGAF...

CHANNEL_103_IG_USERNAME=serim.tennis
CHANNEL_103_IG_ACCOUNT_ID=17841477502597093
CHANNEL_103_IG_APP_SCOPED_ID=27228507580106371
CHANNEL_103_IG_ACCESS_TOKEN=IGAF...
```
> ID 확인법: `GET https://graph.instagram.com/v21.0/me?fields=id,user_id,username&access_token=<토큰>`

`.env.example` 에도 IG 섹션 양식 추가(앱 공통 + `CHANNEL_*_IG_USERNAME/ACCOUNT_ID/APP_SCOPED_ID/ACCESS_TOKEN`).

---

## 4. 후속

- [ ] **서버·터널 재빌드/재시작** — 새 `APP_SCOPED_ID`·두-ID 코드가 운영에 반영되려면 필요.
- [ ] Meta 콜백 URL + `comments` 구독 + 계정별(102/103) Webhook 토글 ON.
- [ ] 테스터 계정 실댓글 → 공개 답글/DM, 본인 이벤트 스킵, `entry.id`/`from.id` 실제 ID 확인.
