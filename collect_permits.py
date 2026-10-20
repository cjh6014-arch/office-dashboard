"""건축HUB 건축인허가정보 → 업무시설 인허가 목록.

국토교통부_건축HUB_건축인허가정보 서비스 (공공데이터포털)
  - getApBasisOulnInfo : 기본개요 (허가일 · 착공일 · 사용승인일 · 연면적 · 주용도)
  - getApFlrOulnInfo   : 층별개요 (층별 용도 · 면적) → 업무시설 비중
파라미터 이름은 포털 '활용가이드'의 최신 명세와 한 번 대조하세요 (PK 체계 변경 이력 있음).

입력: data/bjdong_codes.txt  (행정안전부 법정동코드 전체자료, 탭 구분 — 포털에서 내려받아 넣음)
출력: data/cache/permits.json
"""
import json, os, time, sys, re, zlib, datetime, urllib.parse, urllib.request
from config import *

MAX_CALLS = int(os.environ.get("MAX_CALLS", "1500"))   # 하루 읍면동 호출 수 (트래픽 한도에 맞춰 조정)

BASE = "https://apis.data.go.kr/1613000/ArchPmsHubService"
CENT = json.load(open(ROOT / "scripts" / "centroids.json", encoding="utf-8"))
KOSTAT_SIDO = {"11": "서울", "21": "부산", "22": "대구", "23": "인천", "24": "광주", "25": "대전", "26": "울산", "29": "세종",
               "31": "경기", "32": "강원", "33": "충북", "34": "충남", "35": "전북", "36": "전남", "37": "경북", "38": "경남", "39": "제주"}
CENT_BY_KEY = {}   # (시도 약칭, 시군구명 공백제거) → 대표점
for code, v in CENT.items():
    CENT_BY_KEY[(KOSTAT_SIDO.get(code[:2], ""), v["name"].replace(" ", ""))] = v
    CENT_BY_KEY.setdefault((KOSTAT_SIDO.get(code[:2], ""), v["name"].replace(" ", "")[:3]), v)


def centroid(sido_short, sigungu):
    key = sigungu.replace(" ", "")
    return CENT_BY_KEY.get((sido_short, key)) or CENT_BY_KEY.get((sido_short, key[:3])) \
        or CENT_BY_KEY.get((sido_short, sigungu.split()[0] if sigungu else "")) \
        or CENT_BY_KEY.get((sido_short, sido_short + "시"))


def jitter(pk, lat, lng):
    """같은 시군구 대표점에 여러 건이 겹치지 않게 ID 기반으로 ±0.008도 안에서 살짝 흩뿌림."""
    h = zlib.crc32(str(pk).encode())
    return round(lat + ((h % 1000) / 1000 - 0.5) * 0.016, 5), round(lng + (((h // 1000) % 1000) / 1000 - 0.5) * 0.02, 5)


GEO_BUDGET = int(os.environ.get("GEO_BUDGET", "500"))   # 하루 Kakao 지오코딩 건수


def geocode(addr):
    """Kakao 주소 검색 → (lat, lng). 키 없거나 실패하면 None."""
    if not KAKAO_KEY or not addr:
        return None
    q = addr.replace("번지", "").strip()
    url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode({"query": q, "size": 1})
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents") or []
    except Exception as e:
        print("kakao 실패", q, e, file=sys.stderr)
        return None
    if not docs:
        return None
    return float(docs[0]["y"]), float(docs[0]["x"])


DEBUG_LEFT = 6
LAST_TOTAL = {}
HTTP_CALLS = 0          # 이번 실행의 실제 호출 수
MAX_HTTP = 6000         # 하루 호출 상한(공공데이터포털 일일 한도 안쪽)
MAX_PAGES = 10


def get(op, **params):
    """건축HUB 호출. numOfRows 가 그대로 안 먹는 경우가 있어 totalCount 만큼 pageNo 를 올려 가며 모읍니다."""
    global DEBUG_LEFT, HTTP_CALLS
    out, page, total = [], 1, None
    while page <= MAX_PAGES:
        q = dict(params, serviceKey=DATA_GO_KR_KEY, _type="json", numOfRows=1000, pageNo=page)
        url = f"{BASE}/{op}?" + urllib.parse.urlencode(q)
        body = None
        for attempt in range(3):
            try:
                HTTP_CALLS += 1
                with urllib.request.urlopen(url, timeout=60) as r:
                    text = r.read().decode("utf-8", "replace")
                try:
                    body = json.loads(text)
                except ValueError:
                    if DEBUG_LEFT > 0:
                        DEBUG_LEFT -= 1
                        print("DEBUG non-json", op, params.get("sigunguCd"), text[:300].replace("\n", " "), file=sys.stderr)
                    body = {}
                break
            except Exception as e:  # 네트워크 · 쿼터 초과 등
                print("retry", op, params.get("sigunguCd"), e, file=sys.stderr)
                time.sleep(2 * (attempt + 1))
        if not body:
            break
        head = body.get("response", {}).get("header", {})
        bod = body.get("response", {}).get("body", {})
        items = bod.get("items", {})
        it = (items.get("item", []) if isinstance(items, dict) else []) or []
        it = it if isinstance(it, list) else [it]
        try:
            total = int(bod.get("totalCount") or 0)
        except (TypeError, ValueError):
            total = 0
        if DEBUG_LEFT > 0:
            DEBUG_LEFT -= 1
            print("DEBUG", op, params.get("sigunguCd"), params.get("bjdongCd"), "page", page, "header=", head, "totalCount=", total, "got", len(it),
                  "firstItem=", json.dumps(it[0], ensure_ascii=False)[:600] if it else None, file=sys.stderr)
        out += it
        if not it or len(out) >= total:
            break
        page += 1
    LAST_TOTAL[op] = total
    return out


BJDONG = []   # (sgg, bjdongCd(5), sido, sigungu, dong) — load_sigungu_api 가 채움


def load_sigungu_api():
    """행정안전부_행정표준코드_법정동코드 API(StanReginCd)에서 시군구 · 읍면동 목록. 공공데이터포털 활용신청 필요."""
    out, seen, page = [], set(), 1
    names = {}
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
            if len(code) != 10 or code[2:5] == "000":
                continue
            sgg, parts = code[:5], (it.get("locatadd_nm") or "").split()
            if code[5:] == "00000":
                if sgg in seen:
                    continue
                seen.add(sgg)
                names[sgg] = (parts[0] if parts else "", " ".join(parts[1:]))
                out.append((sgg, parts[0] if parts else "", " ".join(parts[1:])))
            elif code[8:10] == "00" and True:   # 읍 · 면 · 동 (리 제외)
                BJDONG.append([sgg, code[5:10], parts[0] if parts else "", " ".join(parts[1:-1]), parts[-1] if parts else ""])
        page += 1
        if page > 60:
            break
    cache, bcache = CACHE / "sigungu.json", CACHE / "bjdong.json"
    if bcache.exists():                       # API 가 중간에 끊겨 짧게 오면 이전(더 긴) 목록을 쓴다
        old = json.load(open(bcache, encoding="utf-8"))
        if len(old) > len(BJDONG):
            print("읍면동 목록이 이전보다 짧음", len(BJDONG), "<", len(old), "— 이전 목록 사용", file=sys.stderr)
            BJDONG[:] = old
    if out:
        json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(BJDONG, open(bcache, "w", encoding="utf-8"), ensure_ascii=False)
    elif cache.exists():
        out = [tuple(x) for x in json.load(open(cache, encoding="utf-8"))]
        if bcache.exists():
            BJDONG[:] = json.load(open(bcache, encoding="utf-8"))
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


FLR_DEBUG = 3


def office_ratio(sgg, bjd, plat_gb, bun, ji):
    global FLR_DEBUG
    if not bun or bun == "0000":                   # 번지 없는 건은 엉뚱한 건물이 섞여 나와 건너뜀
        return None
    flr = get("getApFlrOulnInfo", sigunguCd=sgg, bjdongCd=bjd, platGbCd=plat_gb, bun=bun, ji=ji)
    if FLR_DEBUG > 0:
        FLR_DEBUG -= 1
        print("DEBUG flr", sgg, bjd, bun, ji, "n=", len(flr), "total=", LAST_TOTAL.get("getApFlrOulnInfo"),
              json.dumps([{k: f.get(k) for k in ("bldNm", "flrNo", "flrGbCdNm", "mainPurpsCd", "mainPurpsCdNm", "flrArea")} for f in flr[:4]], ensure_ascii=False), file=sys.stderr)
    def area(f):
        return float(f.get("flrArea") or f.get("area") or 0)

    def is_office(f):   # 주용도코드 14xxx = 업무시설 계열(일반 · 공공 · 금융업소 등), 이름에 업무 · 사무 포함
        code, nm = str(f.get("mainPurpsCd") or ""), (f.get("mainPurpsCdNm") or "") + (f.get("etcPurps") or "")
        return code.startswith("14") or "업무" in nm or "사무" in nm
    if len(flr) < 2:                               # 층 기록이 1건뿐이면 비중으로 보기 어려워 보류(다음 실행에 재시도)
        return None
    tot = sum(area(f) for f in flr)
    off = sum(area(f) for f in flr if is_office(f))
    return round(off / tot, 2) if tot else None


SIDO_SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
              "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
              "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북",
              "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}


def short_sido(s):
    return SIDO_SHORT.get(s, s[:2])


def floors_of(it):
    try:
        u, g = int(float(it.get("ugrndFlrCnt") or 0)), int(float(it.get("grndFlrCnt") or 0))
    except ValueError:
        return ""
    return f"지하{u}/지상{g}" if (u or g) else ""


def fmt_day(s):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


def main():
    prev = {}
    cache = CACHE / "permits.json"
    if cache.exists():
        prev = {r["id"]: r for r in json.load(open(cache, encoding="utf-8"))}
    rows = dict(prev)
    state_p = CACHE / "scan_state.json"
    state = json.load(open(state_p, encoding="utf-8")) if state_p.exists() else {}
    if state.get("_v") != 2:                      # 수집 방식이 바뀌면 전국을 처음부터 다시 훑음
        state = {"_v": 2}
    seen_purps, n_items, n_calls = {}, 0, 0
    today = datetime.date.today()
    end = today.strftime("%Y%m%d")
    load_sigungu()
    if not BJDONG:
        print("읍면동 목록 없음 — 법정동코드 API 확인", file=sys.stderr)
    # 오래 안 훑은 동부터 MAX_CALLS 개만 (매일 일부씩 순환, 전국 한 바퀴에 며칠)
    todo = sorted(BJDONG, key=lambda b: state.get(f"{b[0]}{b[1]}", ""))[:MAX_CALLS]
    for sgg, bjd, sido, sigungu, dong in todo:
        if HTTP_CALLS >= MAX_HTTP:
            print("호출 상한 도달 — 나머지 동은 다음 실행에", file=sys.stderr)
            break
        # startDate/endDate 는 허가일이 아니라 대장 생성일 기준이라, 허가일은 아래에서 직접 거릅니다
        items = get("getApBasisOulnInfo", sigunguCd=sgg, bjdongCd=bjd, startDate=PERMIT_SINCE, endDate=end)
        n_calls += 1
        n_items += len(items)
        state[f"{sgg}{bjd}"] = today.isoformat()
        for it in items:
            purps = (it.get("mainPurpsCdNm") or "").strip()
            seen_purps[purps] = seen_purps.get(purps, 0) + 1
            if purps not in OFFICE_PURPOSES:
                continue
            if (it.get("archPmsDay") or "").strip() < PERMIT_SINCE:   # 2018년 이전 허가는 제외
                continue
            name = (it.get("bldNm") or "").strip() or f"{sigungu} {dong} 업무시설"
            is_otel = any(t in name for t in EXCLUDE_NAME_TOKENS)
            addr = (it.get("platPlc") or "").strip()
            public = str(it.get("mainPurpsCd") or "").startswith("141") or any(
                k in name for k in ("경찰서", "검찰청", "법원", "청사", "구청", "시청", "군청", "도청", "세무서", "우체국", "소방서", "주민센터", "행정복지센터", "공단", "공사"))
            pk = it.get("mgmPmsrgstPk") or f"{sgg}-{bjd}-{it.get('bun')}-{it.get('ji')}-{it.get('archPmsDay')}"
            old = prev.get(pk, {})
            lat, lng = (old.get("lat"), old.get("lng")) if old.get("geocoded") else (None, None)
            if lat is None:  # 좌표: (1) Kakao 지오코딩 (2) 시군구 대표점
                c = centroid(short_sido(sido), sigungu)
                if c:
                    lat, lng = c["lat"], c["lng"]
            ratio = old.get("office_ratio") if old.get("ratio_n") else None   # 층 1건으로 계산된 옛 값은 다시 계산
            if ratio is None and HTTP_CALLS < MAX_HTTP:
                ratio = office_ratio(sgg, bjd, it.get("platGbCd"), it.get("bun"), it.get("ji"))
                n_calls += 1
            start, comp = fmt_day(it.get("realStcnsDay")), fmt_day(it.get("useAprDay"))
            rows[pk] = {
                "id": pk, "name": name, "kind": (it.get("archGbCdNm") or "신축") + (" · 오피스텔" if is_otel else ""),
                "sido": short_sido(sido),
                "sigungu": sigungu, "sgg_code": sgg, "dong": dong, "zone": zone_of(sido, sigungu, dong),
                "lat": lat, "lng": lng,
                "gfa": int(float(it.get("totArea") or 0)), "office_ratio": ratio, "ratio_n": 2 if ratio is not None else 0,
                "floors": floors_of(it),
                "bjd": bjd, "plat_gb": it.get("platGbCd"), "bun": it.get("bun"), "ji": it.get("ji"),
                "addr": addr, "public": public, "geocoded": old.get("geocoded", False),
                "permit": fmt_day(it.get("archPmsDay")), "start": start, "complete": comp,
                "stage": "준공" if comp else ("공사 중" if start else "착공 전"),
                "exclude": is_otel, "articles": old.get("articles", []),
                "articles_checked": old.get("articles_checked"),
            }
        time.sleep(0.1)
    json.dump(state, open(state_p, "w", encoding="utf-8"))
    geo = GEO_BUDGET
    for r in sorted(rows.values(), key=lambda r: r.get("permit") or "", reverse=True):
        if r.get("geocoded"):
            continue
        if geo > 0 and r.get("addr") and not r.get("exclude"):   # Kakao 지오코딩 (최근 허가부터)
            geo -= 1
            ll = geocode(r["addr"])
            if ll:
                r["lat"], r["lng"], r["geocoded"] = ll[0], ll[1], True
                continue
        c = centroid(r.get("sido", ""), r.get("sigungu", ""))        # 없으면 시군구 대표점 + 흩뿌림
        if c:
            r["lat"], r["lng"] = jitter(r["id"], c["lat"], c["lng"])
    print("지오코딩", sum(1 for r in rows.values() if r.get("geocoded")), "/", len(rows), file=sys.stderr)
    budget = 300                                  # 비중이 비어 있는 기존 건 보충(하루 300건)
    for r in rows.values():
        if budget <= 0:
            break
        if (r.get("office_ratio") is None or not r.get("ratio_n")) and r.get("bjd") and not r.get("exclude"):
            r["office_ratio"] = office_ratio(r["sgg_code"], r["bjd"], r.get("plat_gb"), r.get("bun"), r.get("ji"))
            r["ratio_n"] = 2 if r["office_ratio"] is not None else 0
            budget -= 1
    scanned = sum(1 for b in BJDONG if state.get(f"{b[0]}{b[1]}"))
    print("DEBUG calls", n_calls, "http", HTTP_CALLS, "items", n_items, "purposes", sorted(seen_purps.items(), key=lambda x: -x[1])[:15], file=sys.stderr)
    print(f"읍면동 {scanned}/{len(BJDONG)} 수집됨", file=sys.stderr)
    since = f"{PERMIT_SINCE[:4]}-{PERMIT_SINCE[4:6]}-{PERMIT_SINCE[6:]}"
    out = sorted((r for r in rows.values() if (r.get("permit") or since) >= since), key=lambda r: r["permit"] or "", reverse=True)
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"scanned": scanned, "total": len(BJDONG), "date": today.isoformat()},
              open(CACHE / "coverage.json", "w", encoding="utf-8"))
    print("permits", len(out))


if __name__ == "__main__":
    main()
