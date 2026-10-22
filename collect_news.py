"""구글 뉴스 RSS → (1) 최근 오피스 기사 (2) 사업장별 관련 기사 매칭 (3) 제도 · 일정 갱신.

- 매일: 일반 오피스 기사 수집 + 사업장 이름 · 지역으로 관련 기사 매칭(하루 MAX_MATCH 건, 오래된 것부터)
- 매주(월요일 또는 --weekly): 제도 · 일정 갱신
- ANTHROPIC_API_KEY 가 있으면 Claude 로 '같은 사업장인지' · '제도 진행 상태'를 판정하고, 없으면 규칙(이름 · 지역 토큰이 제목에 모두 포함)만 적용

출력: data/cache/news.json, data/cache/policies.json, data/cache/permits.json 의 articles 갱신
"""
import json, os, sys, re, time, datetime, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from config import *

RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
GENERAL_QUERIES = ["오피스 공실률", "오피스 공급 서울", "업무시설 신축 착공", "프라임 오피스 거래", "오피스 임대료"]
POLICY_QUERIES = ["업무시설 용적률 개정", "도심 복합개발 업무시설", "오피스 주거 전환 특례", "국제업무지구 개발계획",
                  "부동산 PF 건전성 상업용", "상업용부동산 임대동향 발표",
                  "국토교통부 업무시설 제도", "서울시 오피스 공급 대책", "업무시설 지구단위계획 변경", "오피스 리츠 세제",
                  "도시계획위원회 업무시설 가결", "공실 오피스 주택 전환 정부"]
POLICY_RECENT = " when:1y"       # 구글뉴스 검색 연산자: 최근 1년
# 키 없이 쓰는 규칙 분류(기사 제목 기준)
POL_MUST = re.compile(r"오피스|업무|상업용|상업지|도심|PF|프라임|리츠|지구단위|도시계획|용적률|공실")
POL_ACT = re.compile(r"대책|개정|시행|발표|승인|고시|입법예고|계획|심의|통과|가결|추진|검토|지정|해제|특례|인센티브|용적률|조례|법안|국회|제도|규제|완화|허용|지원|전환|적용|개편|선정|특별법|보증|의무|공모|결과|정비|늘린다|도입")
POL_FIELD = [("금융·세제", r"PF|대출|세제|세금|금리|리츠|펀드|과세|감면|건전성|보증|HUG"), ("국회", r"국회|법안|개정안|의원|발의"),
             ("통계", r"임대동향|통계|조사 결과|공실률 발표|지가"), ("도시계획", r"용적률|용도|지구단위|도시계획|조례|고시|정비|높이"),
             ("개발사업", r"업무지구|복합개발|착공|승인|사업계획|개발계획|조성|준공|입주")]
POL_STATUS = [("완료", r"시행|통과|가결|확정|고시|승인|완료|체결|개정했|마무리|결정|발표|결과|선정|적용|상장"), ("계류", r"계류|보류|무산|지연|반대|제동|난항|평행선|정해진 바 없"),
              ("예정", r"예정|예고|앞두|내년|연내|검토|추진|계획|전망|나선다|한다$")]


def classify_policies(found):
    """규칙으로 기사 → 제도 · 일정 항목. 제목에 제도 동사와 오피스 키워드가 함께 있어야 함."""
    out, seen = [], set()
    for a in found:
        t = a["title"]
        if not (POL_MUST.search(t) and POL_ACT.search(t)):
            continue
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", t)[:18]
        if key in seen:
            continue
        seen.add(key)
        field = next((f for f, pat in POL_FIELD if re.search(pat, t)), "개발사업")
        status = next((st for st, pat in POL_STATUS if re.search(pat, t)), "진행 중")
        out.append({"date": (a.get("date") or "")[:7], "field": field, "title": t, "status": status,
                    "note": (a.get("source") or "보도") + " · 제목 기준 자동 분류", "source": a.get("url", "")})
    return out


def rss(q, limit=20):
    url = RSS.format(q=urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        src = item.find("source")
        pub = item.findtext("pubDate") or ""
        try:
            d = datetime.datetime.strptime(pub[:16], "%a, %d %b %Y").date().isoformat()
        except Exception:
            d = ""
        out.append({"title": re.sub(r"\s-\s[^-]+$", "", title), "url": item.findtext("link") or "",
                    "date": d, "source": src.text if src is not None else ""})
        if len(out) >= limit:
            break
    return out


def claude(prompt, max_tokens=400):
    """Claude API 한 번 호출(키 없으면 None)."""
    if not ANTHROPIC_KEY:
        return None
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["content"][0]["text"]


def tokens(name):
    """건물명에서 사업자 · 브랜드 · 지명 토큰 (2자 이상 한글 · 영문)."""
    return [t for t in re.findall(r"[가-힣A-Za-z]{2,}", name) if t not in ("업무시설", "신축", "오피스", "빌딩", "사옥", "복합")]


MAX_MATCH = int(os.environ.get("MAX_MATCH", "300"))   # 하루 기사 매칭 사업장 수


def match_articles(permits):
    todo = [p for p in permits if not p.get("exclude")]
    todo.sort(key=lambda p: p.get("articles_checked") or "")      # 한 번도 안 한 것 · 오래된 것부터
    for p in todo[:MAX_MATCH]:
        toks = tokens(p["name"])[:2]
        if not toks:
            p["articles_checked"] = datetime.date.today().isoformat()
            continue
        q = f"{' '.join(toks)} {p['sigungu']} 오피스 OR 업무시설"
        try:
            cands = rss(q, 10)
            time.sleep(0.4)
        except Exception as e:
            print("rss 실패", q, e, file=sys.stderr)
            p["articles_checked"] = datetime.date.today().isoformat()
            continue
        keep = []
        for a in cands:
            t = a["title"]
            if not (("오피스" in t or "업무시설" in t or "사옥" in t) and any(k in t for k in toks)
                    and (((p.get("sigungu") or p.get("sido") or "").split() or [""])[0][:2] in t or (p.get("dong") and p["dong"][:2] in t) or toks[0] in t)):
                continue
            verdict = claude(f"다음 기사 제목이 아래 사업장(신축 · 전환 성격 포함)에 관한 기사인지 '예' 또는 '아니오'로만 답하세요.\n"
                             f"사업장: {p['name']} / {p['sido']} {p['sigungu']} {p['dong']} / 연면적 {p['gfa']}㎡ / 허가 {p['permit']}\n기사 제목: {t}", 5)
            if verdict is None or verdict.strip().startswith("예"):
                keep.append(a)
        p["articles"] = keep[:3]
        p["articles_checked"] = datetime.date.today().isoformat()


def update_policies(prev):
    found = []
    for q in POLICY_QUERIES:
        try:
            found += rss(q + POLICY_RECENT, 8)
        except Exception as e:
            print("policy rss 실패", q, e, file=sys.stderr)
    prev = [p for p in prev if "(예시)" not in p.get("title", "")]     # 샘플 행은 실제 항목이 생기면 제거
    if not ANTHROPIC_KEY:
        new = classify_policies(found)
        seen = {re.sub(r"[^가-힣A-Za-z0-9]", "", p["title"])[:18] for p in prev}
        merged = prev + [n for n in new if re.sub(r"[^가-힣A-Za-z0-9]", "", n["title"])[:18] not in seen]
        return sorted(merged, key=lambda p: p.get("date", ""), reverse=True)[:60]
    text = claude("아래 기사 제목 목록에서 오피스 · 업무시설 개발 · 금융과 관련된 정부 · 국회 · 지자체 제도나 일정만 골라 JSON 배열로 답하세요. "
                  "각 항목은 {\"date\":\"YYYY-MM\",\"field\":\"도시계획|개발사업|금융·세제|국회|통계\",\"title\":\"...\",\"status\":\"완료|진행 중|계류|예정\",\"note\":\"한 줄\",\"source\":\"기사URL\"}. "
                  "확신이 없는 항목은 빼고, JSON 외 다른 글은 쓰지 마세요.\n\n" +
                  "\n".join(f"- {a['date']} {a['title']} {a['url']}" for a in found), 1500)
    if not text:
        return prev
    try:
        new = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
    except Exception:
        return prev
    seen = {p["title"] for p in prev}
    merged = prev + [n for n in new if n.get("title") not in seen]
    return sorted(merged, key=lambda p: p.get("date", ""), reverse=True)[:40]


def main(weekly=False):
    news = []
    for q in GENERAL_QUERIES:
        try:
            news += rss(q, 6)
        except Exception as e:
            print("rss 실패", q, e, file=sys.stderr)
    uniq, seen = [], set()
    for a in sorted(news, key=lambda a: a["date"], reverse=True):
        if a["title"] not in seen:
            seen.add(a["title"]); uniq.append(a)
    json.dump(uniq[:25], open(CACHE / "news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("news", len(uniq))

    pf = CACHE / "permits.json"
    if pf.exists():
        permits = json.load(open(pf, encoding="utf-8"))
        try:
            match_articles(permits)
        except Exception as e:                      # 매칭이 깨져도 제도 · 일정 갱신은 계속
            print("기사 매칭 오류", repr(e), file=sys.stderr)
        json.dump(permits, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("기사 매칭", sum(1 for p in permits if p.get("articles")), "건 연결", file=sys.stderr)

    pp = CACHE / "policies.json"
    cur = json.load(open(pp, encoding="utf-8")) if pp.exists() else []
    kst = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()
    if weekly or kst.weekday() == 0 or not cur or any("(예시)" in p.get("title", "") for p in cur):
        prev = json.load(open(pp, encoding="utf-8")) if pp.exists() else []
        json.dump(update_policies(prev), open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("weekly 갱신 완료")


if __name__ == "__main__":
    main(weekly="--weekly" in sys.argv)
