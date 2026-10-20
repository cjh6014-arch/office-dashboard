"""캐시(원천 수집 결과)를 합쳐 data/data.json 을 만듭니다.

어느 한 원천이 비어 있으면 그 부분만 이전 data.json 값을 유지합니다.
모든 원천이 비어 있으면(키 미설정 등) sample_data.py 결과를 그대로 둡니다.
"""
import json, datetime, sys
from config import *

OUT = DATA / "data.json"


def load(name, default):
    p = CACHE / name
    try:
        return json.load(open(p, encoding="utf-8")) if p.exists() else default
    except Exception as e:
        print("cache 읽기 실패", name, e, file=sys.stderr)
        return default


def main():
    prev = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {}
    permits, seen = [], set()
    for r in load("permits.json", []):            # 같은 자리 · 같은 연면적의 반복 허가(용도변경 재신청 등)는 최신 1건만
        key = (r.get("addr") or r.get("name"), r.get("gfa"), r.get("kind"))
        if r.get("exclude") or key in seen:
            continue
        seen.add(key)
        permits.append(r)
    market = load("market.json", {})
    news = load("news.json", [])
    policies = load("policies.json", [])
    deals = load("deals.json", [])
    coverage = load("coverage.json", {})

    real = bool(permits or market.get("vacancy"))
    if not real:
        print("실데이터 없음 — 샘플 유지", file=sys.stderr)
        return
    out = {
        "updated": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        "sample": False,
        "coverage": coverage,
        "owner": OWNER or prev.get("owner", ""),
        "permits": permits or prev.get("permits", []),
        "vacancy": market.get("vacancy") or prev.get("vacancy", []),
        "rent": market.get("rent") or prev.get("rent", []),
        "deals": deals or prev.get("deals", []),
        "policies": policies or prev.get("policies", []),
        "news": news or prev.get("news", []),
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("data.json", {k: (len(v) if isinstance(v, list) else v) for k, v in out.items()})


if __name__ == "__main__":
    main()
