"""JMPSA一覧(JSON) + OSM(Overpass JSON) を統合して data/parking.json を作る。

使い方:
  python3 scripts/build_data.py out/jmpsa*.json --osm out/osm.json --detail out/detail.json -o data/parking.json
  # 再スクレイプせず、既存データから料金の読み取りだけやり直す
  python3 scripts/build_data.py --prev data/parking.json --detail out/detail.json -o data/parking.json

出力は配列の配列（ファイルを軽くするため）。列は COLS の順。
"""
import argparse, json, math, re, glob, datetime, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from price import parse_fee  # noqa: E402

COLS = ["id", "name", "addr", "lat", "lng", "price", "holiday", "src", "op", "url",
        "hours", "upd", "fee"]

RESERVE = re.compile(r"^【予約制(?:：([^】]+))?】")


def compact_fee(f):
    """{"d":..., "c":1, "wd":{...}, "sat":{...}, "hol":{...}} 同じ区分は省略、null/false も省略"""
    def c(x):
        return {k: v for k, v in x.items() if v not in (None, False, 0) or (k in ("h", "m") and v == 0)}
    out = {"wd": c(f["wd"])}
    for k in ("sat", "hol"):
        v = c(f[k])
        if v != out["wd"]:
            out[k] = v
    if f["days"]:
        out["d"] = f["days"]
    if f["cc"]:
        out["c"] = 1
    return out


def dist_m(a, b):
    dy = (a[0] - b[0]) * 111000
    dx = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def load_prev(path):
    d = json.load(open(path, encoding="utf-8"))
    ix = {c: i for i, c in enumerate(d["cols"])}
    rows = []
    for r in d["rows"]:
        g = lambda k: r[ix[k]] if k in ix else ""
        if g("kind") == "reserve":
            continue
        rows.append({"id": g("id"), "name": g("name"), "addr": g("addr"), "lat": g("lat"), "lng": g("lng"),
                     "price": g("price"), "holiday": g("holiday"), "src": g("src"), "op": g("op") or "",
                     "url": g("url"), "hours": g("hours") or "", "upd": g("upd") or ""})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jmpsa", nargs="*", help="scrape_jmpsa.py の出力（glob可）")
    ap.add_argument("--prev", help="既存の data/parking.json から作り直す（再スクレイプしない）")
    ap.add_argument("--osm")
    ap.add_argument("--detail", help="fetch_jmpsa_detail.py の出力（利用可能時間・最終更新日）")
    ap.add_argument("-o", "--out", default="data/parking.json")
    a = ap.parse_args()

    rows, seen = [], set()
    if a.prev:
        rows = load_prev(a.prev)
        seen = {r["id"] for r in rows}
    for pat in a.jmpsa:
        for f in glob.glob(pat):
            for r in json.load(open(f, encoding="utf-8")):
                if ("j" + r["id"]) in seen or not (35.4 < r["lat"] < 35.95 and 138.9 < r["lng"] < 139.95):
                    continue
                if RESERVE.match(r["name"]):
                    continue  # 予約制（akippa・特P など）は載せない
                seen.add("j" + r["id"])
                rows.append({"id": "j" + r["id"], "name": r["name"].strip(), "addr": r["addr"],
                             "lat": round(r["lat"], 6), "lng": round(r["lng"], 6), "price": r["price"],
                             "holiday": r["holiday"], "src": "jmpsa", "op": "", "url": r["url"],
                             "hours": "", "upd": ""})

    added = 0
    if a.osm:
        # JMPSAにない駐車場だけOSMから補う（30m以内に既存があれば重複とみなす）
        rows = [r for r in rows if r["src"] != "osm"]
        grid = {}
        for r in rows:
            grid.setdefault((round(r["lat"], 3), round(r["lng"], 3)), []).append((r["lat"], r["lng"]))
        for e in json.load(open(a.osm, encoding="utf-8"))["elements"]:
            lat = e.get("lat") or e.get("center", {}).get("lat")
            lng = e.get("lon") or e.get("center", {}).get("lon")
            if lat is None:
                continue
            tg = e.get("tags", {})
            if tg.get("access") in ("private", "no", "customers"):
                continue
            k = (round(lat, 3), round(lng, 3))
            near = [p for dy in (-0.001, 0, 0.001) for dx in (-0.001, 0, 0.001)
                    for p in grid.get((round(k[0] + dy, 3), round(k[1] + dx, 3)), [])]
            if any(dist_m((lat, lng), p) < 30 for p in near):
                continue
            fee = tg.get("fee")
            price = {"no": "無料（OSM情報）", "yes": "有料（料金不明）"}.get(fee, "料金不明")
            if tg.get("charge"):
                price += " " + tg["charge"]
            rows.append({"id": "o" + str(e["id"]), "name": tg.get("name") or tg.get("name:ja") or "バイク駐車場（名称不明）",
                         "addr": "", "lat": round(lat, 6), "lng": round(lng, 6), "price": price,
                         "holiday": "", "src": "osm", "op": tg.get("operator", ""),
                         "url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
                         "hours": tg.get("opening_hours", ""), "upd": ""})
            added += 1

    if a.detail and os.path.exists(a.detail):
        det = json.load(open(a.detail, encoding="utf-8"))
        for r in rows:
            d = det.get(r["id"])
            if d:
                r["hours"] = d.get("利用可能時間", "") or r["hours"]
                r["upd"] = d.get("最終更新日", "") or r["upd"]
                if d.get("料金（時間貸）"):
                    r["price"] = d["料金（時間貸）"]

    out_rows = []
    rows = [r for r in rows if not (r["src"] == "jmpsa" and re.fullmatch(r"\s*(-|なし)?\s*", r["price"] or ""))]
    for r in rows:
        price = r["price"]
        if r["src"] == "osm":
            f = parse_fee("無料" if price.startswith("無料") else price.split(" ", 1)[1] if " " in price else "")
        else:
            f = parse_fee(price, r["holiday"])
        r["fee"] = compact_fee(f)
        # 利用可能時間が曜日で違う（管理人の勤務時間の話は除く）
        hz = re.sub(r"[（(]?管理[人員][^）)]*[）)]?|管理[人員].*$", "", r["hours"] or "")
        if re.search(r"月[～~-]土|月[～~-]金|日祝|日・祝|土日祝|土曜|日曜", hz):
            r["fee"]["hn"] = 1
            r["fee"]["d"] = "diff"
        out_rows.append([r[c] for c in COLS])

    out = {"cols": COLS, "built": datetime.date.today().isoformat(), "rows": out_rows}
    with open(a.out, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, separators=(",", ":"))
    hp = sum(1 for r in rows if r["fee"]["wd"].get("h") is not None)
    mp = sum(1 for r in rows if r["fee"]["wd"].get("m") is not None)
    diff = sum(1 for r in rows if "sat" in r["fee"] or "hol" in r["fee"] or "hn" in r["fee"])
    print(f"{len(rows)} lots (osm added {added}), 1h price {hp}, 24h price {mp}, weekday/holiday differ {diff}")


if __name__ == "__main__":
    main()
