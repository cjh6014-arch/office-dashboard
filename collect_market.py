"""한국부동산원 R-ONE 오픈API → 오피스 공실률 · 임대료(분기, 권역별).

R-ONE(https://www.reb.or.kr/r-one/) 에서 오픈API 키를 받고, '상업용부동산 임대동향조사' 통계표의
STATBL_ID 와 분류코드(권역)를 아래 TABLES 에 채웁니다. 통계표 번호는 사이트 '통계표 ID 조회'에서 확인.
(예시 값은 자리표시자이며 실제 ID 로 바꿔야 합니다.)

출력: data/cache/market.json  = {"vacancy":[...], "rent":[...]}
"""
import json, sys, urllib.parse, urllib.request
from config import *

API = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
TABLES = {
    # 측정항목 : (STATBL_ID, 분류코드→표시 권역명)
    "vacancy": ("A_2024_00178", {"500001": "전국", "500002": "서울", "500003": "CBD", "500004": "GBD", "500005": "YBD", "500006": "BBD"}),
    "rent":    ("A_2024_00179", {"500001": "전국", "500002": "서울", "500003": "CBD", "500004": "GBD", "500005": "YBD", "500006": "BBD"}),
}


def fetch(statbl, start="201901"):
    q = dict(KEY=REB_KEY, Type="json", pIndex=1, pSize=1000, STATBL_ID=statbl, DTACYCLE_CD="QY", START_WRTTIME=start)
    url = API + "?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
    rows = body.get("SttsApiTblData", [{}, {}])[1].get("row", [])
    return rows


def quarter(wrttime):   # '2024Q1' 또는 '202401' 형식 보정
    s = str(wrttime)
    if "Q" in s:
        return s
    return f"{s[:4]}Q{int(s[4:6])}" if len(s) == 6 else s


def collect(measure):
    statbl, codes = TABLES[measure]
    by_q = {}
    for row in fetch(statbl):
        name = codes.get(str(row.get("CLS_ID")))
        if not name:
            continue
        q = quarter(row.get("WRTTIME_IDTFR_ID"))
        by_q.setdefault(q, {"quarter": q})[name] = float(row.get("DTA_VAL"))
    return [by_q[q] for q in sorted(by_q)]


def main():
    cache = CACHE / "market.json"
    prev = json.load(open(cache, encoding="utf-8")) if cache.exists() else {}
    out = {}
    for m in TABLES:
        try:
            out[m] = collect(m) or prev.get(m, [])
        except Exception as e:
            print("market", m, "실패 — 이전 값 유지:", e, file=sys.stderr)
            out[m] = prev.get(m, [])
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("market", {k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
