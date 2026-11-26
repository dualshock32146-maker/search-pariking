"""駐車料金テキストの読み取り。

parse_fee(料金テキスト, 定休日テキスト) → 曜日区分ごとの料金
  {"days": "all"|"diff"|"",          # all=全日同一と明記 / diff=曜日で違う / ""=曜日の記載なし
   "cc": bool,                         # 車種(排気量)で料金が違う（高い方を採用）
   "wd": Fee, "sat": Fee, "hol": Fee}  # 平日(月〜金) / 土曜 / 日曜・祝日
Fee = {"h": 1時間停めた料金, "u": 基本単位の表記, "m": 24時間停めた料金(上限), "nc": 上限なし, "f": 無料分数, "x": 休業}
値が読めない項目は None。
"""
import math
import re

from price_overrides import OVERRIDES

TR = str.maketrans("０１２３４５６７８９，：／～〜　（）￥＜＞【】", "0123456789,:/~~ ()¥<>[]")


def norm(t):
    z = (t or "").translate(TR).replace("\xa0", " ").replace("㏄", "cc").replace("コイン", "円")
    z = z.replace("－", "-").replace("―", "-").replace("→", " ").replace("…", " ")
    z = re.sub(r"¥\s*([\d,]+)", r"\1円", z)
    z = re.sub(r"(\d)\.(\d{3})円", r"\1\2円", z)
    z = re.sub(r"(\d),(\d{3})", r"\1\2", z)
    z = re.sub(r"(\d+)\s+円", r"\1円", z)
    z = re.sub(r"(\d+)時間半", lambda m: f"{int(m.group(1)) * 60 + 30}分", z)
    z = re.sub(r"(\d+)時間(\d+)分", lambda m: f"{int(m.group(1)) * 60 + int(m.group(2))}分", z)
    z = re.sub(r"(\d+)\s*h(?![a-zA-Z])", r"\1時間", z)
    return z


def mins(n, u):
    n = float(n)
    return int(n * 60) if u in ("時間", "h") else int(n)


def unit_str(p, u):
    if u % 60 == 0:
        return f"{p:,}円/{u // 60}時間" if u != 60 else f"{p:,}円/1時間"
    return f"{p:,}円/{u}分"


# 料金の時間単位（P円/U分）。位置つきで全部拾う
RATE_PU = re.compile(r"(\d+)円\s*/\s*(\d+(?:\.\d+)?)\s*(分|時間)(?:毎|ごと)?")
RATE_UP = re.compile(r"(\d+(?:\.\d+)?)\s*(分|時間)\s*(?:毎|ごと)?に?\s*[:/]?\s*(\d+)円")
FLAT = [re.compile(p) for p in (
    r"(\d+)円\s*/?\s*(?:1日1回|1回1日|1日|日|当日|1回)(?![\d時])",
    r"(?:1日1回|1回1日|1日|当日利用|1回)(?:毎)?\s*[:]?\s*(\d+)円",
    r"(\d+)円\s*/\s*入庫後、?当日",
)]
CAP_CTX = re.compile(r"(最大|まで|打ち?切|上限|入庫|駐車後|以内|一律|1泊|夜間)")


def find_free(z):
    """(無料分, grace) grace=True は「N分以内の出庫は無料」型（超えたら最初から課金）"""
    for p in (r"(\d+)\s*(分|時間)\s*(?:以内|未満)の?出庫は?無料",
              r"最初の\s*(\d+)\s*(分|時間)\s*未満出庫は無料"):
        m = re.search(p, z)
        if m:
            return mins(m.group(1), m.group(2)), True
    m = re.search(r"(?:最初の?|入庫後|入庫から|入庫より|内)?\s*(\d+)\s*(分|時間)\s*(?:間|まで|以内)?(?:は)?無料", z)
    if m:
        return mins(m.group(1), m.group(2)), False
    return 0, False


def rates(z):
    """時間単位の料金 [(pos, P, U分, is_cap)]"""
    cand = []
    for m in RATE_PU.finditer(z):
        cand.append((m.start(), m.end(), int(m.group(1)), mins(m.group(2), m.group(3))))
    for m in RATE_UP.finditer(z):
        cand.append((m.start(), m.end(), int(m.group(3)), mins(m.group(1), m.group(2))))
    cand.sort()
    res, last_end = [], -1
    for s0, e0, p, u in cand:
        if s0 < last_end or u <= 0 or p <= 0:
            continue
        last_end = e0
        before = z[max(0, s0 - 6):s0]
        cap = bool(re.search(r"(入庫|駐車)(後|から|より)\s*$|最大\s*$|まで\s*$", before)) or \
            bool(re.match(r"\s*最大", z[e0:e0 + 3])) and u >= 300
        res.append((s0, p, u, cap))
    return res


BAND = re.compile(r"\d{1,2}:\d{2}\s*~\s*(?:翌)?\d{1,2}:\d{2}|\d{1,2}時\s*~\s*\d{1,2}時|\d{1,2}\s*~\s*\d{1,2}時")


def caps(z):
    """上限 [(pos, window時間 or None=当日/1日, 金額, kind)] kind: 'win'|'day'|'night'|'band'"""
    out = []
    for m in re.finditer(r"最大(?:料金)?([^円]{0,16}?)(\d+)円|(打ち?切り?)\s*(\d+)円", z):
        amt = int(m.group(2) or m.group(4))
        mid = m.group(1) or ""
        if re.match(r"\s*/\s*1?日", z[m.end():]):
            mid += "1日"
        out.append((m.start(), amt, z[max(0, m.start() - 14):m.start()], mid, None))
    for m in re.finditer(r"(?:入庫|駐車)(?:後|から|より)\s*(\d+)\s*時間\s*(?:まで|以内)?(?:\(1限\))?\s*[:]?\s*(?:最大)?\s*(\d+)円", z):
        if not any(abs(m.start() - o[0]) < 25 and o[1] == int(m.group(2)) for o in out):
            out.append((m.start(), int(m.group(2)), "", "", int(m.group(1)) or None))
    res = []
    for pos, amt, before, mid, w0 in out:
        if w0:
            res.append((pos, w0, amt, "win"))
            continue
        w = None
        near = before[-9:]
        if re.search(r"夜間|1泊|宿泊", near + mid):
            kind = "night"
        elif re.search(r"昼間|営業時間内", near + mid):
            kind = "day"
        else:
            kind = "win"
        mm = re.search(r"(?<![/\d])(\d+)\s*時間\s*(?:まで|以内|毎|ごと)?\s*(?:\(1限\))?\s*$", before) or \
            re.search(r"(\d+)\s*時間", mid)
        if kind == "win" and mm and not re.search(r"1日|当日", before[-6:] + mid):
            w = int(mm.group(1)) or None
        if kind == "win" and w is None and not re.search(r"1日|当日|24時", before[-8:] + mid) \
                and any(not re.fullmatch(r"0?0:00\s*~\s*24:00", b) for b in BAND.findall(z[max(0, pos - 30):pos])):
            kind = "band"  # 時間帯ごとの最大（8:00~22:00 ... 最大800円）
        res.append((pos, w, amt, kind))
    return res


def parse_one(z):
    """1つの料金体系（曜日・車種で分割済み）を読む"""
    fee = {"h": None, "u": None, "m": None, "nc": False, "f": 0}
    if not z.strip() or re.fullmatch(r"\s*(-|なし|料金不明|有料（料金不明）)\s*", z):
        return fee
    if re.fullmatch(r"\s*無料.*", z) and "円" not in z:
        fee.update(h=0, m=0, u="無料")
        return fee
    free, grace = find_free(z)
    fee["f"] = free
    allr = rates(z)
    rs = [r for r in allr if not r[3]]
    cap_rates = [r for r in allr if r[3]]
    # 長い単位で高い料金が、短い単位の料金と並んでいる → 長い方は上限（「24時間500円 オールタイム30分100円」）
    keep = []
    for r in rs:
        shorter = [o for o in rs if o[2] < r[2] and o[1] < r[1]] if r[2] >= 300 else []
        later_kw = any(re.search(r"以降|その後|以後|超", z[min(r[0], o[0]):max(r[0], o[0])]) for o in shorter)
        if shorter and not later_kw:
            cap_rates.append(r)
        else:
            keep.append(r)
    rs = keep
    cs = caps(z)
    flat = None
    for p in FLAT:
        m = p.search(z)
        if m and not re.search(r"(最大|まで)\s*$", z[max(0, m.start() - 4):m.start()]):
            flat = int(m.group(1))
            break
    if flat is not None and rs and rs[0][0] < z.find(str(flat)):
        flat = None  # 「100円/2時間 最大800円/日」の /日 は上限
    if flat is None and not rs:
        ms = re.findall(r"(\d+)円", z)
        if len(ms) == 1:
            flat = int(ms[0])  # 「バイク小 1階屋内 200円」など1回料金
    if flat is not None and not rs:
        fee.update(h=0 if free >= 60 else flat, m=flat, u=f"{flat:,}円/1回（1日）")
        return fee

    if not rs:
        if cs:
            fee["m"] = max(c[2] for c in cs)
        return fee

    # 基本料金 = 最初の時間単位
    _, p0, u0, _ = rs[0]
    # 「最初の1時間まで200円 以降30分毎100円」「8時間200円その後4時間毎100円」型
    later = [r for r in rs[1:] if r[2] < u0 and re.search(r"以降|その後|以後|超", z[rs[0][0]:r[0]])]
    cap_rates += [r for r in rs[1:] if r[2] > u0 and r[1] > p0 and r[2] >= 300]
    fee["u"] = unit_str(p0, u0)
    if free:
        dur = f"{free // 60}時間{'半' if free % 60 == 30 else ''}" if free >= 60 and free % 60 in (0, 30) else f"{free}分"
        fee["u"] += f"（{dur}{'未満の出庫は' if grace else ''}無料）"

    # 1時間停めた料金
    if free > 60 or (free == 60 and not (grace and "未満" in z)):
        h = 0
    else:
        charged = 60 if grace else 60 - free
        if re.search(r"無料時間(?:を)?含め|無料時間含む|含む", z):
            charged = 60
        h = p0 * math.ceil(charged / u0) if u0 < charged else p0
    # 上限で頭打ち
    shortcaps = [c[2] for c in cs if c[3] != "night"] + [r[1] for r in cap_rates]
    if shortcaps:
        h = min(h, min(shortcaps))
    fee["h"] = h

    # 24時間停めた料金
    def run(total):
        """total分停めたときの、上限を考慮しない料金"""
        t = total - (0 if grace else free)
        if grace and total <= free:
            return 0
        if t <= 0:
            return 0
        if later:
            _, p1, u1, _ = later[0]
            return p0 + (math.ceil(max(0, t - u0) / u1) * p1 if t > u0 else 0)
        return math.ceil(t / u0) * p0

    day = None
    win = [c for c in cs if c[3] == "win"] + [(r[0], r[2] // 60, r[1], "win") for r in cap_rates if r[2] >= 60]
    dn = [c for c in cs if c[3] in ("day", "night", "band")]
    rep = re.search(r"繰り?返|毎最大|ごと最大|毎\s*最大|24時間毎|24時間ごと", z)
    wv = None
    for _, w, amt, _ in win:
        if w is None or w >= 24:
            v = amt
        elif rep:
            v = amt * (24 // w) + min(amt, run((24 % w) * 60)) if 24 % w else amt * (24 // w)
        else:
            v = amt + min(amt * math.ceil((24 - w) / w), run((24 - w) * 60))
        wv = v if wv is None else min(wv, v)
    if len(dn) >= 2 or (dn and wv is not None and any(w is not None and w < 24 for _, w, _, _ in win)):
        # 昼の上限＋夜の上限（時間帯ごとの最大料金）
        parts = [c[2] for c in dn]
        if len(dn) == 1:
            parts.append(min(c[2] for c in win))
        day = sum(parts[:2])
        full = [c[2] for c in win if c[1] is None or c[1] >= 24]
        if full:
            day = min(day, min(full))
    elif wv is not None:
        day = wv
    elif dn:
        day = None  # 一部の時間帯だけ上限 → 残りの時間の料金次第。読めない
    elif u0 >= 120 or (later and u0 >= 120 and later[0][2] >= 120):
        day = run(24 * 60)
    else:
        fee["nc"] = True  # 時間料金だけで上限なし
    if flat is not None and day is None:
        day = flat
    if day is not None and (day < 0 or day > 30000):
        day = None
    fee["m"] = day
    if day is not None and fee["h"] is not None:
        fee["h"] = min(fee["h"], day)
    return fee


CC = re.compile(r"(\d+\s*cc\s*(?:以下|未満|以上|超|まで)?(?:\s*\d+\s*cc\s*(?:以下|未満))?|\d+~\d+cc(?:以下)?|"
                r"原付[^:：、\s]*|自動二輪(?:車)?|小型[^:：、\s]{0,12}|中型[^:：、\s]{0,6}|大型[^:：、\s]{0,12}|"
                r"バイク(?:小|中|大)(?:・(?:中|大))?|バイク\d+cc[^\d\s円]*|バイク\s+|一般|学生|"
                r"\[(?:小型|大型)バイク\]|\[\d+cc(?:以上|以下)\]|原付バイク駐車場|バイク駐車場)")


def split_cc(z):
    ms = list(CC.finditer(z))
    if len(ms) < 2:
        return [z]
    parts = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(z)
        seg = z[m.start():end]
        if "円" in seg or "無料" in seg:
            parts.append(seg)
    if len(parts) < 2:
        return [z]
    # 共通の注記（※2時間まで無料 など）は全部に付ける
    tail = re.search(r"※[^※]*$", parts[-1])
    if tail and "円" not in tail.group(0):
        parts = [p if "※" in p else p + " " + tail.group(0) for p in parts]
    return parts


def worse(a, b):
    """車種別のうち高い方（自動二輪の方）。上限なしは一番高い扱い"""
    def key(x):
        m = float("inf") if x["nc"] else (x["m"] if x["m"] is not None else -1)
        return (m, x["h"] if x["h"] is not None else -1)
    return a if key(a) >= key(b) else b


def closed_days(holiday):
    z = norm(holiday)
    if re.search(r"無人|問い合わせ|不在", z) and not re.search(r"日曜|土日", z):
        return set()
    out = set()
    if re.search(r"土日|土・日|土曜", z):
        out |= {"sat", "hol"}
    if re.search(r"日曜|日祝|祝日|・祝", z):
        out.add("hol")
    return out


def parse_fee(price, holiday=""):
    raw = price or ""
    key = next((k for k in OVERRIDES if k == raw or (len(k) >= 20 and k in raw)), None)
    if key is not None:
        o = OVERRIDES[key]
        res = {"days": o.get("days", "diff"), "cc": o.get("cc", False)}
        base = {"h": None, "u": None, "m": None, "nc": False, "f": 0}
        for k in ("wd", "sat", "hol"):
            v = o.get(k) or o.get("all")
            res[k] = dict(base, **v) if v else dict(base)
    else:
        z = norm(raw)
        parts = split_cc(z)
        if len(parts) > 1:
            # 「最初の1時間は無料 【126cc以上】…」のように共通の無料時間が前にあるとき
            m = re.search(r"[^、\n]*無料[^、\n]*", z[:z.find(parts[0])])
            if m:
                parts = [p if "無料" in p else m.group(0) + " " + p for p in parts]
        fees = [parse_one(p) for p in parts]
        fee = fees[0]
        for x in fees[1:]:
            fee = worse(fee, x)
        days = "all" if re.search(r"全日|オールタイム|年中同一", z) else ""
        res = {"days": days, "cc": len(parts) > 1, "wd": fee, "sat": dict(fee), "hol": dict(fee)}
    for k in closed_days(holiday):
        res[k] = {"x": True}
        res["days"] = "diff"
    return res
