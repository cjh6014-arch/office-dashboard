"""공통 설정. 키는 환경변수(GitHub Actions Secrets)로 넣습니다."""
import os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"          # 원천 수집 결과(JSON) — 실패 시 이전 값 유지용
CACHE.mkdir(parents=True, exist_ok=True)

DATA_GO_KR_KEY = os.environ.get("DATA_GO_KR_KEY", "")      # 공공데이터포털 (건축HUB · 실거래가)
REB_KEY = os.environ.get("REB_KEY", "")                    # 한국부동산원 R-ONE 오픈API
KAKAO_KEY = os.environ.get("KAKAO_REST_KEY", "")           # (선택) 법정동 좌표 지오코딩
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")    # (선택) 기사 매칭 · 제도 분류
OWNER = os.environ.get("OWNER", "")                        # 푸터 '기획 · 운영' 문구

# 집계 대상 주용도 — 건축HUB mainPurpsCdNm 값과 비교. 오피스텔은 kind 로만 표시하고 기본 집계 제외.
OFFICE_PURPOSES = {"업무시설", "일반업무시설", "공공업무시설"}
EXCLUDE_NAME_TOKENS = ("오피스텔",)

# 서울 권역 (한국부동산원 구분) — 시군구명 기준
ZONE_BY_SIGUNGU = {
    "종로구": "CBD", "중구": "CBD",
    "강남구": "GBD", "서초구": "GBD",
    "영등포구": "YBD", "마포구": "YBD",
}
BBD_DONGS = ("분당구", "판교")  # 성남시 분당구 → BBD
METRO_SIDO = {"서울특별시", "경기도", "인천광역시"}

# 허가일 수집 시작 — 이보다 오래된 건은 모으지 않음
PERMIT_SINCE = "20180101"
