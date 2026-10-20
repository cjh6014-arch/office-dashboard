"""한국부동산원 R-ONE 오픈API → 오피스 공실률 · 임대료(분기, 권역별).

통계표는 기준 변경 때마다 ID가 바뀌어 기간별로 여러 개를 이어 붙입니다
(R-ONE '통계코드 검색'에서 '오피스'로 검색한 결과, 2026-10 기준).
지역은 ID 가 표마다 조금씩 달라 이름(CLS_FULLNM)으로 맞춥니다.

출력: data/cache/market.json = {"vacancy":[{"quarter":"2024Q1","전국":..,"서울":..,"CBD":..,...}], "rent":[...]}
"""
import json, re, sys, urllib.parse, urllib.request
from config import *

API = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
TABLES = {
    # 측정항목: 기간 순 통계표 ID (앞 표와 겹치는 분기는 뒤 표 값을 씀)
    "vacancy": ["A_2024_00244", "A_2024_00247", "A_2024_00250", "A_2024_00253", "TT244763134428698"],
    "rent":    ["A_2024_00265", "A_2024_00269", "A_2024_00273", "A_2024_00277", "TT249843134237374"],
}
# 화면 권역명 ← R-ONE 지역 전체이름(CLS_FULLNM) 패턴
ZONES = [
    ("전국", r"^전국$"), ("서울", r"^서울$"), ("경기", r"^경기$"),
    ("CBD", r"^서울>도심$"), ("GBD", r"^서울>강남$"), ("YBD", r"^서울>여의도마포$"),
    ("서울 기타", r"^서울>기타$"), ("BBD", r"^경기>분당"),
]


def fetch(statbl):
    rows, page = [], 1
    while True:
        q = dict(KEY=REB_KEY, Type="json", pIndex=page, pSize=1000, STATBL_ID=statbl, DTACYCLE_CD="QY")
        url = API + "?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8"))
        blocks = body.get("SttsApiTblData")
        if not blocks:
            msg = (body.get("RESULT") or {}).get("MESSAGE") or str(body)[:200]
            print("R-ONE", statbl, "응답 없음:", msg, file=sys.stderr)
            break
        got = next((b["row"] for b in blocks if isinstance(b, dict) and "row" in b), [])
        rows += got
        total = int((blocks[0].get("head") or [{}])[0].get("list_total_count") or 0)
        if len(got) < 1000 or len(rows) >= total:
            break
        page += 1
    return rows


def quarter_of(row):
    s = str(row.get("WRTTIME_DESC") or "")
    m = re.search(r"(\d{4})\D*(\d)\s*분기", s)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    s = str(row.get("WRTTIME_IDTFR_ID") or "")
    m = re.match(r"^(\d{4})Q?([1-4])$", s)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = re.match(r"^(\d{4})(\d{2})$", s)          # 202403 → 분기 끝 월
    if m:
        return f"{m.group(1)}Q{(int(m.group(2)) + 2) // 3}"
    return None


def collect(measure):
    by_q = {}
    for statbl in TABLES[measure]:
        try:
            rows = fetch(statbl)
        except Exception as e:
            print("R-ONE", statbl, "실패:", e, file=sys.stderr)
            continue
        n = 0
        for row in rows:
            name = str(row.get("CLS_FULLNM") or row.get("CLS_NM") or "").replace(" ", "")
            zone = next((z for z, pat in ZONES if re.search(pat, name)), None)
            q = quarter_of(row)
            if not zone or not q:
                continue
            try:
                val = float(str(row.get("DTA_VAL")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            by_q.setdefault(q, {"quarter": q})[zone] = round(val, 2)
            n += 1
        print("R-ONE", measure, statbl, "rows", len(rows), "used", n, file=sys.stderr)
    return [by_q[q] for q in sorted(by_q) if q >= "2013Q1"]


def main():
    cache = CACHE / "market.json"
    prev = json.load(open(cache, encoding="utf-8")) if cache.exists() else {}
    if not REB_KEY:
        print("REB_KEY 없음 — 공실률 · 임대료 건너뜀", file=sys.stderr)
        json.dump(prev, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    out = {}
    for m in TABLES:
        series = collect(m)
        out[m] = series or prev.get(m, [])
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("market", {k: (len(v), v[-1] if v else None) for k, v in out.items()})


if __name__ == "__main__":
    main()
