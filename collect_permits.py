"""건축HUB 건축인허가정보 → 업무시설 인허가 목록.

국토교통부_건축HUB_건축인허가정보 서비스 (공공데이터포털)
  - getApBasisOulnInfo : 기본개요 (허가일 · 착공일 · 사용승인일 · 연면적 · 주용도)
  - getApFlrOulnInfo   : 층별개요 (층별 용도 · 면적) → 업무시설 비중
파라미터 이름은 포털 '활용가이드'의 최신 명세와 한 번 대조하세요 (PK 체계 변경 이력 있음).

입력: data/bjdong_codes.txt  (행정안전부 법정동코드 전체자료, 탭 구분 — 포털에서 내려받아 넣음)
출력: data/cache/permits.json
"""
import json, time, sys, re, datetime, urllib.parse, urllib.request
from config import *

BASE = "https://apis.data.go.kr/1613000/ArchPmsHubService"
CENT = json.load(open(ROOT / "scripts" / "centroids.json", encoding="utf-8"))
CENT_BY_NAME = {v["name"]: v for v in CENT.values()}


DEBUG_LEFT = 3


def get(op, **params):
    global DEBUG_LEFT
    params.update(serviceKey=DATA_GO_KR_KEY, _type="json", numOfRows=1000)
    url = f"{BASE}/{op}?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
            try:
                body = json.loads(text)
            except ValueError:
                if DEBUG_LEFT > 0:
                    DEBUG_LEFT -= 1
                    print("DEBUG non-json", op, params.get("sigunguCd"), text[:300].replace("\n", " "), file=sys.stderr)
                return []
            head = body.get("response", {}).get("header", {})
            bod = body.get("response", {}).get("body", {})
            items = bod.get("items", {})
            if DEBUG_LEFT > 0:
                DEBUG_LEFT -= 1
                first = (items.get("item") if isinstance(items, dict) else None) or []
                first = first[0] if isinstance(first, list) and first else first
                print("DEBUG", op, params.get("sigunguCd"), "header=", head, "totalCount=", bod.get("totalCount"),
                      "firstItem=", json.dumps(first, ensure_ascii=False)[:400] if first else None, file=sys.stderr)
            if not items or not isinstance(items, dict):
                return []
            it = items.get("item", [])
            return it if isinstance(it, list) else [it]
        except Exception as e:  # 네트워크 · 쿼터 초과 등
            print("retry", op, params.get("sigunguCd"), e, file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return []


def load_sigungu_api():
    """행정안전부_행정표준코드_법정동코드 API(StanReginCd)에서 시군구 목록. 공공데이터포털 활용신청 필요."""
    out, seen, page = [], set(), 1
    while True:
        q = dict(ServiceKey=DATA_GO_KR_KEY, pageNo=page, numOfRows=1000, type="json", flag="Y")
        url = "https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("법정동코드 API 실패", page, e, file=sys.stderr)
            break
        blocks = body.get("StanReginCd") or []
        rows = next((b["row"] for b in blocks if isinstance(b, dict) and "row" in b), [])
        if not rows:
            break
        for it in rows:
            code = str(it.get("region_cd", ""))
            if len(code) == 10 and code[5:] == "00000" and code[2:5] != "000":
                sgg = code[:5]
                if sgg in seen:
                    continue
                seen.add(sgg)
                parts = (it.get("locatadd_nm") or "").split()
                out.append((sgg, parts[0] if parts else "", " ".join(parts[1:])))
        page += 1
        if page > 60:
            break
    cache = CACHE / "sigungu.json"
    if out:
        json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    elif cache.exists():
        out = [tuple(x) for x in json.load(open(cache, encoding="utf-8"))]
    return out


def load_sigungu():
    """법정동코드 파일에서 (시군구코드, 시도명, 시군구명) 목록. 파일이 없으면 API 로 대체."""
    path = DATA / "bjdong_codes.txt"
    if not path.exists():
        out = load_sigungu_api()
        print("법정동코드 API 시군구", len(out), file=sys.stderr)
        return out
    out, seen = [], set()
    for line in open(path, encoding="cp949", errors="ignore"):
        code, name, *rest = line.rstrip("\n").split("\t")
        if not code.isdigit() or (rest and rest[0] != "존재"):
            continue
        sgg = code[:5]
        if code[5:] == "00000" and code[2:5] != "000" and sgg not in seen:
            parts = name.split()
            seen.add(sgg)
            out.append((sgg, parts[0], " ".join(parts[1:])))
    return out


def zone_of(sido, sigungu, dong):
    if sido.startswith("서울"):
        return ZONE_BY_SIGUNGU.get(sigungu.split()[-1], "서울 기타")
    if sido.startswith("경기") and any(t in sigungu + dong for t in BBD_DONGS):
        return "BBD"
    return "수도권" if sido in METRO_SIDO else "지방"


def office_ratio(sgg, bjd, plat_gb, bun, ji):
    flr = get("getApFlrOulnInfo", sigunguCd=sgg, bjdongCd=bjd, platGbCd=plat_gb, bun=bun, ji=ji)
    tot = sum(float(f.get("area") or 0) for f in flr)
    off = sum(float(f.get("area") or 0) for f in flr if (f.get("mainPurpsCdNm") or "") in OFFICE_PURPOSES
              or "업무" in (f.get("etcPurps") or ""))
    return round(off / tot, 2) if tot else None


SIDO_SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
              "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
              "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북",
              "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}


def short_sido(s):
    return SIDO_SHORT.get(s, s[:2])


def fmt_day(s):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


def main():
    prev = {}
    cache = CACHE / "permits.json"
    if cache.exists():
        prev = {r["id"]: r for r in json.load(open(cache, encoding="utf-8"))}
    rows = {}
    seen_purps, n_items = {}, 0
    end = datetime.date.today().strftime("%Y%m%d")
    for sgg, sido, sigungu in load_sigungu():
        items = get("getApBasisOulnInfo", sigunguCd=sgg, bjdongCd="", startDate=PERMIT_SINCE, endDate=end)
        n_items += len(items)
        for it in items:
            purps = (it.get("mainPurpsCdNm") or "").strip()
            seen_purps[purps] = seen_purps.get(purps, 0) + 1
            name = (it.get("bldNm") or "").strip() or f"{it.get('platPlc','')} 업무시설"
            if purps not in OFFICE_PURPOSES:
                continue
            is_otel = any(t in name for t in EXCLUDE_NAME_TOKENS)
            pk = it.get("mgmPmsrgstPk") or f"{sgg}-{it.get('bjdongCd')}-{it.get('bun')}-{it.get('ji')}-{it.get('archPmsDay')}"
            plat = it.get("platPlc", "")
            dong = re.sub(r".*?(\S+동|\S+리|\S+가)\b.*", r"\1", plat) if plat else ""
            old = prev.get(pk, {})
            lat, lng = old.get("lat"), old.get("lng")
            if lat is None:  # 좌표: (1) Kakao 지오코딩 (2) 시군구 대표점
                c = CENT_BY_NAME.get(sigungu.split()[0]) or CENT_BY_NAME.get(sigungu.replace(" ", ""))
                if c:
                    lat, lng = c["lat"], c["lng"]
            ratio = old.get("office_ratio")
            if ratio is None:
                ratio = office_ratio(sgg, it.get("bjdongCd"), it.get("platGbCd"), it.get("bun"), it.get("ji"))
            start, comp = fmt_day(it.get("realStcnsDay")), fmt_day(it.get("useAprDay"))
            rows[pk] = {
                "id": pk, "name": name, "kind": (it.get("archGbCdNm") or "신축") + (" · 오피스텔" if is_otel else ""),
                "sido": short_sido(sido),
                "sigungu": sigungu, "sgg_code": sgg, "dong": dong, "zone": zone_of(sido, sigungu, dong),
                "lat": lat, "lng": lng,
                "gfa": int(float(it.get("totArea") or 0)), "office_ratio": ratio,
                "floors": f"지하{it.get('ugrndFlrCnt','0')}/지상{it.get('grndFlrCnt','0')}",
                "permit": fmt_day(it.get("archPmsDay")), "start": start, "complete": comp,
                "stage": "준공" if comp else ("공사 중" if start else "착공 전"),
                "exclude": is_otel, "articles": old.get("articles", []),
                "articles_checked": old.get("articles_checked"),
            }
        time.sleep(0.2)
    print("DEBUG items total", n_items, "purposes", sorted(seen_purps.items(), key=lambda x: -x[1])[:20], file=sys.stderr)
    if not rows and prev:
        print("수집 결과 없음 — 이전 캐시 유지", file=sys.stderr)
        rows = prev
    out = sorted(rows.values(), key=lambda r: r["permit"] or "", reverse=True)
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("permits", len(out))


if __name__ == "__main__":
    main()
