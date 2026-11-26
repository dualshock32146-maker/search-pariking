"""区のオープンデータ（CC BY）からバイク駐車場の料金を取得して out/opendata.json に保存する。
使い方: python3 scripts/fetch_opendata.py out/opendata.json

対象（2026年11月時点で、バイクの料金が入っているもの）
- 中央区「区営二輪車駐車場一覧」
- 目黒区「自転車等駐輪場一覧」（自治体標準オープンデータセット。一時利用料_自動二輪 がある駐輪場のみ）
- 品川区「民間自転車駐輪場」（バイクの行のみ）
"""
import csv, io, json, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (personal bike-parking map; low rate)"}

SOURCES = {
    "chuo": {
        "label": "中央区オープンデータ「区営二輪車駐車場一覧」",
        "page": "https://catalog.data.metro.tokyo.lg.jp/dataset/t131024d0000000015",
        "csv": "https://www.city.chuo.lg.jp/documents/984/kuei_nirinsha.csv",
    },
    "meguro": {
        "label": "目黒区オープンデータ「自転車等駐輪場一覧」",
        "page": "https://catalog.data.metro.tokyo.lg.jp/dataset/t131105d0000000206",
        "csv": "https://data.bodik.jp/dataset/a53ddc7b-f2e3-4378-a281-9a521d3a8151/resource/"
               "b8ce935e-5cbf-44ec-b418-91b83b3688e1/download/131105_bicycle_park_20240425.csv",
    },
    "shinagawa": {
        "label": "品川区オープンデータ「民間自転車駐輪場」",
        "page": "https://catalog.data.metro.tokyo.lg.jp/dataset/t131091d0000000118",
        "csv": "https://www.opendata.metro.tokyo.lg.jp/shinagawa/minkan_tyurinjo.csv",
    },
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def rows(url):
    b = get(url)
    for enc in ("utf-8-sig", "cp932"):
        try:
            return list(csv.reader(io.StringIO(b.decode(enc))))
        except UnicodeDecodeError:
            pass
    raise ValueError("unknown encoding: " + url)


def geocode(addr):
    """国土地理院 住所検索API"""
    q = urllib.parse.quote(addr)
    js = json.loads(get(f"https://msearch.gsi.go.jp/address-search/AddressSearch?q={q}"))
    time.sleep(0.5)
    if not js:
        return None, None
    lng, lat = js[0]["geometry"]["coordinates"]
    return round(lat, 6), round(lng, 6)


def chuo(src):
    out = []
    head, *body = rows(src["csv"])
    for r in body:
        d = dict(zip(head, r))
        if not d.get("駐車料金") or d["駐車料金"].strip() in ("－", "-", ""):
            continue  # 定期駐車のみ
        addr = "東京都中央区" + re.sub(r"[（(].*", "", d["所在地"]).strip()
        lat, lng = (float(d["緯度"]), float(d["経度"])) if d.get("緯度") else geocode(addr)
        if lat is None:
            continue
        out.append({"key": "chuo:" + d["駐車場名"], "name": d["駐車場名"], "addr": "中央区" + d["所在地"],
                    "lat": lat, "lng": lng, "price": d["駐車料金"].strip(), "hours": d["利用時間"].strip(),
                    "holiday": d.get("休業日", ""), "note": "車両制限：" + d.get("駐車できる二輪車", "")})
    return out


def meguro(src):
    out = []
    head, *body = rows(src["csv"])
    for r in body:
        d = dict(zip(head, r))
        fee = d.get("一時利用料_自動二輪", "").strip()
        if not fee or not d.get("緯度"):
            continue
        free = re.search(r"最初の\S*無料", d.get("備考", ""))
        price = (free.group(0) + "、" if free else "") + fee
        days = d.get("利用可能曜日", "")
        hours = f"{d['開始時間']}～{d['終了時間']}" if d.get("開始時間") else ""
        if days and days != "日月火水木金土":
            hours = f"{days} {hours}"
        out.append({"key": "meguro:" + d["名称"], "name": d["名称"], "addr": d["住所"].replace("東京都", ""),
                    "lat": float(d["緯度"]), "lng": float(d["経度"]), "price": price,
                    "hours": "24時間" if hours == "0:00～23:59" else hours,
                    "holiday": "", "all_days": days == "日月火水木金土",
                    "note": "原付の料金：" + d.get("一時利用料_一般原動機付自転車", "") if d.get("一時利用料_一般原動機付自転車") else ""})
    return out


def shinagawa(src):
    out = []
    head, *body = rows(src["csv"])
    for r in body:
        if len(r) < 8 or r[2] != "バイク" or not r[6]:
            continue
        fee = r[4].strip()
        if not fee or fee == "なし":
            continue
        # 「200円 3時間毎」→「3時間毎200円」（読み取り用。表示は元の文のまま）
        ptext = re.sub(r"^(\d+)円\s*(.*?)(\d+)時間(毎|ごと)", r"\3時間毎\1円 \2", fee)
        out.append({"key": "shinagawa:" + r[0], "name": r[0] + " 駐輪場（バイク）", "addr": "品川区" + r[1],
                    "lat": float(r[6]), "lng": float(r[7]), "price": fee, "ptext": ptext, "hours": "", "holiday": "",
                    "note": "定期利用：" + r[3] + "。区の一覧の「バイク」欄の料金で、原付向けの場合あり。車種は現地で確認を"})
    return out


def main():
    dst = sys.argv[1]
    out = []
    for k, src in SOURCES.items():
        items = globals()[k](src)
        for it in items:
            it.update(srcname=src["label"], srcurl=src["page"])
        print(k, len(items))
        out += items
    json.dump({"fetched": time.strftime("%Y-%m-%d"), "items": out}, open(dst, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
