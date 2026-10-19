"""GitHub Actions 첫 단계: 폴더 구조와 지도 · 샘플 데이터를 만든다.

- scripts/, data/ 폴더를 만들고 루트의 *.py 를 scripts/ 로 복사
- data/map.json (시군구 경계) 와 scripts/centroids.json (시군구 대표점) 을 southkorea-maps 에서 생성
- data/data.json 이 없으면 sample_data.py 로 샘플 생성
"""
import json, os, shutil, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
scripts, data = os.path.join(ROOT, "scripts"), os.path.join(ROOT, "data")
os.makedirs(scripts, exist_ok=True)
os.makedirs(data, exist_ok=True)

for f in os.listdir(ROOT):
    if f.endswith(".py") and f != "prepare.py":
        shutil.copy(os.path.join(ROOT, f), os.path.join(scripts, f))

map_path, cent_path = os.path.join(data, "map.json"), os.path.join(scripts, "centroids.json")
if not (os.path.exists(map_path) and os.path.exists(cent_path)):
    local = os.environ.get("MAP_SOURCE")
    raw = open(local, encoding="utf-8").read() if local else urllib.request.urlopen(SRC, timeout=120).read().decode("utf-8")
    src = json.loads(raw)

    def rnd(c):
        return [round(c[0], 3), round(c[1], 3)] if isinstance(c[0], (int, float)) else [rnd(x) for x in c]

    def pts(c, out):
        if isinstance(c[0], (int, float)):
            out.append(c)
        else:
            for x in c:
                pts(x, out)

    feats, cent = [], {}
    for f in src["features"]:
        p, g = f["properties"], f["geometry"]
        g["coordinates"] = rnd(g["coordinates"])
        ps = []
        pts(g["coordinates"], ps)
        cent[p["code"]] = {"name": p["name"], "lng": round(sum(q[0] for q in ps) / len(ps), 4),
                           "lat": round(sum(q[1] for q in ps) / len(ps), 4)}
        feats.append({"type": "Feature", "properties": {"code": p["code"], "name": p["name"]}, "geometry": g})
    json.dump({"type": "FeatureCollection", "features": feats}, open(map_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump(cent, open(cent_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("map.json / centroids.json 생성", len(feats))

if not os.path.exists(os.path.join(data, "data.json")):
    subprocess.run([sys.executable, "sample_data.py"], cwd=scripts, check=True)
    print("data.json 샘플 생성")
