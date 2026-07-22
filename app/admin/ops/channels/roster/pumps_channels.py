"""pump 채널 빌더 모음.

채널 이름은 `.env`의 `CHANNEL_{ID}_TAB`를 우선 사용한다.

숏크루 통합본: 02/03/04 는 인플루언서 몰(골프·테니스·쇼핑), 05~37 은 펌프 몰.
모두 `MALL_PUMP_SLUG` 기반이며 딥링크 subId 는 `shortcrew` 고정(숏몰과 값만 다름).
"""
from __future__ import annotations

import os

from ..constants import COMMON_HISTORY_FILE_ID, DEFAULT_TREND_KEYWORDS
from ..env_names import channel_env

_CHANNEL_TREND_SEEDS: dict[str, dict[str, list[str]]] = {
    "02": {
        "naver_category_id": ["50000172", "50000000"],
        "trend_keywords": [
            "골프", "골프채", "드라이버", "퍼터", "골프공",
            "골프장갑", "골프화", "라운딩", "골프의류", "골프거리측정기",
            "골프백", "골프우산", "골프모자", "스크린골프", "골프연습용품",
            "골프토시", "골프양말", "골프티", "골프마커", "가성비",
        ],
    },
    "03": {
        "naver_category_id": ["50000172", "50000000"],
        "trend_keywords": [
            "테니스", "테니스화", "테니스라켓", "테니스복", "운동화",
            "스포츠양말", "그립테이프", "테니스가방", "테니스공", "손목보호대",
            "테니스캡", "스포츠타월", "테니스스커트", "무릎보호대", "쿨토시",
            "테니스스트링", "진동방지기", "스포츠고글", "테니스라켓가방", "가성비",
        ],
    },
    "04": {
        "naver_category_id": ["50000173", "50000002", "50000000"],
        "trend_keywords": [
            "라이브커머스", "데일리템", "자취꿀템", "주방용품", "생필품",
            "스킨케어", "클렌징", "선크림", "마스크팩", "생활용품",
            "수납정리", "욕실용품", "청소용품", "주방수납", "가성비",
            "쿠팡추천", "홈리빙", "소형가전", "1인가구", "다이소추천",
        ],
    },
    "05": {
        "naver_category_id": ["50000003"],
        "trend_keywords": [
            "홈캠", "가정용CCTV", "펫캠", "베이비캠", "IP카메라",
            "웹캠", "스마트플러그", "스마트전구", "블랙박스", "도어벨",
            "실내카메라", "실외카메라", "현관카메라", "무선CCTV", "와이파이카메라",
            "양방향오디오카메라", "야간감시카메라", "모션감지카메라", "보안카메라", "스마트홈허브",
        ],
    },
    "07": {
        "naver_category_id": ["50000120", "50000008", "50000015"],
        "trend_keywords": [
            "베스트셀러", "경제전망", "자기계발서", "심리학도서", "역사책",
            "과학도서", "인문학", "재테크", "사고력", "철학도서",
            "다이어리", "만년필", "사무용품", "데스크테리어", "독서대",
            "필기구", "북스탠드", "스터디플래너", "노트패드", "아이패드거치대",
        ],
    },
    "09": {
        "naver_category_id": ["50000175", "50000120", "50000008"],
        "trend_keywords": [
            "역사책", "한국사", "세계사", "위인전", "역사만화",
            "인문학도서", "다큐멘터리", "박물관굿즈", "전통공예품", "고전수필",
            "만년필", "지도", "지구본", "레트로소품", "엔틱소품",
            "한복", "기념주화", "전통차", "서예용품", "역사소설",
        ],
    },
    "10": {
        "naver_category_id": ["50000175", "50000167", "50000008"],
        "trend_keywords": [
            "과학도서", "현미경", "천체망원경", "실험키트", "과학교구",
            "지구본", "코딩로봇", "SF소설", "백과사전", "퍼즐",
            "레고", "우주인소품", "스마트워치", "기능성음료", "영양제",
            "만보기", "체성분체중계", "블루라이트차단안경", "식물재배기", "기상관측기",
        ],
    },
    "11": {
        "naver_category_id": ["50000175", "50000167", "50000008"],
        "trend_keywords": [
            "천체망원경", "별자리무드등", "우주인조명", "플라네타륨", "태양계모형",
            "과학도서", "SF소설", "우주식량", "로켓모형", "과학교구",
            "지구본", "우주복", "야광별", "코딩로봇", "현미경",
            "우주퍼즐", "스마트워치", "기상관측기", "실험키트", "백과사전",
        ],
    },
    "12": {
        "naver_category_id": ["50000175", "50000167", "50000008"],
        "trend_keywords": [
            "해양다큐멘터리", "과학도서", "어항", "수족관", "오션무드등",
            "스쿠버장비", "스노클링", "오리발", "방수팩", "액션캠",
            "심해어피규어", "해양생물도감", "바다소금", "입욕제", "아쿠아슈즈",
            "다이빙시계", "해양심층수", "수중카메라", "수영복", "지구본",
        ],
    },
    "13": {
        "naver_category_id": ["50000175", "50000172", "50000173"],
        "trend_keywords": [
            "자연다큐멘터리", "동물도감", "과학도서", "쌍안경", "캠핑장비",
            "생존배낭", "서바이벌키트", "바람막이", "등산화", "침낭",
            "아웃도어랜턴", "야간투시경", "다용도나이프", "동물피규어", "반려동물용품",
            "구급상자", "방수자켓", "망원경", "자연과학", "생물학도서",
        ],
    },
    "14": {
        "naver_category_id": ["50000175", "50000008"],
        "trend_keywords": [
            "뇌과학도서", "심리학도서", "자기계발서", "수면안대", "백색소음기",
            "집중력향상", "명상용품", "아로마오일", "스트레스해소기구", "오메가3",
            "퍼즐", "두뇌개발교구", "건강기능식품", "스마트워치", "숙면베개",
            "루빅스큐브", "만년필", "다이어리", "마인드맵", "기억력영양제",
        ],
    },
    "15": {
        "naver_category_id": ["50000173", "50000175"],
        "trend_keywords": [
            "유산균", "비타민C", "오메가3", "마그네슘", "건강도서",
            "혈압계", "혈당측정기", "체온계", "마사지기", "자세교정기",
            "수면안대", "단백질보충제", "찜질팩", "홍삼", "다이어트보조제",
            "의학서적", "구급상자", "프로바이오틱스", "눈영양제", "관절영양제",
        ],
    },
    "16": {
        "naver_category_id": ["50000175", "50000173"],
        "trend_keywords": ["심리학도서", "자기계발", "인간관계", "심리테스트", "명상용품", "스트레스해소"],
    },
    "17": {
        "naver_category_id": ["50000175"],
        "trend_keywords": ["재테크도서", "경제전망", "부의감각", "주식투자", "부동산책", "가계부", "다이어리"],
    },
    "18": {
        "naver_category_id": ["50000175"],
        "trend_keywords": ["법학도서", "생활법률", "추리소설", "정치학", "변호사추천", "논리력교재"],
    },
    "19": {
        "naver_category_id": ["50000175", "50000008", "50000167"],
        "trend_keywords": [
            "추리소설", "범죄심리학", "프로파일링도서", "호신용품", "호신용스프레이",
            "경보기", "삼단봉", "가정용CCTV", "홈캠", "녹음기",
            "도어락", "안전장치", "현관카메라", "미스터리소설", "법의학도서",
            "비상벨", "창문잠금장치", "호신경보기", "스마트도어벨", "호신용휘슬",
        ],
    },
    "20": {
        "naver_category_id": ["50000175", "50000170"],
        "trend_keywords": ["미술사도서", "명화포스터", "전시회굿즈", "드로잉세트", "인테리어액자", "디자인소품"],
    },
    "21": {
        "naver_category_id": ["50000175", "50000167"],
        "trend_keywords": ["음악이론", "블루투스스피커", "헤드폰", "턴테이블", "악보집", "LP수집"],
    },
    "22": {
        "naver_category_id": ["50000175", "50000167"],
        "trend_keywords": ["영화설정집", "빔프로젝터", "홈시네마", "영화포스터", "각본집", "팝콘제조기"],
    },
    "23": {
        "naver_category_id": ["50000175"],
        "trend_keywords": ["베스트셀러", "독서대", "북라이트", "책갈피", "전자책리더기", "고전문학"],
    },
    "24": {
        "naver_category_id": ["50000167", "50000175", "50000170"],
        "trend_keywords": [
            "기계식키보드", "마우스", "태블릿거치대", "스마트워치", "보조배터리",
            "IT도서", "개발자도서", "과학도서", "데스크테리어", "블루투스이어폰",
            "노트북스탠드", "웹캠", "모니터암", "코딩교육", "스마트홈",
            "얼리어답터", "드론", "스마트플러그", "가젯", "혁신기술",
        ],
    },
    "25": {
        "naver_category_id": ["50000175", "50000173", "50000167"],
        "trend_keywords": [
            "아이디어상품", "발명품", "과학도서", "혁신기술", "기발한선물",
            "전자레인지", "포스트잇", "생활꿀템", "얼리어답터", "스마트가전",
            "실험키트", "개발자도서", "스타트업도서", "특허", "문구류",
            "데스크테리어", "스마트홈", "기능성용품", "아이디어주방용품", "가젯",
        ],
    },
    "26": {
        "naver_category_id": ["50000175", "50000167"],
        "trend_keywords": ["AI활용법", "챗GPT도서", "코딩교구", "스마트홈", "얼리어답터가젯", "IT기기"],
    },
    "27": {
        "naver_category_id": ["50000175", "50000172", "50000167"],
        "trend_keywords": [
            "지구본", "세계지도", "망원경", "쌍안경", "캠핑장비",
            "백패킹용품", "나침반", "미스터리도서", "과학도서", "여행가젯",
            "액션캠", "드론", "서바이벌키트", "방수백", "야간투시경",
            "지리책", "인문학도서", "고급지구본", "입체지도", "탐사용품",
        ],
    },
    "28": {
        "naver_category_id": ["50000175", "50000008", "50000174"],
        "trend_keywords": [
            "한국사도서", "역사책", "전통공예품", "나전칠기", "한복",
            "전통차", "다기세트", "문화유산도서", "기념품", "한지",
            "붓펜", "만년필", "K컬처", "전통장신구", "인문학도서",
            "역사만화", "전통소품", "부채", "도자기", "세종대왕",
        ],
    },
    "29": {
        "naver_category_id": ["50000175", "50000170"],
        "trend_keywords": ["고고학도서", "엔틱소품", "역사퍼즐", "박물관굿즈", "지구본", "탐사도구"],
    },
    "30": {
        "naver_category_id": ["50000175", "50000172"],
        "trend_keywords": ["전쟁사도서", "밀리터리소품", "전략게임", "프라모델", "서바이벌기어", "아웃도어"],
    },
    "31": {
        "naver_category_id": ["50000175", "50000167", "50000173"],
        "trend_keywords": [
            "추리소설", "역사책", "기밀문서", "암호해독", "홈캠",
            "가정용CCTV", "녹음기", "호신용품", "금고", "자물쇠",
            "밀리터리용품", "전술가방", "캠핑칼", "쌍안경", "야간투시경",
            "스마트도어벨", "호신용휘슬", "심리학도서", "방음재", "보안가젯",
        ],
    },
    "32": {
        "naver_category_id": ["50000175", "50000170", "50000008"],
        "trend_keywords": [
            "그리스로마신화", "북유럽신화", "신화도서", "인문학책", "조각상",
            "타로카드", "별자리무드등", "신비주의", "판타지소설", "명화포스터",
            "엔틱소품", "인테리어조각상", "세계사도서", "요괴대백과", "전설의고향",
            "풍수지리", "명상용품", "향로", "석고상", "신화굿즈",
        ],
    },
    "33": {
        "naver_category_id": ["50000175", "50000173"],
        "trend_keywords": ["철학책", "인문학도서", "명언집", "자기계발서", "명상용품", "싱잉볼", "다이어리", "만년필"],
    },
    "34": {
        "naver_category_id": ["50000172", "50000173"],
        "trend_keywords": ["생존배낭", "서바이벌키트", "멀티툴", "전투식량", "구급상자", "캠핑용품", "손전등", "방수성냥"],
    },
    "35": {
        "naver_category_id": ["50000175", "50000167"],
        "trend_keywords": ["미스터리소설", "추리소설", "호러굿즈", "CCTV", "녹음기", "암막커튼", "심리서적", "공포영화"],
    },
    "36": {
        "naver_category_id": ["50000175"],
        "trend_keywords": ["어원도서", "언어학", "인문학", "영어학습", "글쓰기교본", "사전"],
    },
    "37": {
        "naver_category_id": ["50000172", "50000167"],
        "trend_keywords": ["스포츠과학", "러닝화", "트레이닝복", "스마트워치", "마사지건", "단백질쉐이크", "기능성웨어", "홈트용품"],
    },
}


def _build_channel(*, cid: str, slug_fallback: str) -> dict:
    tab = os.getenv(channel_env(cid, "TAB"), "").strip()
    name_from_tab = tab.replace("-상품", "").strip() if tab else ""
    product_delivery = os.getenv(channel_env(cid, "PRODUCT_DELIVERY_WEBAPP_URL"), "").strip()
    mall_products = os.getenv(channel_env(cid, "MALL_PRODUCTS_API_URL"), "").strip()
    mall_pump_slug = os.getenv(channel_env(cid, "MALL_PUMP_SLUG"), "").strip() or slug_fallback
    trend_seed = _CHANNEL_TREND_SEEDS.get(cid) or {}
    naver_category_id = list(trend_seed.get("naver_category_id") or ["50000000"])
    trend_keywords = list(trend_seed.get("trend_keywords") or DEFAULT_TREND_KEYWORDS)
    return {
        "channel_id": cid,
        "name": name_from_tab or f"{mall_pump_slug}펌프",
        "google_sheet_id": os.getenv(channel_env(cid, "FILE_ID"), "").strip(),
        "sheet_tab_name": tab or "상품목록",
        "history_sheet_id": COMMON_HISTORY_FILE_ID,
        "history_sheet_tab": os.getenv(channel_env(cid, "HISTORY_TAB"), "기록").strip() or "기록",
        "product_delivery_url": product_delivery,
        "mall_products_api_url": mall_products or product_delivery,
        "mall_products_channel_param": os.getenv(channel_env(cid, "MALL_PRODUCTS_CHANNEL_PARAM"), "").strip(),
        "mall_pump_slug": mall_pump_slug,
        "naver_category_id": naver_category_id,
        "trend_keywords": trend_keywords,
        "monitor_keywords": [],
    }


def build_02() -> dict:
    return _build_channel(cid="02", slug_fallback="golf")


def build_03() -> dict:
    return _build_channel(cid="03", slug_fallback="tennis")


def build_04() -> dict:
    return _build_channel(cid="04", slug_fallback="shopping")


def build_05() -> dict:
    return _build_channel(cid="05", slug_fallback="homecam")


def build_07() -> dict:
    return _build_channel(cid="07", slug_fallback="knowledge")


def build_09() -> dict:
    return _build_channel(cid="09", slug_fallback="history")


def build_10() -> dict:
    return _build_channel(cid="10", slug_fallback="science")


def build_11() -> dict:
    return _build_channel(cid="11", slug_fallback="space")


def build_12() -> dict:
    return _build_channel(cid="12", slug_fallback="ocean")


def build_13() -> dict:
    return _build_channel(cid="13", slug_fallback="nature")


def build_14() -> dict:
    return _build_channel(cid="14", slug_fallback="brain")


def build_15() -> dict:
    return _build_channel(cid="15", slug_fallback="health-pump")


def build_16() -> dict:
    return _build_channel(cid="16", slug_fallback="psyche")


def build_17() -> dict:
    return _build_channel(cid="17", slug_fallback="money")


def build_18() -> dict:
    return _build_channel(cid="18", slug_fallback="law")


def build_19() -> dict:
    return _build_channel(cid="19", slug_fallback="crime")


def build_20() -> dict:
    return _build_channel(cid="20", slug_fallback="art")


def build_21() -> dict:
    return _build_channel(cid="21", slug_fallback="music")


def build_22() -> dict:
    return _build_channel(cid="22", slug_fallback="cinema")


def build_23() -> dict:
    return _build_channel(cid="23", slug_fallback="book")


def build_24() -> dict:
    return _build_channel(cid="24", slug_fallback="tech")


def build_25() -> dict:
    return _build_channel(cid="25", slug_fallback="invention")


def build_26() -> dict:
    return _build_channel(cid="26", slug_fallback="ai")


def build_27() -> dict:
    return _build_channel(cid="27", slug_fallback="geo")


def build_28() -> dict:
    return _build_channel(cid="28", slug_fallback="korea")


def build_29() -> dict:
    return _build_channel(cid="29", slug_fallback="ancient")


def build_30() -> dict:
    return _build_channel(cid="30", slug_fallback="war")


def build_31() -> dict:
    return _build_channel(cid="31", slug_fallback="spy")


def build_32() -> dict:
    return _build_channel(cid="32", slug_fallback="mythology")


def build_33() -> dict:
    return _build_channel(cid="33", slug_fallback="philosophy")


def build_34() -> dict:
    return _build_channel(cid="34", slug_fallback="survival")


def build_35() -> dict:
    return _build_channel(cid="35", slug_fallback="horror")


def build_36() -> dict:
    return _build_channel(cid="36", slug_fallback="word")


def build_37() -> dict:
    return _build_channel(cid="37", slug_fallback="sports")
