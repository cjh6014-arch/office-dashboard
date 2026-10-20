"""국토교통부 상업업무용 부동산 실거래가 → 연간 업무시설 거래액(조원) · 건수.

API: 국토교통부_상업업무용 부동산 매매 신고 자료 (getRTMSDataSvcNrgTrade)
  params: serviceKey, LAWD_CD(시군구 5자리), DEAL_YMD(YYYYMM), numOfRows, pageNo
  응답의 건물주용도 필드(buildingUse 등 — 활용가이드 확인)가 '업무시설'인 건만 합산.
매일 전체를 다시 받지 않고, 최근 3개월만 다시 받고 나머지는 캐시(data/cache/deals_raw.json)를 씁니다.

출력: data/cache/deals.json = [{"year":2025,"amount":13.4,"count":138}, ...]
"""
import json, os, sys, time, datetime, urllib.parse, urllib.request
from config import *
from collect_permits import load_sigungu

BASE = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"


def fetch(lawd, ym):
    q = dict(serviceKey=DATA_GO_KR_KEY, LAWD_CD=lawd, DEAL_YMD=ym, numOfRows=1000, pageNo=1, _type="json")
    with urllib.request.urlopen(BASE + "?" + urllib.parse.urlencode(q), timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
    items = body.get("response", {}).get("body", {}).get("items", {}) or {}
    it = items.get("item", [])
    it = it if isinstance(it, list) else [it]
    global DEBUG_LEFT
    if it and DEBUG_LEFT > 0:
        DEBUG_LEFT -= 1
        print("DEBUG deals firstItem", json.dumps(it[0], ensure_ascii=False)[:400], file=sys.stderr)
    return it


DEBUG_LEFT = 2


MAX_DEAL_CALLS = int(os.environ.get("MAX_DEAL_CALLS", "1200"))   # 하루 호출 수 (최근 달부터 채움)


def main():
    raw_p = CACHE / "deals_raw.json"
    raw = json.load(open(raw_p, encoding="utf-8")) if raw_p.exists() else {}
    today = datetime.date.today()
    months = []
    y, m = 2019, 1
    while (y, m) <= (today.year, today.month):
        months.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    recent = set(months[-3:])
    sgg = [s for s, _, _ in load_sigungu()]
    calls, fails, stop = 0, 0, False
    for ym in reversed(months):            # 최근 달부터
        for code in sgg:
            key = f"{code}-{ym}"
            if key in raw and ym not in recent:
                continue
            if calls >= MAX_DEAL_CALLS:
                stop = True
                break
            try:
                items = fetch(code, ym)
                calls += 1
                fails = 0
            except Exception as e:
                calls += 1
                fails += 1
                print("deals 실패", key, e, file=sys.stderr)
                if "403" in str(e) or fails >= 20:
                    print("실거래가 API 사용 불가(활용신청 확인) — 거래 수집 중단", file=sys.stderr)
                    stop = True
                    break
                continue
            rows = []
            for it in items:
                use = str(it.get("buildingUse") or it.get("건물주용도") or "")
                if "업무" not in use:
                    continue
                amt = str(it.get("dealAmount") or it.get("거래금액") or "0").replace(",", "").strip()
                rows.append(int(amt or 0))
            raw[key] = rows
            if calls % 100 == 0:
                json.dump(raw, open(raw_p, "w", encoding="utf-8"))
            time.sleep(0.05)
        if stop:
            break
    json.dump(raw, open(raw_p, "w", encoding="utf-8"))
    agg = {}
    for key, rows in raw.items():
        yr = int(key.split("-")[1][:4])
        a = agg.setdefault(yr, {"year": yr, "amount": 0, "count": 0, "months": set()})
        a["amount"] += sum(rows); a["count"] += len(rows); a["months"].add(key.split("-")[1])
    out = [{"year": y, "amount": round(a["amount"] / 1e8, 1), "count": a["count"], "months": len(a["months"])}
           for y, a in sorted(agg.items())]  # 만원 → 조원
    json.dump(out, open(CACHE / "deals.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    done = len(raw); total = len(months) * len(sgg)
    print("deals calls", calls, f"coverage {done}/{total}", out[-3:])


if __name__ == "__main__":
    main()
