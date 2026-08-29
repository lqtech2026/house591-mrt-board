#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
591 捷運站周邊 售價匯報工具

只用 Python 標準函式庫，不需要 pip install 任何東西。

用法:
    python3 house591.py              # 抓資料 + 產生 CSV 與 HTML 報告
    python3 house591.py --stations   # 列出所有可用的捷運站名
    python3 house591.py --dry-run    # 只查各條件的總筆數，不抓明細

資料來源是 591 網站前端自己在呼叫的公開介面。請維持低頻率抓取(config 的
request_delay_sec)，這是自用小工具，不要拿去大量爬。
"""

import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "out")

API = "https://bff-house.591.com.tw/v1/web/sale/list"
DETAIL_URL = "https://sale.591.com.tw/home/house/detail/2/{}.html"
PAGE_SIZE = 30

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 物件類別 -> 591 查詢參數。kind/shape/floor 的值是從 591 前端反推出來的。
CATEGORIES = {
    "一樓店面":  {"kind": 5,  "floor": "1$_1"},
    "店面":      {"kind": 5},
    "土地":      {"kind": 11},
    "透天":      {"kind": 9,  "shape": 3},
    "別墅":      {"kind": 9,  "shape": 4},
    "住宅":      {"kind": 9},
    "公寓":      {"kind": 9,  "shape": 1},
    "電梯大樓":  {"kind": 9,  "shape": 2},
    "華廈":      {"kind": 9,  "shape": 5},
    "住辦":      {"kind": 12},
    "辦公":      {"kind": 6},
    "套房":      {"kind": 10},
    "廠房":      {"kind": 7},
    "車位":      {"kind": 8},
    "法拍屋":    {"kind": 22},
    "其他":      {"kind": 24},
}


# ---------------------------------------------------------------- 基礎工具

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def log(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def fetch_json(params, timeout, retries):
    """打 591 的 list API，回傳 dict。失敗會退避重試。"""
    url = API + "?" + urllib.parse.urlencode(params, safe="$,_")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://sale.591.com.tw/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-TW,zh;q=0.9",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return json.loads(raw.decode("utf-8"))
        except Exception as exc:                      # 逾時 / 連線中斷 / 非 JSON
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("API 連續 %d 次失敗: %s\n  URL: %s" % (retries, last, url))


def to_num(v):
    """591 的數字欄位有時是字串、有時是 "108~118" 這種區間，統一轉成 float。"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    txt = str(v).replace(",", "").replace("萬", "").strip()
    if "~" in txt:                       # 區間取下限
        txt = txt.split("~")[0]
    try:
        return float(txt)
    except ValueError:
        return None


def tidy(v):
    """1234.0 -> 1234，1234.5 保持 1234.5，讓 CSV / 報表數字乾淨。"""
    if v is None:
        return None
    return int(v) if float(v).is_integer() else round(float(v), 2)


def real_listings(payload):
    """濾掉業配新建案與內嵌廣告，只留真實中古物件。"""
    rows = (payload.get("data") or {}).get("house_list") or []
    return [h for h in rows if not h.get("is_newhouse") and h.get("houseid")]


# ---------------------------------------------------------------- 抓取

def build_params(cfg, station_ids, category):
    p = {"regionid": cfg["region_id"], "type": 2,
         "station": ",".join(str(i) for i in station_ids)}
    p.update(CATEGORIES[category])

    lo, hi = cfg.get("min_area_ping"), cfg.get("max_area_ping")
    if lo is not None or hi is not None:
        p["area"] = "%s$%s" % (lo if lo is not None else "",
                               hi if hi is not None else "_")
    plo, phi = cfg.get("min_price_wan"), cfg.get("max_price_wan")
    if plo is not None or phi is not None:
        p["price"] = "%s$%s" % (plo if plo is not None else "",
                                phi if phi is not None else "_")
    return p


def crawl(cfg, station_ids, dry_run=False):
    """逐類別分頁抓完，回傳 {houseid: record}。"""
    delay = cfg.get("request_delay_sec", 0.6)
    timeout = cfg.get("timeout_sec", 40)
    retries = cfg.get("retries", 3)
    max_pages = cfg.get("max_pages_per_query", 400)

    found = {}
    for category in cfg["categories"]:
        if category not in CATEGORIES:
            log("  ! 略過未知類別: %s" % category)
            continue
        params = build_params(cfg, station_ids, category)

        first = fetch_json(params, timeout, retries)
        total = int((first.get("data") or {}).get("total") or 0)
        log("  %-8s 591 回報 %s 筆" % (category, total))
        if dry_run:
            continue

        page_rows = real_listings(first)
        for h in page_rows:
            h["_category"] = category
            found.setdefault(h["houseid"], h)

        pages = min((total + PAGE_SIZE - 1) // PAGE_SIZE, max_pages)
        for page in range(1, pages):
            time.sleep(delay)
            params["firstRow"] = page * PAGE_SIZE
            try:
                payload = fetch_json(params, timeout, retries)
            except RuntimeError as exc:
                log("    ! 第 %d 頁失敗，跳過: %s" % (page + 1, exc))
                continue
            rows = real_listings(payload)
            if not rows:
                break
            for h in rows:
                h["_category"] = category
                found.setdefault(h["houseid"], h)
            sys.stdout.write("\r    抓取中 %d/%d 頁 (累計 %d 筆)" %
                             (page + 1, pages, len(found)))
            sys.stdout.flush()
        if pages > 1:
            sys.stdout.write("\r" + " " * 60 + "\r")
    return found


# ---------------------------------------------------------------- 整理

def is_basement(floor):
    """樓層欄長得像 "B1/12F"、"1F/4F"、"整棟/2F"、"1F~2F/2F"。
    斜線前面才是物件自己的樓層，以 B 開頭就是地下室。土地沒有樓層，回 False。"""
    own = str(floor or "").split("/")[0].strip()
    return own.upper().startswith("B")


def clean_station(name, known):
    """591 回的是「古亭站」「台北車站」，統一成設定檔裡的寫法(別把台北車站砍成台北車)。"""
    if not name:
        return ""
    if name in known:
        return name
    if name.endswith("站") and name[:-1] in known:
        return name[:-1]
    return name


def normalise(raw, cfg):
    """把 591 的原始欄位整理成報表用的欄位，並套用本地端過濾條件。"""
    out = []
    known = set(cfg.get("stations") or [])
    max_dist = cfg.get("max_distance_m")
    min_area = cfg.get("min_area_ping")
    max_area = cfg.get("max_area_ping")
    min_price = cfg.get("min_price_wan")
    max_price = cfg.get("max_price_wan")
    min_unit = cfg.get("min_unit_price_wan")
    drop_b = cfg.get("exclude_basement", True)

    for h in raw.values():
        dist = to_num(h.get("distance"))
        area = to_num(h.get("area"))
        price = to_num(h.get("price"))

        # 591 的捷運搜尋收到 2 公里，這裡再收緊一次
        if max_dist is not None and (dist is None or dist > max_dist):
            continue
        if area is None or price is None:
            continue
        if min_area is not None and area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue

        if drop_b and is_basement(h.get("floor")):
            continue

        unit = to_num(h.get("unitprice"))
        if not unit and area:
            unit = round(price / area, 2)
        # 單價低到不合理的多半是「頂讓」或誤刊，不是真的售屋
        if min_unit is not None and unit is not None and unit < min_unit:
            continue

        out.append({
            "類別": h.get("_category", ""),
            "型態": h.get("shape_name") or "",
            "捷運站": clean_station(h.get("distance_name"), known),
            "距離(m)": int(dist) if dist is not None else None,
            "總價(萬)": tidy(price),
            "單價(萬/坪)": tidy(unit),
            "坪數": tidy(area),
            "主建物坪": tidy(to_num(h.get("mainarea"))) or "",
            "格局": h.get("room") or "",
            "樓層": h.get("floor") or "",
            "屋齡": h.get("showhouseage") or "",
            "行政區": h.get("section_name") or "",
            "地址": h.get("address") or "",
            "社區": h.get("community_name") or "",
            "標題": h.get("title") or "",
            "含車位": "是" if h.get("price_has_carport") else "",
            "降價": "是" if h.get("is_down_price") else "",
            "刊登": h.get("refreshtime") or "",
            "聯絡人": h.get("nick_name") or h.get("linkman") or "",
            "同物件筆數": 1,
            "開價區間": "",
            "其他仲介": "",
            "其他連結": "",
            "houseid": h["houseid"],
            "連結": DETAIL_URL.format(h["houseid"]),
        })

    out.sort(key=lambda r: (r["捷運站"], r["距離(m)"] if r["距離(m)"] is not None else 9999))
    return out


def merge_duplicates(rows):
    """同一間房常被好幾家仲介同時刊登，而且各家開價可能不一樣。

    用 prop_key（區＋類別＋坪數＋樓層＋地址，不含價格）當指紋合併，
    保留開價最低的那筆當代表；各家開價不同時記在「開價區間」，那是議價的資訊。
    合併鍵不含價格才抓得到「同一間、兩家開不同價」的情形。
    """
    groups = {}
    for r in rows:
        groups.setdefault(prop_key(r), []).append(r)

    merged = []
    for items in groups.values():
        items.sort(key=lambda x: (
            x["總價(萬)"] if x["總價(萬)"] is not None else float("inf"),
            x["距離(m)"] if x["距離(m)"] is not None else 9999,
            x["houseid"]))
        rep = dict(items[0])
        rep["同物件筆數"] = len(items)

        prices = sorted({i["總價(萬)"] for i in items if i["總價(萬)"] is not None})
        rep["開價區間"] = "%g~%g" % (prices[0], prices[-1]) if len(prices) > 1 else ""

        if len(items) > 1:
            others = [i["聯絡人"] for i in items[1:] if i["聯絡人"]]
            rep["其他仲介"] = "、".join(dict.fromkeys(others))
            rep["其他連結"] = " ".join(i["連結"] for i in items[1:])
        else:
            rep["其他仲介"] = ""
            rep["其他連結"] = ""
        merged.append(rep)

    merged.sort(key=lambda r: (r["捷運站"], r["距離(m)"] if r["距離(m)"] is not None else 9999))
    return merged


def median(values):
    vals = sorted(v for v in (to_num(x) for x in values) if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else round((vals[n // 2 - 1] + vals[n // 2]) / 2, 2)


def summarise(rows, key):
    """依 key 分組統計筆數、總價中位數、單價中位數。"""
    groups = {}
    for r in rows:
        groups.setdefault(r[key], []).append(r)
    stats = []
    for name, items in groups.items():
        prices = [i["總價(萬)"] for i in items]
        units = [i["單價(萬/坪)"] for i in items]
        stats.append({
            "name": name,
            "count": len(items),
            "price_median": median(prices),
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
            "unit_median": median(units),
        })
    stats.sort(key=lambda s: -s["count"])
    return stats


# ---------------------------------------------------------------- 快照比對

# 物件指紋的版本。改了 prop_key 的組成就把這個數字加一：
# 舊快照的 key 會全部對不上，與其噴出一整批假的「新上架／已下架」，
# 不如直接重建基準。
KEY_VERSION = 2


def prop_key(r):
    """物件指紋。刻意不含價格(價格是要拿來比的)，也不含 houseid
    (同一間房換仲介刊登 houseid 就變了)。"""
    tail = r.get("地址") or r.get("社區") or str(r["houseid"])
    return "|".join([r.get("行政區", ""), r.get("類別", ""),
                     str(r.get("坪數", "")), str(r.get("樓層", "")), tail])


def diff_snapshot(rows):
    """跟上次結果比對，標出新上架 / 降價 / 已下架。

    591 每次回的分頁結果會些微跳動（同樣的條件，前後兩次抓到的集合會差幾筆），
    所以不能「這次沒看到就算下架」——那樣每天都會冒出十幾筆假異動。
    這裡改成記錄每筆物件連續幾次沒出現，連續 2 次才算真的下架。
    """
    path = os.path.join(DATA_DIR, "snapshot.json")
    store = {"run": 0, "items": {}}
    if os.path.exists(path):
        try:
            raw = load_json(path)
            if isinstance(raw, dict) and "items" in raw:
                if raw.get("key_version") == KEY_VERSION:
                    store = raw
                else:
                    log("  指紋格式已更新，重建比對基準（這次不判定異動）")
        except Exception:
            pass

    first_run = not store["items"]
    run = store["run"] + 1
    items = store["items"]

    # 先把這次的結果整理成 指紋 -> 物件，並找出撞號的指紋。
    # 撞號代表這個指紋分不出是哪一戶，拿去比價會產生假的降價，所以排除在異動判斷外。
    current, ambiguous = {}, set()
    for r in rows:
        key = prop_key(r)
        if key in current:
            ambiguous.add(key)
        current[key] = r

    prev = items                       # 上次存下來的狀態，比對期間不動它
    new_ids, drops = [], []
    updated = {}
    for key, r in current.items():
        cur = r["總價(萬)"]
        old = prev.get(key)
        if key not in ambiguous:
            if old is None:
                if not first_run:
                    new_ids.append(key)
            else:
                op = to_num(old.get("price"))
                if op is not None and cur is not None and cur < op:
                    drops.append((key, op, cur))
        updated[key] = {"price": cur, "title": r["標題"], "station": r["捷運站"],
                        "houseid": r["houseid"], "miss": 0}
    items = dict(prev, **updated)

    # 這次沒出現的，累計未出現次數；連續 2 次才判定下架
    seen = set(current)
    gone = []
    for key in list(items):
        if key in seen:
            continue
        items[key]["miss"] = items[key].get("miss", 0) + 1
        if items[key]["miss"] == 2:
            gone.append((key, items[key]))
        elif items[key]["miss"] > 3:
            del items[key]                     # 早就沒了，不用再留

    by_key = {prop_key(r): r for r in rows}
    new_set = set(new_ids)
    for r in rows:
        r["新上架"] = "是" if not first_run and prop_key(r) in new_set else ""
        r["對比上次"] = ""
    for key, old_p, new_p in drops:
        by_key[key]["對比上次"] = "降 %g 萬 (%g→%g)" % (old_p - new_p, old_p, new_p)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run": run, "key_version": KEY_VERSION, "items": items},
                  f, ensure_ascii=False)

    return {"first_run": first_run, "new": new_ids, "drops": drops, "gone": gone}


# ---------------------------------------------------------------- 輸出

CSV_FIELDS = ["類別", "型態", "捷運站", "距離(m)", "總價(萬)", "單價(萬/坪)", "坪數",
              "主建物坪", "格局", "樓層", "屋齡", "行政區", "地址", "社區",
              "含車位", "降價", "新上架", "對比上次", "刊登", "聯絡人",
              "同物件筆數", "開價區間", "其他仲介", "標題", "houseid", "連結", "其他連結"]


def write_csv(rows, stamp):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "591_%s.csv" % stamp)
    # utf-8-sig 讓 Excel 直接開不會亂碼
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_html(rows, cfg, changes, stamp):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "591_%s.html" % stamp)

    by_station = summarise(rows, "捷運站")
    by_category = summarise(rows, "類別")

    def fmt(v, suffix=""):
        return "—" if v is None else ("%g%s" % (v, suffix))

    parts = []
    parts.append(HTML_HEAD.replace("{{TITLE}}", "591 捷運周邊物件 " + stamp))

    cond = "%s坪以上" % cfg.get("min_area_ping")
    if cfg.get("max_distance_m"):
        cond += "・站距 %d 公尺內" % cfg["max_distance_m"]
    if cfg.get("max_price_wan"):
        cond += "・總價 %g 萬以下" % cfg["max_price_wan"]

    dup_note = ""
    if cfg.get("merge_duplicates", True):
        multi = sum(1 for r in rows if r.get("同物件筆數", 1) > 1)
        if multi:
            dup_note = "（已合併重複刊登，其中 %d 間有多家仲介同時刊登）" % multi
    parts.append('<header><h1>591 捷運周邊物件</h1>'
                 '<p class="sub">%s ｜ %s ｜ 共 <b>%d</b> 間</p>'
                 '<p class="sub">%s%s</p></header>'
                 % (esc("、".join(cfg["categories"])), esc(cond), len(rows),
                    esc(datetime.now().strftime("%Y-%m-%d %H:%M 產出")), esc(dup_note)))

    # 變動摘要
    if not changes["first_run"]:
        parts.append('<section class="cards"><div class="card"><div class="k">新上架</div>'
                     '<div class="v">%d</div></div>'
                     '<div class="card"><div class="k">降價</div><div class="v">%d</div></div>'
                     '<div class="card"><div class="k">已下架</div><div class="v">%d</div></div>'
                     '</section>' % (len(changes["new"]), len(changes["drops"]),
                                     len(changes["gone"])))

    # 統計表
    for title, stats, label in (("依捷運站", by_station, "捷運站"),
                                ("依類別", by_category, "類別")):
        parts.append('<h2>%s</h2><div class="scroll"><table class="stats"><thead><tr>'
                     '<th>%s</th><th>筆數</th><th>總價中位數</th><th>總價區間</th>'
                     '<th>單價中位數</th></tr></thead><tbody>' % (title, label))
        for s in stats:
            parts.append('<tr><td>%s</td><td class="num">%d</td>'
                         '<td class="num">%s</td><td class="num rng">%s ~ %s</td>'
                         '<td class="num">%s</td></tr>'
                         % (esc(s["name"]), s["count"], fmt(s["price_median"], " 萬"),
                            fmt(s["price_min"]), fmt(s["price_max"]),
                            fmt(s["unit_median"], " 萬/坪")))
        parts.append("</tbody></table></div>")

    # 明細表
    parts.append('<h2>物件明細</h2>'
                 '<div class="toolbar"><input id="q" type="search" '
                 'placeholder="搜尋站名 / 地址 / 社區 / 標題…"><span id="cnt"></span></div>'
                 '<div class="scroll"><table id="rows"><thead><tr>')
    cols = ["狀態", "捷運站", "距離(m)", "類別", "型態", "總價(萬)", "單價(萬/坪)", "坪數",
            "格局", "樓層", "屋齡", "行政區", "地址", "標題"]
    for i, c in enumerate(cols):
        parts.append('<th data-i="%d">%s</th>' % (i, esc(c)))
    parts.append("</tr></thead><tbody>")

    for r in rows:
        # 新上架與降價是最該一眼看到的，放在最前面的「狀態」欄
        status = ""
        if r.get("新上架"):
            status += '<span class="tag new">新上架</span>'
        if r.get("對比上次"):
            status += '<span class="tag drop">%s</span>' % esc(r["對比上次"])
        elif r.get("降價") == "是":
            status += '<span class="tag drop">降價</span>'

        flags = ""
        if r.get("同物件筆數", 1) > 1:
            flags += '<span class="tag dup" title="%s">%d 家仲介</span>' % (
                esc(r.get("其他仲介", "")), r["同物件筆數"])
        if r.get("開價區間"):
            flags += '<span class="tag rng">開價 %s 萬</span>' % esc(r["開價區間"])
        parts.append('<tr tabindex="0" role="link" data-url="%s" title="點一下在 591 開啟">'
                     % esc(r["連結"]))
        for c in cols:
            if c == "狀態":
                parts.append('<td class="stat">%s</td>' % status)
                continue
            v = r.get(c)
            v = "" if v is None else v
            if c == "標題":
                parts.append('<td class="ttl"><a href="%s" target="_blank" rel="noopener">%s</a>%s</td>'
                             % (esc(r["連結"]), esc(v), flags))
            elif c in ("總價(萬)", "單價(萬/坪)", "坪數", "距離(m)"):
                parts.append('<td class="num">%s</td>' % esc(v))
            else:
                parts.append("<td>%s</td>" % esc(v))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    parts.append(HTML_TAIL)

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path


HTML_HEAD = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title><style>
:root{--bg:#fbfaf9;--fg:#1c1b1a;--mut:#6b6866;--line:#e4e0dc;--card:#fff;--zebra:#f5f3f1;--acc:#b45309;--new:#0f766e;--drop:#b91c1c}
@media(prefers-color-scheme:dark){:root{--bg:#191817;--fg:#eeecea;--mut:#a3a09d;--line:#333130;--card:#232120;--zebra:#2a2827;--acc:#f0a355;--new:#5eead4;--drop:#fca5a5}}
*{box-sizing:border-box}
body{margin:0;padding:24px 20px 64px;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,"PingFang TC","Noto Sans TC",Helvetica,sans-serif}
header{max-width:1180px;margin:0 auto 20px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:17px;margin:32px auto 10px;max-width:1180px;font-weight:600}
.sub{margin:2px 0;color:var(--mut);font-size:13.5px}
.cards{display:flex;gap:10px;max-width:1180px;margin:0 auto;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:96px}
.card .k{font-size:12px;color:var(--mut)}
.card .v{font-size:22px;font-weight:600}
.scroll{max-width:1180px;margin:0 auto;overflow-x:auto;border:1px solid var(--line);
border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 11px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{position:sticky;top:0;background:var(--card);font-weight:600;font-size:12.5px;
color:var(--mut);cursor:pointer;user-select:none}
thead th:hover{color:var(--fg)}
tbody tr:last-child td{border-bottom:0}
tbody tr{cursor:pointer}
tbody tr:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
tbody tr:nth-child(even){background:var(--zebra)}
tbody tr:hover{background:color-mix(in srgb,var(--acc) 9%,transparent)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.rng{color:var(--mut)}
.ttl{white-space:normal;min-width:280px;max-width:460px}
.ttl a{color:var(--fg);text-decoration:none}
.ttl a:hover{color:var(--acc);text-decoration:underline}
.tag{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;
font-size:11px;vertical-align:middle;white-space:nowrap}
.tag.new{color:var(--new);border:1px solid currentColor}
.tag.drop{color:var(--drop);border:1px solid currentColor}
.tag.dup{color:var(--mut);border:1px solid var(--line)}
.tag.rng{color:var(--acc);border:1px solid currentColor}
td.stat{white-space:nowrap}
td.stat .tag{margin-left:0;margin-right:4px}
.stats td:first-child{font-weight:500}
.toolbar{max-width:1180px;margin:0 auto 10px;display:flex;gap:12px;align-items:center}
#q{flex:1;max-width:360px;padding:7px 11px;border:1px solid var(--line);border-radius:8px;
background:var(--card);color:var(--fg);font-size:14px}
#cnt{color:var(--mut);font-size:13px}
</style></head><body>"""

HTML_TAIL = """<script>
(function(){
 var tbl=document.getElementById('rows'); if(!tbl) return;
 var tb=tbl.tBodies[0], all=[].slice.call(tb.rows), cnt=document.getElementById('cnt');
 function show(n){cnt.textContent='顯示 '+n+' / '+all.length+' 筆';}
 show(all.length);
 document.getElementById('q').addEventListener('input',function(e){
   var q=e.target.value.trim().toLowerCase(), n=0;
   all.forEach(function(r){
     var hit=!q||r.textContent.toLowerCase().indexOf(q)>-1;
     r.style.display=hit?'':'none'; if(hit)n++;
   });
   show(n);
 });
 /* 整列可點，不用滑到最右邊 */
 function openRow(tr){ var u=tr&&tr.getAttribute('data-url'); if(u) window.open(u,'_blank','noopener'); }
 tb.addEventListener('click',function(e){
   if(e.target.closest('a')) return;
   if(String(getSelection())) return;
   openRow(e.target.closest('tr'));
 });
 tb.addEventListener('keydown',function(e){
   if(e.key!=='Enter'&&e.key!==' ') return;
   var tr=e.target.closest('tr'); if(!tr) return;
   e.preventDefault(); openRow(tr);
 });
 var dir={};
 [].forEach.call(tbl.tHead.rows[0].cells,function(th,i){
   th.addEventListener('click',function(){
     dir[i]=!dir[i]; var s=dir[i]?1:-1;
     var rows=all.slice().sort(function(a,b){
       var x=a.cells[i].textContent.trim(), y=b.cells[i].textContent.trim();
       var nx=parseFloat(x.replace(/,/g,'')), ny=parseFloat(y.replace(/,/g,''));
       if(!isNaN(nx)&&!isNaN(ny)) return (nx-ny)*s;
       return x.localeCompare(y,'zh-Hant')*s;
     });
     rows.forEach(function(r){tb.appendChild(r);});
   });
 });
})();
</script></body></html>"""


# ---------------------------------------------------------------- 主流程

def main():
    args = sys.argv[1:]
    stations_ref = load_json(os.path.join(BASE_DIR, "mrt_stations.json"))

    if "--stations" in args:
        by_line = {}
        for name, info in stations_ref.items():
            for ln in info["lines"]:
                by_line.setdefault(ln, []).append(name)
        for ln in sorted(by_line):
            log("\n【%s】" % ln)
            log("  " + "、".join(sorted(by_line[ln])))
        return 0

    cfg = load_json(os.path.join(BASE_DIR, "config.json"))
    dry = "--dry-run" in args

    station_ids, unknown = [], []
    for name in cfg["stations"]:
        info = stations_ref.get(name) or stations_ref.get(name.replace("站", ""))
        if info:
            station_ids.append(info["id"])
        else:
            unknown.append(name)
    if unknown:
        log("! 找不到這些站名(用 --stations 看可用站名): %s" % "、".join(unknown))
    if not station_ids:
        log("沒有任何有效站名，結束。")
        return 1

    log("查詢 %d 個捷運站 ｜ %s ｜ %s坪以上"
        % (len(station_ids), "、".join(cfg["categories"]), cfg.get("min_area_ping")))

    raw = crawl(cfg, station_ids, dry_run=dry)
    if dry:
        return 0

    rows = normalise(raw, cfg)
    raw_count = len(rows)
    if cfg.get("merge_duplicates", True):
        rows = merge_duplicates(rows)
        log("\n抓到 %d 筆刊登，符合條件 %d 筆，合併重複刊登後 %d 間物件"
            % (len(raw), raw_count, len(rows)))
    else:
        log("\n抓到 %d 筆刊登，符合條件 %d 筆" % (len(raw), raw_count))
    if not rows:
        log("沒有符合條件的物件，試著把 max_distance_m 放寬或降低 min_area_ping。")
        return 0

    changes = diff_snapshot(rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = write_csv(rows, stamp)
    html_path = write_html(rows, cfg, changes, stamp)

    log("")
    log("%-8s %5s  %-11s %-11s" % ("捷運站", "筆數", "總價中位數", "單價中位數"))
    log("-" * 46)
    for s in summarise(rows, "捷運站"):
        log("%-9s %4d  %8s 萬  %8s 萬/坪"
            % (s["name"], s["count"],
               "—" if s["price_median"] is None else "%g" % s["price_median"],
               "—" if s["unit_median"] is None else "%g" % s["unit_median"]))

    if not changes["first_run"]:
        log("\n變動：新上架 %d ｜ 降價 %d ｜ 已下架 %d"
            % (len(changes["new"]), len(changes["drops"]), len(changes["gone"])))
        for key, old_p, new_p in changes["drops"][:10]:
            row = next((r for r in rows if prop_key(r) == key), None)
            log("  降價 %g → %g 萬  %s" % (old_p, new_p,
                DETAIL_URL.format(row["houseid"]) if row else key))
    else:
        log("\n(第一次執行，已建立比對基準；下次跑就會標出新上架與降價)")

    log("\nCSV : %s" % csv_path)
    log("報告: %s" % html_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n中斷。")
        sys.exit(130)
