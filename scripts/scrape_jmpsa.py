"""JMPSA 全国バイク駐車場案内（東京都）の一覧を区市ごとに取得してJSONに保存する。
使い方: python3 scrape_jmpsa.py counts.txt out.json
counts.txt: "区市名 件数" の行
"""
import sys, json, time, re, html, urllib.parse, urllib.request

BASE = "https://www.jmpsa.or.jp"
UA = {"User-Agent": "Mozilla/5.0 (personal bike-parking map; low rate)"}

ITEM = re.compile(
    r'q=([\d.]+),([\d.]+).*?href="(/society/parking/area13/p-(\d+)\.html)"[^>]*>(.*?)<span'
    r'.*?map-txt">(.*?)</p>(.*?)</li>', re.S)
CELL = re.compile(r'table-ttl">(.*?)</p>\s*<p class="p-parking-prefecture-table-txt">(.*?)</p>', re.S)

def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            time.sleep(2 + i * 3)
    return ""

def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def main():
    counts = [l.rsplit(" ", 1) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    out = {}
    for sect, c in counts:
        c = int(c or 0)
        if not c:
            continue
        pages = (c + 9) // 10
        for off in range(pages):
            q = urllib.parse.urlencode({"id": 13, "types": 1, "offset": off, "vs": "1,1,1,0",
                                        "sect": sect, "locations": "", "search": ""})
            body = get(f"{BASE}/assets/module/maplist.php?{q}")
            for m in ITEM.finditer(body):
                lat, lng, href, pid, name, addr, rest = m.groups()
                cells = {clean(k): clean(v) for k, v in CELL.findall(rest)}
                out[pid] = {"id": pid, "name": clean(name), "addr": clean(addr), "sect": sect,
                            "lat": float(lat), "lng": float(lng),
                            "holiday": cells.get("定休日", ""), "price": cells.get("料金", ""),
                            "url": BASE + href}
            time.sleep(0.25)
        print(sect, c, len(out), flush=True)
    json.dump(list(out.values()), open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)

if __name__ == "__main__":
    main()
