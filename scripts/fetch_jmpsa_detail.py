"""JMPSA 詳細ページから 利用可能時間・最終更新日 などを取得する（時間貸のみ）。
使い方: python3 scripts/fetch_jmpsa_detail.py data/parking.json out/detail.json
既存の out/detail.json があれば取得済みIDは飛ばす。
"""
import sys, json, os, re, html, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (personal bike-parking map; low rate)"}
CELL = re.compile(r'table-ttl">(.*?)</th>\s*<td[^>]*>(.*?)</td>', re.S)


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", s))).strip()


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = json.load(open(src, encoding="utf-8"))
    ix = {c: i for i, c in enumerate(d["cols"])}
    out = json.load(open(dst, encoding="utf-8")) if os.path.exists(dst) else {}
    todo = [r for r in d["rows"] if r[ix["src"]] == "jmpsa" and r[ix["id"]] not in out
            and r[ix.get("kind", 0)] != "reserve"]
    for n, r in enumerate(todo):
        try:
            with urllib.request.urlopen(urllib.request.Request(r[ix["url"]], headers=UA), timeout=30) as f:
                body = f.read().decode("utf-8", "replace")
            out[r[ix["id"]]] = {clean(k): clean(v) for k, v in CELL.findall(body)}
        except Exception as e:
            print("fail", r[ix["id"]], e, flush=True)
        if n % 50 == 0:
            print(n, len(todo), flush=True)
            json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.4)
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
    print("done", len(out))


if __name__ == "__main__":
    main()
