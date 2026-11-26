"""JMPSA一覧(JSON) + OSM(Overpass JSON) を統合して data/parking.json を作る。

使い方:
  python3 scripts/build_data.py out/jmpsa*.json --osm out/osm.json -o data/parking.json

出力は配列の配列（ファイルを軽くするため）。列は COLS の順。
"""
import argparse, json, math, re, glob, datetime

COLS = ["id", "name", "addr", "lat", "lng", "price", "holiday", "src", "kind",
        "hour", "max", "op", "url"]

RESERVE = re.compile(r"^【予約制(?:：([^】]+))?】")


def num(s):
    return int(s.replace(",", ""))


def parse_price(t):
    """料金テキスト → (60分あたり円, 1日あたりの最大料金円)。読めなければ None。"""
    if not t:
        return None, None
    z = t.translate(str.maketrans("０１２３４５６７８９，：", "0123456789,:"))
    hour = None
    m = re.search(r"(\d+)\s*分(?:毎|ごと|まで)?\s*(?:[:：]?\s*)?([\d,]+)\s*円", z)
    if m and int(m.group(1)) > 0:
        hour = round(num(m.group(2)) * 60 / int(m.group(1)))
    else:
        m = re.search(r"(\d+)\s*時間(?:毎|ごと)に?\s*([\d,]+)\s*円", z)
        if m and int(m.group(1)) <= 3:
            hour = round(num(m.group(2)) / int(m.group(1)))
    mx = None
    # 特Pなどの時間帯ブロック形式「0:00〜12:00：平日1,600円/12h ...」→ ブロックごとの最高額を合計
    blocks = re.split(r"(?=\d{1,2}:\d{2}\s*[〜~～-]\s*\d{1,2}:\d{2}\s*:)", z)
    bsum = [max(num(v) for v in re.findall(r"([\d,]+)\s*円\s*/\s*\d+\s*h", b))
            for b in blocks if re.search(r"([\d,]+)\s*円\s*/\s*\d+\s*h", b)]
    if len(bsum) >= 1 and re.match(r"\s*\d{1,2}:\d{2}", z):
        return hour, sum(bsum)
    m = re.search(r"([\d,]+)\s*円\s*/\s*(\d+)\s*時間", z)
    if m and hour is None and int(m.group(2)) <= 3:
        hour = round(num(m.group(1)) / int(m.group(2)))
    elif m and int(m.group(2)) >= 4 and not re.search(r"最大|打切|打ち切り", z):
        return hour, num(m.group(1)) * math.ceil(24 / int(m.group(2)))
    m = re.search(r"打ち?切り?\s*([\d,]+)\s*円", z)
    if m:
        return hour, num(m.group(1))
    if hour is None:
        m = re.search(r"(\d+)\s*時間(?:毎|ごと)に?\s*([\d,]+)\s*円", z)
        if m and int(m.group(1)) <= 3:
            hour = round(num(m.group(2)) / int(m.group(1)))
    vals = [num(v) for v in re.findall(r"最大(?:料金)?[^円\n]{0,20}?([\d,]+)\s*円", z)]
    if vals:
        mx = max(vals)  # 平日/休日など複数あるときは高い方（安全側）
    else:
        m = re.search(r"([\d,]+)\s*(?:円|コイン)\s*[～〜~]?\s*/\s*(?:1日|24h|24時間|日)", z) or \
            re.search(r"(?:1日|24時間)\s*([\d,]+)\s*円", z)
        if m:
            mx = num(m.group(1))
        else:
            m = re.search(r"([\d,]+)\s*円\s*/\s*12h", z)
            m2 = re.search(r"(\d+)\s*時間(?:毎|ごと)に?\s*([\d,]+)\s*円", z)
            if m:
                mx = num(m.group(1)) * 2
            elif m2 and int(m2.group(1)) >= 8:
                mx = num(m2.group(2)) * math.ceil(24 / int(m2.group(1)))
    if mx is not None and (mx < 50 or mx > 20000):
        mx = None
    if hour is not None and (hour < 10 or hour > 3000):
        hour = None
    return hour, mx


def kind_of(name):
    m = RESERVE.match(name)
    if m:
        return "reserve", (m.group(1) or "予約制").strip()
    return "time", ""


def dist_m(a, b):
    dy = (a[0] - b[0]) * 111000
    dx = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jmpsa", nargs="+")
    ap.add_argument("--osm")
    ap.add_argument("-o", "--out", default="data/parking.json")
    a = ap.parse_args()

    rows, seen = [], set()
    for pat in a.jmpsa:
        for f in glob.glob(pat):
            for r in json.load(open(f, encoding="utf-8")):
                if r["id"] in seen or not (35.4 < r["lat"] < 35.95 and 138.9 < r["lng"] < 139.95):
                    continue
                seen.add(r["id"])
                hour, mx = parse_price(r["price"])
                kind, op = kind_of(r["name"])
                name = RESERVE.sub("", r["name"]).strip() or r["name"]
                rows.append(["j" + r["id"], name, r["addr"], round(r["lat"], 6), round(r["lng"], 6),
                             r["price"], r["holiday"], "jmpsa", kind, hour, mx, op, r["url"]])

    added = 0
    if a.osm:
        # JMPSAにない駐車場だけOSMから補う（30m以内に既存があれば重複とみなす）
        grid = {}
        for r in rows:
            grid.setdefault((round(r[3], 3), round(r[4], 3)), []).append((r[3], r[4]))
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
            name = tg.get("name") or tg.get("name:ja") or "バイク駐車場（名称不明）"
            hour, mx = parse_price(tg.get("charge", ""))
            if fee == "no":
                hour, mx = 0, 0
            rows.append(["o" + str(e["id"]), name, "", round(lat, 6), round(lng, 6), price,
                         tg.get("opening_hours", ""), "osm", "time", hour, mx, tg.get("operator", ""),
                         f"https://www.openstreetmap.org/{e['type']}/{e['id']}"])
            added += 1

    out = {"cols": COLS, "built": datetime.date.today().isoformat(), "rows": rows}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    priced = sum(1 for r in rows if r[10] is not None)
    print(f"{len(rows)} lots (osm added {added}), max-price parsed {priced}")


if __name__ == "__main__":
    main()
