"""국토교통부 상업업무용 부동산 실거래가 → 연간 업무시설 거래액(조원) · 건수.

API: 국토교통부_상업업무용 부동산 매매 신고 자료 (getRTMSDataSvcNrgTrade)
  params: serviceKey, LAWD_CD(시군구 5자리), DEAL_YMD(YYYYMM), numOfRows, pageNo
  응답의 건물주용도 필드(buildingUse 등 — 활용가이드 확인)가 '업무시설'인 건만 합산.
매일 전체를 다시 받지 않고, 최근 3개월만 다시 받고 나머지는 캐시(data/cache/deals_raw.json)를 씁니다.

출력: data/cache/deals.json = [{"year":2025,"amount":13.4,"count":138}, ...]
      data/cache/deal_list.json = 10억원 이상 거래 목록(최근순, 최대 3,000건)
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
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()   # KST
    months = []
    y, m = 2019, 1
    while (y, m) <= (today.year, today.month):
        months.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    recent = set(months[-3:])
    sgg_all = load_sigungu()
    sgg = [s for s, _, _ in sgg_all]
    SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
            "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북",
            "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
    names = {s: (SIDO.get(sd, sd[:2]), sg) for s, sd, sg in sgg_all}
    calls, fails, stop = 0, 0, False
    for ym in reversed(months):            # 최근 달부터
        for code in sgg:
            key = f"{code}-{ym}"
            if key in raw and ym not in recent and not (raw[key] and isinstance(raw[key][0], int)):
                continue                       # 옛 형식(금액만 저장)은 상세를 받으러 다시 호출
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
                def num(k):
                    try:
                        return float(str(it.get(k) or "").replace(",", "").strip() or 0) or None
                    except ValueError:
                        return None
                rows.append({
                    "a": int(amt or 0),                                   # 거래금액(만원)
                    "d": f"{it.get('dealYear')}-{int(it.get('dealMonth') or 0):02d}-{int(it.get('dealDay') or 0):02d}",
                    "sgg": code, "jibun": str(it.get("jibun") or "").strip(),
                    "bt": str(it.get("buildingType") or "").strip(), "use": use.strip(),
                    "bar": num("buildingAr"), "par": num("plottageAr"),
                    "fl": str(it.get("floor") or "").strip(), "by": str(it.get("buildYear") or "").strip(),
                    "dg": str(it.get("dealingGbn") or "").strip(), "buyer": str(it.get("buyerGbn") or "").strip(),
                    "seller": str(it.get("slerGbn") or "").strip(), "share": str(it.get("shareDealingType") or "").strip(),
                    "cancel": str(it.get("cdealType") or "").strip(),
                })
            raw[key] = rows
            if calls % 100 == 0:
                json.dump(raw, open(raw_p, "w", encoding="utf-8"))
            time.sleep(0.05)
        if stop:
            break
    json.dump(raw, open(raw_p, "w", encoding="utf-8"))
    agg, deals = {}, []
    amount_of = lambda r: r if isinstance(r, int) else r["a"]
    for key, rows in raw.items():
        yr = int(key.split("-")[1][:4])
        a = agg.setdefault(yr, {"year": yr, "amount": 0, "count": 0, "months": set()})
        live = [r for r in rows if isinstance(r, int) or not r.get("cancel")]      # 해제 신고 건 제외
        a["amount"] += sum(amount_of(r) for r in live); a["count"] += len(live); a["months"].add(key.split("-")[1])
        for r in live:
            if isinstance(r, dict) and r["a"] >= 100000:                           # 10억원 이상만 목록에
                sd, sg = names.get(r["sgg"], ("", r["sgg"]))
                deals.append(dict(r, sido=sd, sigungu=sg))
    deals.sort(key=lambda r: (r["d"], r["a"]), reverse=True)
    json.dump(deals[:3000], open(CACHE / "deal_list.json", "w", encoding="utf-8"), ensure_ascii=False)
    out = [{"year": y, "amount": round(a["amount"] / 1e8, 1), "count": a["count"], "months": len(a["months"])}
           for y, a in sorted(agg.items())]  # 만원 → 조원
    json.dump(out, open(CACHE / "deals.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    done = len(raw); total = len(months) * len(sgg)
    print("deals calls", calls, f"coverage {done}/{total}", out[-3:])


if __name__ == "__main__":
    main()
