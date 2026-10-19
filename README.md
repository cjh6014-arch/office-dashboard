# 오피스 개발 현황 대시보드

전국 건축 인허가 대장에서 주용도가 **업무시설**인 건의 허가 → 착공 → 준공 추이와 위치, 한국부동산원 권역별 오피스
공실률 · 임대료, 거래 규모, 제도 · 일정, 기사를 한 화면에 모은 정적 대시보드입니다. dc.namepf.com 과 같은 구조로,
정적 HTML 한 장 + `data/data.json` + GitHub Actions 매일 갱신 + Cloudflare Pages 배포로 돌아갑니다.

```
index.html                 배포용 페이지(완전한 HTML)
page.html                  같은 내용의 본문만(claude.ai 아티팩트 미리보기용) — 수정은 둘 중 하나만 하고 복사
data/data.json             화면이 읽는 데이터 (처음엔 샘플, 갱신 후 실데이터)
data/map.json              시군구 경계 GeoJSON (southkorea-maps, 소수점 3자리로 축소)
data/cache/*.json          원천별 수집 결과 — 실패 시 이전 값 유지
scripts/collect_permits.py 건축HUB 건축인허가 → 업무시설 인허가 목록 + 층별 업무시설 비중
scripts/collect_market.py  한국부동산원 R-ONE → 공실률 · 임대료(분기 · 권역)
scripts/collect_deals.py   실거래가(상업업무용) → 연간 업무시설 거래액
scripts/collect_news.py    구글뉴스 RSS → 기사 · 사업장별 관련 기사 매칭(주 1회) · 제도 · 일정(주 1회, Claude 분류)
scripts/build.py           캐시를 합쳐 data/data.json 작성
scripts/sample_data.py     샘플 데이터 생성(API 키 없을 때 화면 확인용)
.github/workflows/update.yml  매일 08:00 KST 실행 → data 커밋
```

## 1. 처음 띄우기 (샘플)

```bash
python scripts/sample_data.py
python -m http.server 8000      # http://localhost:8000
```

## 2. 실데이터 연결

| 원천 | 키 · 준비물 | 넣는 곳 |
|---|---|---|
| 공공데이터포털 — 건축HUB 건축인허가정보, 상업업무용 실거래가 | 포털에서 두 API 활용신청 후 발급 키 | Secrets `DATA_GO_KR_KEY` |
| 행정안전부 법정동코드 전체자료 | 포털에서 txt 내려받기 | `data/bjdong_codes.txt` (cp949, 탭 구분) |
| 한국부동산원 R-ONE 오픈API | 키 + 오피스 공실률 · 임대료 통계표 ID | Secrets `REB_KEY`, `scripts/collect_market.py` 의 `TABLES` |
| Anthropic API (선택) | 기사 매칭 · 제도 분류에 사용. 없으면 규칙 매칭만 | Secrets `ANTHROPIC_API_KEY` |
| Kakao REST (선택) | 법정동 좌표 지오코딩. 없으면 시군구 대표점 | Secrets `KAKAO_REST_KEY` |
| 푸터 운영자 문구 | 예: `OO증권 OO부 홍길동 (email, 전화)` | Variables `OWNER` |

주의할 점
- 건축HUB 파라미터 · 응답 필드명(`archPmsDay`, `realStcnsDay`, `useAprDay`, `totArea`, `mainPurpsCdNm` 등)은 포털
  '활용가이드' 최신본과 한 번 대조하세요. PK 체계가 바뀐 이력이 있습니다.
- 전국 시군구(약 250곳)를 매일 훑으므로 일일 트래픽 한도(기본 1,000~10,000건)를 넘으면 포털에서 **활용목적 변경 → 트래픽 증가 신청**이 필요합니다.
  첫 수집 뒤에는 `PERMIT_SINCE` 를 최근 1년으로 줄여 호출 수를 줄이는 것도 방법입니다.
- 오피스텔은 대장상 업무시설이지만 주거 성격이 강해 `exclude` 로 표시해 기본 집계에서 뺍니다(`config.py`).

## 3. 자동 갱신

`.github/workflows/update.yml` 이 매일 UTC 23:00(08:00 KST)에 수집 → `build.py` → `data/` 커밋을 합니다.
기사 매칭과 제도 · 일정은 매주 월요일에만 다시 검색하고, Actions 화면의 **Run workflow → weekly** 로 바로 돌릴 수 있습니다.

## 4. 배포 (Cloudflare Pages)

1. 이 저장소를 GitHub 에 올립니다.
2. Cloudflare → Workers & Pages → Create → Pages → Connect to Git → 저장소 선택.
3. Build command 비움, Build output directory `/` (루트). 저장하면 `*.pages.dev` 주소가 생깁니다.
4. Custom domain 에서 `office.내도메인.com` 처럼 서브도메인을 붙입니다.
5. 데이터 커밋이 들어올 때마다 Pages 가 자동 재배포합니다.

## 5. data.json 구조

```jsonc
{
  "updated": "2026-10-15 08:00", "sample": false, "owner": "…",
  "permits": [{ "id","name","kind","sido","sigungu","dong","zone","lat","lng","gfa","office_ratio",
                "floors","permit","start","complete","stage","articles":[{"title","url","date","source"}] }],
  "vacancy": [{ "quarter":"2026Q2", "전국":.., "서울":.., "CBD":.., "GBD":.., "YBD":.., "BBD":.. }],
  "rent":    [ 같은 형식 (천원/㎡·월) ],
  "deals":   [{ "year", "amount"(조원), "count" }],
  "policies":[{ "date":"YYYY-MM","field","title","status","note","source" }],
  "news":    [{ "date","title","url","source" }]
}
```
