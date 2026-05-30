# 09 — 인스타그램 댓글 → 자동 DM (인포크링크식 DM 관리)

인스타 게시물에 **지정 키워드 댓글이 달리면 → 공개 답글 + 맞춤 DM(상품 링크)** 을 자동 발송하는 기능.
인포크링크(Inpock) 자동 DM과 **동일한 사용 경험**을 목표로, 백오피스 **'DM 관리'** 메뉴에서 게시물·키워드·답글·링크를 규칙으로 관리한다.

> 상태: **구현 완료(MVP)**. 기본 웹훅 + DM 관리 UI 모두 구현 — [app/webhooks/instagram.py](../app/webhooks/instagram.py), [app/admin/ops/routes/dm.py](../app/admin/ops/routes/dm.py), [app/admin/templates/dm.html](../app/admin/templates/dm.html), [static/js/admin-dm.js](../static/js/admin-dm.js).
> shortcrew는 **숏크루-IG**(별도 Meta 앱, App ID `26786055824397018`)로 운영. short-mall(숏몰-IG)과 앱·서버·콜백이 분리됨. short-mall repo에도 동일 구조의 09 문서가 있다.
> 관련: [01 채널](01_CHANNEL_GUIDE.md) · [02 딥링크](02_SHEETS_DEEPLINK_AND_SUBID.md)

> **확정 결정(2026-05-29)**: ① 규칙 저장 = **SQLite DB** · ② DM 링크 = **상품 선택**(채널 상품 목록에서 골라 딥링크 자동, 쿠팡 추적 보존) · ③ 구현 순서 = **short-mall 먼저 → shortcrew 이식** · ④ **기존 admin UI 패턴** 재사용(새 프레임워크·공유 라이브러리 없음).

---

## 0. 큰 그림

```
[관리자] 백오피스 'DM 관리'에서 규칙 생성
   · 게시물: 직접 선택  |  다음 발행 게시물 자동
   · 트리거: 모든 댓글  |  특정 키워드
   · 공개 답글: 랜덤 3종 (선택)
   · DM: 본문 + 링크(상품/몰)
        │ 저장 → DB(dm_automations)
        ▼
[사용자가 그 게시물에 키워드 댓글]
        │
        ▼
[Webhook(comments) POST] → /webhooks/instagram (shortcrew.co.kr)
        │  (1) 서명 검증
        │  (2) account_id → 채널(인플루언서)
        │  (3) media_id + 댓글 text 로 매칭되는 규칙 탐색
        ▼
  매칭되면:  · 공개 답글 1개(랜덤) → POST /{comment-id}/replies
            · 비공개 DM → POST /{ig-id}/messages (recipient=comment_id)
```

핵심: **게시물·키워드별 규칙**으로 매칭한다. 코드 골격(서명 검증·계정 매핑·DM 발송) 유지하고, **규칙 저장소 + 매칭 로직 + 백오피스 UI**가 얹어진 구조.

---

## A. Meta 개발자센터 설정 (요약)

| 항목 | 값 |
|------|----|
| 앱 | **숏크루-IG** (App ID `26786055824397018`) — 숏몰-IG와 별개 |
| 방식 | Instagram API with Instagram **login**(비즈니스) — 베이스 `graph.instagram.com` |
| 권한 | `instagram_business_basic`, `instagram_manage_comments`(댓글·답글), `instagram_business_manage_messages`(DM) |
| 콜백 | `https://shortcrew.co.kr/webhooks/instagram` |
| 인증 토큰 | `.env`의 `IG_WEBHOOK_VERIFY_TOKEN` |
| 구독 필드 | `comments` + 계정별 토글 ON |
| 개발 모드 | 테스터로 등록·수락한 IG 계정만 동작 → 검수 후 일반 공개 |

비공개 답장(Private Reply)은 **댓글 후 7일 이내·댓글당 1회**.

---

## B. 기본 웹훅 (구현됨)

| 위치 | 역할 |
|------|------|
| `app/webhooks/instagram.py` | GET 검증 / POST 서명검증·댓글파싱·규칙 매칭·발송 |
| `main.py` | `include_router(ig_webhook_router)` (공개, 인증 없음) |

- `.env`: 앱 공통(`IG_APP_ID/SECRET`, `IG_WEBHOOK_VERIFY_TOKEN`, `IG_GRAPH_API_VERSION`) + 채널별(`CHANNEL_{ID}_IG_USERNAME/ACCOUNT_ID/ACCESS_TOKEN`).
- 채널(인플루언서) 매핑: 웹훅 `entry[].id` == `CHANNEL_{ID}_IG_ACCOUNT_ID`.

| 채널 | 인플루언서 | IG 계정 | DM 링크 도메인 |
|------|-----------|---------|---------------|
| 102 | 오세련픽(골프) | seryeon.golf | shortcrew.co.kr/golf |
| 103 | 왕세림픽(테니스) | serim.tennis | shortcrew.co.kr/tennis |
| 104 | 한소율픽(쇼핑) | (IG 미연결) | — |

DM 링크는 `PUBLIC_SITE_URL=https://shortcrew.co.kr` 기준으로 자동 생성됨(코드 공용, 도메인만 다름).

---

## C. ★ 인포크링크식 DM 관리

### C-1. 기능 요구 (인포크 동등)

- [x] **게시물 타게팅 2종**: ① 게시물 직접 선택(내 게시물 불러와 그리드에서 선택) ② 다음 발행 게시물 자동 적용
- [x] **트리거**: 모든 댓글 / 특정 키워드(여러 개)
- [x] **공개 답글(댓글에 답글)**: 켜기/끄기 + **랜덤 3종 입력**(스팸 감지 회피)
- [x] **DM 내용**: 본문 텍스트 + 상품 선택(딥링크 자동, 쿠팡 추적 보존)
- [x] **내용 미리보기**
- [ ] (선택) 팔로워/비팔로워 분기

### C-2. 백오피스 메뉴·페이지

- 사이드바 '몰 운영' 섹션, **상품 관리 바로 아래** 'DM 관리' (`forum` 아이콘) — `app/admin/templates/layout.html`.
- 페이지 `GET /admin/dm` (HTML, `Depends(require_admin)`) — `main.py`.
- 템플릿 `app/admin/templates/dm.html`(layout.html 확장).
- 화면 구성: 채널(인플루언서) 선택 → 규칙 목록 → "자동화 추가" 편집 패널.

### C-3. DB 모델 (`dm_automations`)

`models.py`의 `DmAutomation`:

```python
class DmAutomation(Base):
    __tablename__ = "dm_automations"
    id: Mapped[int]
    channel_id: Mapped[str]                  # "102", "103" …
    name: Mapped[str]
    # 게시물 타게팅
    target_mode: Mapped[str]                 # specific | next
    ig_media_id: Mapped[str | None]
    media_permalink, media_thumbnail: Mapped[str | None]
    next_baseline_ts: Mapped[str | None]
    # 트리거
    trigger_type: Mapped[str]                # any | keyword
    keywords_json: Mapped[str]
    # 공개 답글
    public_reply_enabled: Mapped[bool]
    public_reply_variants_json: Mapped[str]  # 최대 3
    # DM (상품 선택 → 딥링크 자동)
    dm_message: Mapped[str]
    dm_product_ref: Mapped[str | None]
    dm_product_title: Mapped[str | None]
    dm_link: Mapped[str]
    # 옵션/상태
    follower_only: Mapped[bool]
    active: Mapped[bool]
    created_at, updated_at: Mapped[datetime]
```

`Base.metadata.create_all`로 신규 테이블 자동 생성.

### C-4. 게시물 불러오기 (Graph 프록시)

`GET /admin/api/ops/dm/media?channel_id=` → 서버가 채널 토큰으로 `graph.instagram.com/{ver}/{ig-id}/media` 호출 → 토큰 비노출 상태로 클라이언트에 JSON 반환.

### C-5. 규칙 설정 UI 흐름

1. 채널(IG 계정) 선택 → "+ 자동화 추가"
2. **게시물 선택**: 탭 `직접 선택`(C-4 그리드) / `다음 발행 게시물 자동`
3. **트리거**: `모든 댓글` / `특정 키워드`(쉼표 구분)
4. **공개 답글**: on/off + **3칸 입력**(랜덤 발송)
5. **DM 내용**: 본문 + **상품 선택**(채널 상품 목록 드롭다운 → 딥링크 자동, 쿠팡 추적 보존)
6. **미리보기** → 저장

| 메서드 | 경로 | 역할 |
|--------|------|------|
| GET | `/admin/api/ops/dm/channels` | IG 설정된 채널 목록(드롭다운) |
| GET | `/admin/api/ops/dm/media?channel_id=` | 게시물 목록(Graph 프록시) |
| GET | `/admin/api/ops/dm/rules?channel_id=` | 규칙 목록 |
| POST | `/admin/api/ops/dm/rules` | 생성 |
| PATCH | `/admin/api/ops/dm/rules/{id}` | 수정(활성 토글 포함) |
| DELETE | `/admin/api/ops/dm/rules/{id}` | 삭제 |

상품 목록은 별도 API 없이 프론트가 기존 `/api/mall-products?channel_id=` 재사용.

### C-6. 웹훅 매칭 로직

```
on comment(account_id, media_id, text, comment_id, from_id):
  채널 = resolve(account_id);  토큰 = 채널 토큰
  rules = dm_automations WHERE channel_id=채널.id AND active=1 ORDER BY id DESC
  for r in rules:
     if r.target_mode=="specific" and r.ig_media_id != media_id: continue
     if r.target_mode=="next":
         바인딩(r, media_id)  # 미바인딩이면 첫 댓글 게시물에 1회 바인딩(MVP)
         if r.ig_media_id != media_id: continue
     if r.trigger_type=="keyword" and not any(kw in text for kw in r.keywords): continue
     매칭.append(r); break
  if 매칭:
     if r.public_reply_enabled: 공개답글(comment_id, random.choice(r.variants))
     DM(account_id, 토큰, comment_id, r.dm_message + "\n" + r.dm_link)
```

- 본인 댓글 스킵 유지(`from.id == entry.id`).
- 첫 매칭 1건만 실행(중복 DM 방지).
- 발송은 BackgroundTask(즉시 200).

### C-7. 공개 답글

```
POST https://graph.instagram.com/{ver}/{comment-id}/replies
     message=<랜덤 변형 1개>   (Authorization: Bearer <token>)
```
권한 `instagram_manage_comments`(보유).

### C-8. "다음 발행 게시물 자동" 모드 (MVP 한계)

- 현재: 규칙 저장 후 첫 댓글의 게시물 ID에 lazy 바인딩.
- 한계: 옛 게시물에 늦은 댓글이 들리면 그곳에 잘못 바인딩 가능.
- 정밀화(후속): `next_baseline_ts` 기반 timestamp 비교(Graph media 조회 1회).

### C-9. 내용 미리보기

순수 프론트(`admin-dm.js`). DM 카드(본문+링크) + 공개 답글 예시 렌더. 저장 전 확인용.

---

## D. 보안

- 시크릿(`IG_APP_SECRET`/토큰/verify token)은 `.env`에만(`.gitignore` 대상 확인됨).
- 토큰은 채널 dict·API 응답에 노출 금지(웹훅 모듈이 env 직접 조회).
- 서명 검증 실패 → 403. 본인 댓글 스킵으로 루프 차단.
- 규칙 매칭은 첫 1건만 실행(중복 DM 방지).
- `/admin/dm`·`dm/*` API는 `require_admin`. 게시물/규칙 API는 토큰을 절대 클라이언트로 내려보내지 않음.

---

## E. 운영 체크리스트

- [x] 기본 웹훅 + `.env` IG 키 (102/103)
- [x] DM 관리 UI + 규칙 CRUD + 매칭 구현
- [x] 도커 배포 (`shortcrew.co.kr` 라이브)
- [ ] Meta 콜백 저장 + `comments` 구독 + 계정 토글 ON
- [ ] 테스터 계정 실댓글 → 공개답글 + DM 확인
- [ ] 앱 검수
- [ ] 104(한소율픽) IG 계정 연결 시 `.env` 채우기
- [ ] (후속) "다음 게시물 자동" baseline 정밀화
