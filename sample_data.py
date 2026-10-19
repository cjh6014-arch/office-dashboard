"""샘플 data.json 생성기.

API 키가 없는 환경에서 화면을 확인하기 위한 예시 데이터입니다.
실제 운영 시에는 build.py 가 collect_permits.py / collect_vacancy.py /
collect_news.py 결과를 합쳐 같은 구조로 data/data.json 을 씁니다.
"""
import json, random, datetime, pathlib

random.seed(42)
HERE = pathlib.Path(__file__).parent
CENT = json.load(open(HERE / "centroids.json", encoding="utf-8"))

# 시군구코드 → (시도, 권역)
ZONES = {
    "11010": ("서울", "CBD"), "11020": ("서울", "CBD"),          # 종로·중구
    "11030": ("서울", "서울 기타"),                                # 용산
    "11230": ("서울", "GBD"), "11220": ("서울", "GBD"),          # 강남·서초
    "11190": ("서울", "YBD"),                                     # 영등포
    "11040": ("서울", "서울 기타"), "11240": ("서울", "서울 기타"),  # 성동·송파
    "11140": ("서울", "서울 기타"), "11160": ("서울", "서울 기타"),  # 마포·강서
    "11170": ("서울", "서울 기타"),                                 # 구로
    "31023": ("경기", "BBD"),                                     # 성남 분당 → 판교
    "31014": ("경기", "수도권"), "31103": ("경기", "수도권"),      # 수원 영통·고양 일산동
    "31042": ("경기", "수도권"), "23040": ("인천", "수도권"),      # 안양 동안·인천 연수
    "23080": ("인천", "수도권"),                                   # 인천 서구
    "21090": ("부산", "지방"), "22060": ("대구", "지방"),
    "25040": ("대전", "지방"), "29010": ("세종", "지방"),
    "24020": ("광주", "지방"), "26020": ("울산", "지방"),
}
NAMES = {
    "CBD": ["을지로 업무시설 신축", "서소문 복합업무시설", "세운 재정비 업무동", "청계천변 오피스",
            "서울역북부 업무동", "공평 도심정비 오피스"],
    "GBD": ["테헤란로 오피스 신축", "역삼 업무시설", "삼성동 복합업무동", "서초 법조타운 오피스",
            "양재 R&D 업무시설", "논현 사옥 신축"],
    "YBD": ["여의도 복합업무시설", "여의도 금융타워", "영등포 업무시설 신축"],
    "BBD": ["판교 테크 오피스", "분당 업무시설", "판교 제2TV 사옥"],
    "서울 기타": ["성수 지식산업 오피스", "마곡 업무시설", "용산 업무동", "문정 업무시설",
                "구로 디지털 오피스", "상암 미디어 사옥"],
    "수도권": ["광교 업무시설", "송도 국제업무지구 오피스", "일산 업무동", "청라 업무시설", "평촌 오피스"],
    "지방": ["센텀 업무시설", "동대구 오피스", "둔산 업무동", "세종 행정타운 오피스", "광주 상무 업무시설",
            "울산 혁신도시 오피스"],
}
KINDS = ["신축"] * 8 + ["증축", "대수선", "용도변경"]


def d(y, m, day):
    return datetime.date(y, m, day).isoformat()


rows = []
codes = list(ZONES)
for i in range(54):
    code = codes[i % len(codes)] if i < len(codes) else random.choice(codes)
    sido, zone = ZONES[code]
    c = CENT[code]
    name = random.choice(NAMES[zone])
    py = random.choice([2020, 2021, 2022, 2023, 2023, 2024, 2024, 2025, 2025, 2026])
    permit = datetime.date(py, random.randint(1, 12), random.randint(1, 28))
    start = complete = None
    r = random.random()
    if permit < datetime.date(2026, 6, 1) and r > 0.25:
        start = permit + datetime.timedelta(days=random.randint(60, 420))
        if start > datetime.date(2026, 10, 1):
            start = None
    if start and start < datetime.date(2024, 6, 1) and random.random() > 0.35:
        complete = start + datetime.timedelta(days=random.randint(700, 1300))
        if complete > datetime.date(2026, 10, 1):
            complete = None
    gfa = int(random.choice([8000, 15000, 24000, 42000, 65000, 98000, 150000]) * random.uniform(0.6, 1.4))
    if zone in ("CBD", "GBD", "YBD") and random.random() > 0.5:
        gfa = int(gfa * 1.8)
    stage = "준공" if complete else ("공사 중" if start else "착공 전")
    rows.append({
        "id": f"S{i+1:03d}",
        "name": f"{name} (샘플 {i+1:02d})",
        "kind": random.choice(KINDS),
        "sido": sido,
        "sigungu": c["name"],
        "sgg_code": code,
        "dong": "",
        "zone": zone,
        "lat": round(c["lat"] + random.uniform(-0.012, 0.012), 4),
        "lng": round(c["lng"] + random.uniform(-0.012, 0.012), 4),
        "gfa": gfa,
        "office_ratio": round(random.uniform(0.55, 0.98), 2),
        "floors": f"지하{random.randint(3, 8)}/지상{random.randint(8, 42)}",
        "permit": permit.isoformat(),
        "start": start.isoformat() if start else None,
        "complete": complete.isoformat() if complete else None,
        "stage": stage,
        "articles": [],
    })
    if random.random() > 0.6:
        q = f"{name.split()[0]} 오피스"
        rows[-1]["articles"].append({
            "title": f"{name.split()[0]} 일대 업무시설 개발 추진… 연면적 {gfa//1000:,}천㎡ (예시 기사)",
            "url": "https://news.google.com/search?q=" + q,
            "date": (permit + datetime.timedelta(days=random.randint(-30, 200))).isoformat(),
            "source": "예시",
        })

# 공실률 (한국부동산원 상업용부동산 임대동향조사 오피스 공실률 형식, 분기) — 샘플 값
vac = []
base = {"전국": 11.2, "서울": 8.1, "CBD": 10.5, "GBD": 5.4, "YBD": 7.8, "BBD": 3.9}
q = (2019, 1)
while q <= (2026, 2):
    y, n = q
    row = {"quarter": f"{y}Q{n}"}
    for k, b in base.items():
        drift = {"전국": 0.02, "서울": -0.03, "CBD": -0.07, "GBD": -0.02, "YBD": -0.04, "BBD": 0.00}[k]
        t = (y - 2019) * 4 + n
        row[k] = round(b + drift * t + random.uniform(-0.35, 0.35) + (0.8 if y == 2020 else 0), 1)
    vac.append(row)
    q = (y + (n == 4), 1 if n == 4 else n + 1)

# 임대료 (천원/㎡·월, 한국부동산원 기준 형식) — 샘플 값
rent = []
rb = {"전국": 17.1, "서울": 22.3, "CBD": 25.0, "GBD": 24.1, "YBD": 19.0, "BBD": 20.5}
for i, v in enumerate(vac):
    row = {"quarter": v["quarter"]}
    for k, b in rb.items():
        row[k] = round(b * (1 + 0.004 * i) + random.uniform(-0.15, 0.15), 1)
    rent.append(row)

# 거래 (연간, 조원·건) — 샘플
deals = [{"year": y, "amount": a, "count": c} for y, a, c in
         [(2019, 12.8, 160), (2020, 13.1, 150), (2021, 18.7, 190), (2022, 15.2, 140),
          (2023, 9.6, 110), (2024, 11.9, 125), (2025, 13.4, 138), (2026, 7.1, 70)]]

policies = [
    {"date": "2026-09", "field": "도시계획", "title": "서울시 도심 업무시설 용적률 인센티브 운영기준 개정 (예시)", "status": "완료",
     "note": "업무시설 비중에 따라 용적률 가산 적용", "source": "https://news.google.com/search?q=서울시+업무시설+용적률"},
    {"date": "2026-08", "field": "개발사업", "title": "용산국제업무지구 실시계획 (예시)", "status": "진행 중",
     "note": "업무시설 중심 복합개발 단계별 착공", "source": "https://news.google.com/search?q=용산국제업무지구"},
    {"date": "2026-07", "field": "금융·세제", "title": "상업용 부동산 PF 건전성 관리 방안 (예시)", "status": "진행 중",
     "note": "브릿지론·본PF 전환 기준 강화", "source": "https://news.google.com/search?q=부동산PF+건전성"},
    {"date": "2026-06", "field": "국회", "title": "도시 및 주거환경정비법 개정안 — 도심 업무시설 전환 (예시)", "status": "계류",
     "note": "노후 오피스의 주거 전환 특례", "source": "https://news.google.com/search?q=오피스+주거전환+개정안"},
    {"date": "2026-11", "field": "통계", "title": "한국부동산원 3분기 상업용부동산 임대동향 발표 (예정)", "status": "예정",
     "note": "오피스 공실률·임대가격지수", "source": "https://www.reb.or.kr/"},
]

news = [
    {"date": "2026-10-13", "title": "서울 주요 권역 오피스 공실률 추이 (예시 기사)", "url": "https://news.google.com/search?q=서울+오피스+공실률", "source": "예시"},
    {"date": "2026-10-10", "title": "프라임 오피스 신규 공급 전망 (예시 기사)", "url": "https://news.google.com/search?q=프라임+오피스+공급", "source": "예시"},
    {"date": "2026-10-08", "title": "도심 노후 오피스 리모델링·용도전환 동향 (예시 기사)", "url": "https://news.google.com/search?q=오피스+용도전환", "source": "예시"},
]

out = {
    "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "sample": True,
    "permits": sorted(rows, key=lambda r: r["permit"], reverse=True),
    "vacancy": vac,
    "rent": rent,
    "deals": deals,
    "policies": policies,
    "news": news,
}
json.dump(out, open(HERE.parent / "data" / "data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("permits", len(rows), "vacancy", len(vac))
