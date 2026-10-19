"""구글 뉴스 RSS → (1) 최근 오피스 기사 (2) 사업장별 관련 기사 매칭 (3) 제도 · 일정 갱신.

- 매일: 일반 오피스 기사 수집
- 매주(월요일 또는 --weekly): 사업장 이름 + 지역으로 재검색해 관련 기사 연결, 제도 · 일정 갱신
- ANTHROPIC_API_KEY 가 있으면 Claude 로 '같은 사업장인지' · '제도 진행 상태'를 판정하고, 없으면 규칙(이름 · 지역 토큰이 제목에 모두 포함)만 적용

출력: data/cache/news.json, data/cache/policies.json, data/cache/permits.json 의 articles 갱신
"""
import json, sys, re, datetime, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from config import *

RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
GENERAL_QUERIES = ["오피스 공실률", "오피스 공급 서울", "업무시설 신축 착공", "프라임 오피스 거래", "오피스 임대료"]
POLICY_QUERIES = ["업무시설 용적률 개정", "도심 복합개발 업무시설", "오피스 주거 전환 특례", "국제업무지구 개발계획",
                  "부동산 PF 건전성 상업용", "상업용부동산 임대동향 발표"]


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


def match_articles(permits):
    for p in permits:
        if p.get("articles_checked") and (datetime.date.today() - datetime.date.fromisoformat(p["articles_checked"])).days < 7:
            continue
        toks = tokens(p["name"])[:2]
        if not toks:
            p["articles_checked"] = datetime.date.today().isoformat()
            continue
        q = f"{' '.join(toks)} {p['sigungu']} 오피스 OR 업무시설"
        try:
            cands = rss(q, 10)
        except Exception as e:
            print("rss 실패", q, e, file=sys.stderr)
            continue
        keep = []
        for a in cands:
            t = a["title"]
            if not (("오피스" in t or "업무시설" in t or "사옥" in t) and any(k in t for k in toks)
                    and (p["sigungu"].split()[0][:2] in t or (p["dong"] and p["dong"][:2] in t) or toks[0] in t)):
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
            found += rss(q, 8)
        except Exception as e:
            print("policy rss 실패", q, e, file=sys.stderr)
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

    if weekly or datetime.date.today().weekday() == 0:
        pf = CACHE / "permits.json"
        if pf.exists():
            permits = json.load(open(pf, encoding="utf-8"))
            match_articles(permits)
            json.dump(permits, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        pp = CACHE / "policies.json"
        prev = json.load(open(pp, encoding="utf-8")) if pp.exists() else []
        json.dump(update_policies(prev), open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("weekly 갱신 완료")


if __name__ == "__main__":
    main(weekly="--weekly" in sys.argv)
