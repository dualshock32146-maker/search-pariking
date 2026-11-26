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
        "hours", "upd", "fee", "alt"]

GENERIC = re.compile(r"駐輪場|駐車場|自転車等?|二輪車|自動二輪|バイク|オートバイ|区営|区立|目黒区|中央区|品川区|"
                     r"地下|駅|東急|JR|ＪＲ|エコステーション21|パーキング|[（）()\s　・]|No\.\d+")


def lcs(a, b):
    """共通部分文字列の最大長"""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def same_place(od, r):
    a, b = GENERIC.sub("", od["name"]), GENERIC.sub("", r["name"])
    d = dist_m((od["lat"], od["lng"]), (r["lat"], r["lng"]))
    # 名前の大部分が一致し（「武蔵小山西口」と「武蔵小山ビルA」は別扱い）、近くにある
    return d <= 400 and min(len(a), len(b)) >= 3 and lcs(a, b) / max(len(a), len(b)) >= 0.75

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
        if g("kind") == "reserve" or g("src") == "od":
            continue  # 区データの行は毎回 out/opendata.json から作り直す
        alt = g("alt") or {}
        if alt.get("jp") is not None:  # 区データで上書きしていたJMPSAの行は元に戻す
            r = list(r)
            for k, v in (("price", alt["jp"]), ("name", alt["jn"]), ("hours", alt["jh"]), ("upd", alt["ju"])):
                r[ix[k]] = v
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
    ap.add_argument("--opendata", help="fetch_opendata.py の出力（区のオープンデータ）")
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

    for r in rows:
        r.setdefault("alt", {})
        r.setdefault("ptext", None)
    od_added = od_merged = 0
    if a.opendata and os.path.exists(a.opendata):
        # 区のオープンデータ：同じ駐車場がJMPSAにあれば区データの料金を優先（JMPSAの掲載は古いものが多い）
        od = json.load(open(a.opendata, encoding="utf-8"))
        for it in od["items"]:
            alt = {"sn": it["srcname"], "su": it["srcurl"], "sd": od["fetched"]}
            if it.get("note"):
                alt["note"] = it["note"]
            hits = [r for r in rows if r["src"] == "jmpsa" and not r["alt"].get("hid") and same_place(it, r)]
            hits.sort(key=lambda r: dist_m((it["lat"], it["lng"]), (r["lat"], r["lng"])))
            if hits:
                r = hits[0]
                r["alt"] = dict(alt, jp=r["price"], jn=r["name"], jh=r["hours"], ju=r["upd"])
                r.update(price=it["price"], ptext=it.get("ptext"), hours=it["hours"] or r["hours"], upd="")
                if it.get("all_days"):
                    r["alldays"] = True
                for dup in hits[1:]:
                    if dist_m((dup["lat"], dup["lng"]), (r["lat"], r["lng"])) < 60:
                        dup["alt"] = {"hid": 1, "by": r["id"]}  # JMPSA内の重複
                od_merged += 1
            else:
                rows.append({"id": "d" + it["key"], "name": it["name"], "addr": it["addr"], "lat": it["lat"],
                             "lng": it["lng"], "price": it["price"], "ptext": it.get("ptext"),
                             "holiday": it["holiday"], "src": "od", "op": "", "url": it["srcurl"],
                             "hours": it["hours"], "upd": "", "alt": alt, "alldays": it.get("all_days")})
                od_added += 1

    out_rows = []
    rows = [r for r in rows if not (r["src"] == "jmpsa" and re.fullmatch(r"\s*(-|なし)?\s*", r["price"] or ""))
            and not r["alt"].get("hid")]
    for r in rows:
        price = r["price"]
        if r.get("ptext"):
            f = parse_fee(r["ptext"], r["holiday"])
        elif r["src"] == "osm":
            f = parse_fee("無料" if price.startswith("無料") else price.split(" ", 1)[1] if " " in price else "")
        else:
            f = parse_fee(price, r["holiday"])
        if r.get("alldays") and f["days"] == "":
            f["days"] = "all"
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
    print(f"opendata: merged {od_merged}, added {od_added}")
    print(f"{len(rows)} lots (osm added {added}), 1h price {hp}, 24h price {mp}, weekday/holiday differ {diff}")


if __name__ == "__main__":
    main()
