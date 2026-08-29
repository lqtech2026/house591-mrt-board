#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 house591.py 產出的最新 CSV 轉成一頁「可分享」的網頁 (out/share.html)。

用法:
    python3 make_share_page.py            # 用 out/ 裡最新的 CSV
    python3 make_share_page.py 某個.csv   # 指定 CSV
"""

import csv
import glob
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "out")

# 台北捷運官方線色。用線色標站，是資訊本身，不是裝飾。
LINE_COLORS = {
    "文湖線":     ("#B0791F", "#D9A94E"),   # (淺色底用, 深色底用)
    "淡水信義線": ("#D0002A", "#FF5A72"),
    "松山新店線": ("#00704B", "#3DBE8B"),
    "中和新蘆線": ("#D89400", "#F5B93C"),
    "板南線":     ("#0064AA", "#4FA8E8"),
    "機場線":     ("#7A3E9D", "#B77BD6"),
    "環狀線":     ("#C7A800", "#E8CE3A"),
    "新北投支線": ("#D0002A", "#FF5A72"),
    "小碧潭支線": ("#00704B", "#3DBE8B"),
}

NUM_COLS = {"距離(m)", "總價(萬)", "單價(萬/坪)", "坪數", "同物件筆數"}


def _load_prop_key():
    """直接沿用 house591.py 的物件指紋，避免兩邊各寫一份而走鐘。"""
    spec = importlib.util.spec_from_file_location(
        "_h", os.path.join(BASE_DIR, "house591.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.prop_key


PROP_KEY = _load_prop_key()


def _range_high(rng):
    """開價區間 "6850~6880" -> 6880。代表價是最低開價，這裡取最高的那個。"""
    if not rng or "~" not in rng:
        return None
    return num(rng.split("~")[-1])


def short_key(row):
    """給「我的最愛」用的短代號。指紋不含刊登編號，所以同一間房換仲介刊登也還認得。"""
    return hashlib.sha1(PROP_KEY(row).encode("utf-8")).hexdigest()[:8]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def load_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        rec = {k: (num(v) if k in NUM_COLS else v) for k, v in r.items()}
        out.append(rec)
    return out


def build(rows, stations_ref, cfg):
    """整理成頁面要用的資料結構。"""
    lines_of = {}
    for name, info in stations_ref.items():
        lines_of[name] = info["lines"]

    items = []
    for r in rows:
        st = r.get("捷運站", "")
        items.append({
            "k": short_key(r),
            "s": st,
            "d": r.get("距離(m)"),
            "c": r.get("類別", ""),
            "t": r.get("型態", ""),
            "p": r.get("總價(萬)"),
            "u": r.get("單價(萬/坪)"),
            "a": r.get("坪數"),
            "rm": r.get("格局", ""),
            "fl": r.get("樓層", ""),
            "ag": r.get("屋齡", ""),
            "dt": r.get("行政區", ""),
            "ad": r.get("地址", ""),
            "ti": r.get("標題", ""),
            "url": r.get("連結", ""),
            "dup": int(r.get("同物件筆數") or 1),
            "hi": _range_high(r.get("開價區間", "")),
            "new": r.get("新上架", ""),
            "chg": r.get("對比上次", ""),
            "sv": 2 if r.get("新上架") else (1 if r.get("對比上次") else 0),
        })

    # 各站統計
    stats = {}
    for it in items:
        stats.setdefault(it["s"], []).append(it)

    all_units = [i["u"] for i in items if i["u"]]
    umin = min(all_units) if all_units else 0
    umax = max(all_units) if all_units else 1

    board = []
    for st, group in stats.items():
        us = [g["u"] for g in group if g["u"]]
        ps = [g["p"] for g in group if g["p"]]
        board.append({
            "station": st,
            "lines": [{"name": ln, "c": LINE_COLORS.get(ln, ("#888", "#aaa"))[0],
                       "cd": LINE_COLORS.get(ln, ("#888", "#aaa"))[1]}
                      for ln in lines_of.get(st, [])],
            "n": len(group),
            "pmed": median(ps), "pmin": min(ps) if ps else None, "pmax": max(ps) if ps else None,
            "umed": median(us), "umin": min(us) if us else None, "umax": max(us) if us else None,
        })
    board.sort(key=lambda b: (b["umed"] is None, b["umed"]))

    cats = sorted({i["c"] for i in items if i["c"]})
    return {"items": items, "board": board, "cats": cats,
            "uscale": [umin, umax], "cfg": cfg, "generated": ""}


def render(data, stamp, iso=""):
    data = dict(data, generated=iso)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    cfg = data["cfg"]
    cond = "%s坪以上" % cfg.get("min_area_ping")
    if cfg.get("max_distance_m"):
        cond += " ・ 站距 %d 公尺內" % cfg["max_distance_m"]

    html = PAGE
    html = html.replace("__PAYLOAD__", payload)
    html = html.replace("__CATS__", "、".join(cfg.get("categories", [])))
    html = html.replace("__COND__", cond)
    html = html.replace("__COUNT__", str(len(data["items"])))
    html = html.replace("__STATIONS__", str(len(data["board"])))
    html = html.replace("__STAMP__", stamp)

    org = (cfg.get("org") or "").strip()
    html = html.replace("__ORGTITLE__", (org + "置產看板") if org else "捷運沿線置產看板")
    html = html.replace("__EYEBROW__", (org + " · 591 台北市") if org else "591 · 台北市")
    return html


PAGE = r"""<title>__ORGTITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700&family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
  --bg:#f4f4f1; --surface:#fbfbfa; --raise:#ffffff;
  --ink:#191b1c; --ink-2:#4b5155; --mut:#7d858a;
  --line:#e0e1dd; --line-2:#ecedea;
  --accent:#1f4f6b; --accent-soft:rgba(31,79,107,.09);
  --track:#e6e7e3; --zebra:#f2f2ef;
  --shadow:0 1px 2px rgba(20,24,26,.05),0 8px 24px -16px rgba(20,24,26,.28);
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#131517; --surface:#1a1d1f; --raise:#212528;
    --ink:#eef0f1; --ink-2:#b9c0c4; --mut:#8b9398;
    --line:#2b2f32; --line-2:#232729;
    --accent:#7ec4e8; --accent-soft:rgba(126,196,232,.12);
    --track:#2a2e31; --zebra:#202427;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"]{
  --bg:#131517; --surface:#1a1d1f; --raise:#212528;
  --ink:#eef0f1; --ink-2:#b9c0c4; --mut:#8b9398;
  --line:#2b2f32; --line-2:#232729;
  --accent:#7ec4e8; --accent-soft:rgba(126,196,232,.12);
  --track:#2a2e31; --zebra:#202427;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -18px rgba(0,0,0,.8);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"Noto Sans TC",-apple-system,"PingFang TC",sans-serif;
  font-size:15px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1200px;margin:0 auto;padding:40px 22px 80px}
.num{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}

/* ---- header ---- */
header{margin-bottom:34px}
.eyebrow{
  font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--mut);margin:0 0 10px;font-weight:500;
}
h1{
  font-family:"Noto Serif TC",serif;font-weight:700;
  font-size:clamp(28px,4.4vw,42px);line-height:1.2;letter-spacing:-.01em;
  margin:0 0 14px;text-wrap:balance;
}
.lede{color:var(--ink-2);margin:0;max-width:60ch;font-size:15.5px}
.meta{
  display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:18px;
  padding-top:16px;border-top:1px solid var(--line);
  font-size:13px;color:var(--mut);
}
.meta b{color:var(--ink);font-weight:600}
#age{margin-left:6px}
#age.stale{color:#b45309;font-weight:500}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) #age.stale{color:#f0a355}}
:root[data-theme="dark"] #age.stale{color:#f0a355}

h2{
  font-family:"Noto Serif TC",serif;font-size:19px;font-weight:700;
  margin:44px 0 4px;letter-spacing:-.005em;
}
.hint{color:var(--mut);font-size:13px;margin:0 0 16px}

/* ---- station board ---- */
.board{
  background:var(--surface);border:1px solid var(--line);
  border-radius:12px;overflow:hidden;box-shadow:var(--shadow);
}
.brow{
  display:grid;
  grid-template-columns:150px 58px 108px 108px minmax(150px,1fr);
  align-items:center;gap:14px;
  padding:11px 18px;border-bottom:1px solid var(--line-2);
  cursor:pointer;background:none;border-left:0;border-right:0;border-top:0;
  width:100%;text-align:left;color:inherit;font:inherit;
}
.brow:last-child{border-bottom:0}
button.brow:nth-of-type(even){background:var(--zebra)}
.brow:hover{background:var(--accent-soft)}
.brow.on{background:var(--accent-soft);box-shadow:inset 3px 0 0 var(--accent)}
.brow:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.bhead{
  font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);
  cursor:default;background:var(--raise);font-weight:600;
}
.bhead:hover{background:var(--raise)}
.stn{display:flex;align-items:center;gap:8px;min-width:0}
.dots{display:flex;gap:3px;flex:0 0 auto}
.dot{width:8px;height:8px;border-radius:50%}
.stn span{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cnt{text-align:right;color:var(--ink-2);font-size:13.5px}
.val{text-align:right;font-size:13.5px}
.val small{color:var(--mut);font-size:11px;margin-left:2px}

/* 單價分布帶 */
.spread{position:relative;height:22px}
.spread .track{
  position:absolute;top:9px;left:0;right:0;height:3px;
  background:var(--track);border-radius:2px;
}
.spread .rng{position:absolute;top:9px;height:3px;border-radius:2px;background:currentColor;opacity:.42}
.spread .med{
  position:absolute;top:4px;width:3px;height:13px;border-radius:2px;
  background:currentColor;
}
.scaleline{
  display:flex;justify-content:space-between;
  font-size:11px;color:var(--mut);padding:8px 18px 0;
}

/* ---- filters ---- */
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{
  font:inherit;font-size:13px;padding:5px 12px;border-radius:999px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink-2);
  cursor:pointer;transition:background .12s,color .12s,border-color .12s;
}
.chip:hover{border-color:var(--accent);color:var(--ink)}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--bg);font-weight:500}
:root[data-theme="dark"] .chip[aria-pressed="true"],
.chip[aria-pressed="true"]{color:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .chip[aria-pressed="true"]{color:#0d1114}}
:root[data-theme="dark"] .chip[aria-pressed="true"]{color:#0d1114}
input[type="search"]{
  font:inherit;font-size:14px;padding:7px 13px;border-radius:8px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink);
  min-width:220px;flex:1;max-width:320px;
}
input[type="search"]:focus{outline:2px solid var(--accent);outline-offset:-1px;border-color:transparent}
.shown{font-size:13px;color:var(--mut);margin-left:auto;white-space:nowrap}

/* ---- table ---- */
.tablebox{
  background:var(--surface);border:1px solid var(--line);border-radius:12px;
  overflow-x:auto;box-shadow:var(--shadow);
}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:9px 14px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line-2)}
thead th{
  position:sticky;top:0;z-index:1;background:var(--raise);
  font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--mut);font-weight:600;cursor:pointer;user-select:none;
}
thead th:hover{color:var(--ink)}
thead th[aria-sort]{color:var(--ink)}
thead th[aria-sort]::after{content:"↓";margin-left:5px;font-size:10px}
thead th[aria-sort="ascending"]::after{content:"↑"}
tbody tr:last-child td{border-bottom:0}
tbody tr:nth-child(even){background:var(--zebra)}
tbody tr:hover{background:var(--accent-soft)}
th.favcol,td.favcol{width:34px;padding-left:12px;padding-right:0;text-align:center}
thead th.favcol{cursor:default}
.star{
  font:inherit;font-size:15px;line-height:1;padding:2px 4px;border:0;border-radius:5px;
  background:none;color:var(--line);cursor:pointer;transition:color .12s,transform .08s;
}
.star:hover{color:var(--mut);transform:scale(1.15)}
.star[aria-pressed="true"]{color:#e0a12a}
.star:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.pill.gone{color:var(--mut);border-style:dashed}
td.stat{padding-left:6px;padding-right:6px}
td.stat .pill{margin-left:0;margin-right:4px}
td.stat:empty{padding:0}
td.r .pill.rng{margin-left:6px;font-weight:400}
.pill.rng{color:var(--accent);border-color:currentColor}
.favbar{
  display:flex;gap:8px;align-items:center;max-width:1180px;margin:0 auto 10px;
  font-size:13px;color:var(--mut);
}
.favbar[hidden]{display:none}   /* 作者樣式的 display 會壓過 hidden 屬性，要明寫 */
.linkbtn{
  font:inherit;font-size:13px;padding:4px 10px;border-radius:7px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink-2);cursor:pointer;
}
.linkbtn:hover{border-color:var(--accent);color:var(--ink)}
.linkbtn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
tbody tr{cursor:pointer}
tbody tr:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
td.r{text-align:right}
td.ti{white-space:normal;min-width:300px;max-width:440px;line-height:1.45}
td.ti a{color:var(--ink);text-decoration:none;border-bottom:1px solid transparent}
td.ti a:hover{color:var(--accent);border-bottom-color:currentColor}
td.ti a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.sdot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px}
.pill{
  display:inline-block;font-size:11px;padding:1px 7px;border-radius:5px;
  border:1px solid var(--line);color:var(--mut);margin-left:6px;
}
.pill.new{color:#0f766e;border-color:currentColor}
.pill.down{color:#b91c1c;border-color:currentColor}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .pill.new{color:#5eead4}
  :root:not([data-theme="light"]) .pill.down{color:#fca5a5}
}
:root[data-theme="dark"] .pill.new{color:#5eead4}
:root[data-theme="dark"] .pill.down{color:#fca5a5}
.empty{padding:40px;text-align:center;color:var(--mut)}

/* ---- 手機：表格換成卡片 ---- */
#cards{display:none;max-width:1180px;margin:0 auto;gap:10px}
#more{display:none;margin:14px auto 0;padding:9px 22px;font-size:14px}
@media (max-width:720px){#more:not([hidden]){display:block}}
.card2{
  background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;display:grid;gap:7px;cursor:pointer;box-shadow:var(--shadow);
}
.card2:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.c-top{display:flex;align-items:center;gap:8px}
.c-stn{display:flex;align-items:center;gap:6px;font-weight:500;font-size:14px}
.c-dist{color:var(--mut);font-size:12.5px;font-variant-numeric:tabular-nums}
.c-top .star{margin-left:auto;font-size:17px}
.c-ti{font-size:14px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}
.c-price{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.c-price b{font-size:21px;font-weight:600;font-family:"IBM Plex Mono",monospace;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.c-price .u{color:var(--ink-2);font-size:13px;font-variant-numeric:tabular-nums}
.c-meta{color:var(--mut);font-size:12.5px;display:flex;flex-wrap:wrap;gap:4px 10px}
.c-tags{display:flex;flex-wrap:wrap;gap:4px}
.sortbar{display:none;gap:8px;align-items:center;max-width:1180px;margin:0 auto 12px}
.sortbar select{
  font:inherit;font-size:13.5px;padding:6px 10px;border-radius:8px;flex:1;
  border:1px solid var(--line);background:var(--surface);color:var(--ink);
}
.sortbar button{
  font:inherit;font-size:13.5px;padding:6px 12px;border-radius:8px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink-2);cursor:pointer;
}
@media (max-width:720px){
  .wrap{padding:24px 14px 60px}
  h1{font-size:clamp(24px,7vw,32px)}
  .lede{font-size:14.5px}
  .meta{gap:6px 16px;font-size:12.5px}
  h2{font-size:16px;margin-top:30px}
  .tablebox{display:none}
  #cards{display:grid}
  .sortbar{display:flex}
  .toolbar{flex-wrap:wrap}
  #q{max-width:none;min-width:0;width:100%;order:3}
  .shown{margin-left:0;order:2}
  .favbar{flex-wrap:wrap}
}
footer{margin-top:36px;font-size:12.5px;color:var(--mut);line-height:1.7}
@media (max-width:820px){
  .brow{grid-template-columns:112px 44px 92px 92px;gap:10px;padding:10px 14px}
  .spread,.brow>:nth-child(5){display:none}
  .scaleline{display:none}
}
/* 這段必須排在 820px 之後：同權重時後面的規則勝出 */
@media (max-width:720px){
  .brow{grid-template-columns:minmax(0,1fr) 30px 66px 62px;gap:6px;padding:10px 10px;font-size:12.5px}
  .board .bhead{font-size:10px;letter-spacing:.03em}
  .val small{display:none}          /* 單位移到上面的說明，省下寬度 */
  .stn{gap:5px;min-width:0}
  .dot{width:7px;height:7px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">__EYEBROW__</p>
  <h1>捷運沿線置產看板</h1>
  <p class="lede">__CATS__ ｜ __COND__。預設把新上架排在最前面。點 ☆ 收進最愛；點任一列（手機是整張卡片）開啟該物件的 591 頁面；點左側站名可只看該站，欄位標題可排序。</p>
  <p class="meta">
    <span><b>__COUNT__</b> 間物件</span>
    <span><b>__STATIONS__</b> 個捷運站</span>
    <span>資料擷取 <b>__STAMP__</b><span id="age"></span></span>
  </p>
</header>

<h2>各站價格帶</h2>
<p class="hint">總價單位萬元、單價單位萬元/坪。顏色是捷運路線色，
橫條（寬螢幕才顯示）是該站單價的最低到最高，粗線是中位數。</p>
<div class="board" id="board"></div>
<div class="scaleline"><span id="s0"></span><span id="s1"></span></div>

<h2>物件明細</h2>
<div class="tools">
  <div class="chips" id="catchips"></div>
  <button class="chip" id="favchip" aria-pressed="false">★ 只看最愛</button>
  <input type="search" id="q" placeholder="搜尋站名、地址、標題…" aria-label="搜尋">
  <span class="shown" id="shown"></span>
</div>
<div class="favbar" id="favbar" hidden>
  <span id="favmsg"></span>
  <button class="linkbtn" id="favshare">複製最愛的連結</button>
  <button class="linkbtn" id="favclear">清空最愛</button>
</div>
<div class="sortbar">
  <select id="msort" aria-label="排序方式">
    <option value="sv">狀態（新上架優先）</option>
    <option value="p">總價</option>
    <option value="u">單價</option>
    <option value="a">坪數</option>
    <option value="d">離站距離</option>
    <option value="s">捷運站</option>
  </select>
  <button id="mdir" aria-label="切換排序方向">高→低</button>
</div>
<div id="cards"></div>
<button class="linkbtn" id="more" hidden>顯示更多</button>
<div class="tablebox"><table id="tbl">
  <thead><tr>
    <th class="favcol" title="我的最愛">★</th>
    <th data-k="sv" title="點這裡可把新上架與降價排到最前面">狀態</th>
    <th data-k="s">捷運站</th><th data-k="d" class="r">距離</th>
    <th data-k="c">類別</th><th data-k="t">型態</th>
    <th data-k="p" class="r">總價</th><th data-k="u" class="r">單價</th>
    <th data-k="a" class="r">坪數</th><th data-k="fl">樓層</th>
    <th data-k="ag">屋齡</th><th data-k="dt">行政區</th>
    <th data-k="ad">地址</th><th data-k="ti">物件</th>
  </tr></thead>
  <tbody id="tb"></tbody>
</table></div>
<p class="empty" id="empty" hidden>這個條件下沒有物件。</p>

<footer>
  價格單位為萬元，單價為萬元/坪。距離是 591 標示的直線距離。<br>
  同一間房若有多家仲介刊登已合併為一筆，標記「N 家」。資料為擷取當下的公開刊登內容，成交價請以實價登錄為準。
</footer>
</div>

<script>
const DATA = __PAYLOAD__;
const dark = () => {
  const s = document.documentElement.getAttribute('data-theme');
  if (s === 'dark') return true;
  if (s === 'light') return false;
  return matchMedia('(prefers-color-scheme: dark)').matches;
};
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = n => n == null ? '—' : n.toLocaleString('en-US', {maximumFractionDigits: 2});

const colorOf = st => {
  const b = DATA.board.find(x => x.station === st);
  if (!b || !b.lines.length) return 'var(--mut)';
  return dark() ? b.lines[0].cd : b.lines[0].c;
};

/* ---------- 各站價格帶 ---------- */
const [U0, U1] = DATA.uscale, span = Math.max(U1 - U0, 1);
const pct = v => ((v - U0) / span) * 100;

function drawBoard() {
  const el = document.getElementById('board');
  const head = `<div class="brow bhead"><span>捷運站</span><span class="cnt">件數</span>
    <span class="val">總價中位</span><span class="val">單價中位</span><span>單價分布</span></div>`;
  el.innerHTML = head + DATA.board.map(b => {
    const c = dark() ? (b.lines[0]||{}).cd : (b.lines[0]||{}).c;
    const dots = b.lines.map(l => `<i class="dot" style="background:${dark()?l.cd:l.c}" title="${esc(l.name)}"></i>`).join('');
    const lo = pct(b.umin), hi = pct(b.umax), me = pct(b.umed);
    return `<button class="brow" data-st="${esc(b.station)}" aria-pressed="false" style="color:${c||'var(--mut)'}">
      <span class="stn"><span class="dots">${dots}</span><span style="color:var(--ink)">${esc(b.station)}</span></span>
      <span class="cnt num">${b.n}</span>
      <span class="val num" style="color:var(--ink)">${fmt(b.pmed)}<small>萬</small></span>
      <span class="val num" style="color:var(--ink)">${fmt(b.umed)}<small>萬/坪</small></span>
      <span class="spread"><i class="track"></i>
        <i class="rng" style="left:${lo}%;width:${Math.max(hi-lo,0.6)}%"></i>
        <i class="med" style="left:calc(${me}% - 1.5px)"></i></span>
    </button>`;
  }).join('');
  document.getElementById('s0').textContent = fmt(U0) + ' 萬/坪';
  document.getElementById('s1').textContent = fmt(U1) + ' 萬/坪';
  el.querySelectorAll('.brow[data-st]').forEach(btn => btn.addEventListener('click', () => {
    const st = btn.dataset.st;
    state.station = state.station === st ? null : st;
    el.querySelectorAll('.brow[data-st]').forEach(b => {
      const on = b.dataset.st === state.station;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
    draw();
  }));
}

/* ---------- 我的最愛 ----------
   存在瀏覽器的 localStorage，只屬於這台裝置這個瀏覽器。
   key 用的是物件指紋，不是刊登編號，所以同一間房換仲介重新刊登也還認得。
   連同當下的資料一起存，之後物件從名單消失時仍找得回來。 */
const FAV_STORE = 'house591.favs';
let FAVS = {};
try { FAVS = JSON.parse(localStorage.getItem(FAV_STORE) || '{}') || {}; } catch (e) { FAVS = {}; }
const saveFavs = () => { try { localStorage.setItem(FAV_STORE, JSON.stringify(FAVS)); } catch (e) {} };
const byKey = Object.fromEntries(DATA.items.map(i => [i.k, i]));

// 網址帶 ?fav=xxx.yyy 就併進來，這樣最愛可以用連結分享／換裝置
try {
  const inc = new URLSearchParams(location.search).get('fav');
  if (inc) {
    inc.split('.').filter(Boolean).forEach(k => {
      if (!FAVS[k]) FAVS[k] = {t: Date.now(), snap: byKey[k] || null};
    });
    saveFavs();
    history.replaceState(null, '', location.pathname);   // 收掉網址上的參數
  }
} catch (e) {}

function toggleFav(k) {
  if (FAVS[k]) delete FAVS[k];
  else FAVS[k] = {t: Date.now(), snap: byKey[k] || null};
  saveFavs();
  draw();
}

/* 最愛清單 = 目前名單裡被標記的 + 已經不在名單、但當初有存下來的 */
function favRows() {
  const here = DATA.items.filter(i => FAVS[i.k]);
  const have = new Set(here.map(i => i.k));
  const gone = Object.keys(FAVS)
    .filter(k => !have.has(k) && FAVS[k] && FAVS[k].snap)
    .map(k => Object.assign({}, FAVS[k].snap, {gone: true}));
  return here.concat(gone);
}

/* ---------- 篩選 ---------- */
const state = {station: null, cat: null, q: '', sort: 'sv', asc: false, favOnly: false};

document.getElementById('catchips').innerHTML =
  ['全部', ...DATA.cats].map((c, i) =>
    `<button class="chip" data-cat="${i ? esc(c) : ''}" aria-pressed="${i ? 'false' : 'true'}">${esc(c)}</button>`).join('');
document.querySelectorAll('#catchips .chip').forEach(ch => ch.addEventListener('click', () => {
  state.cat = ch.dataset.cat || null;
  document.querySelectorAll('#catchips .chip').forEach(x =>
    x.setAttribute('aria-pressed', x === ch));
  draw();
}));
document.getElementById('q').addEventListener('input', e => { state.q = e.target.value.trim().toLowerCase(); draw(); });

document.querySelectorAll('#tbl thead th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  if (state.sort === k) state.asc = !state.asc; else { state.sort = k; state.asc = true; }
  document.querySelectorAll('#tbl thead th').forEach(x => x.removeAttribute('aria-sort'));
  th.setAttribute('aria-sort', state.asc ? 'ascending' : 'descending');
  draw();
}));

/* ---------- 明細 ---------- */
const MQ = matchMedia('(max-width: 720px)');
const PAGE_SIZE = 50;          // 手機一次先畫這麼多張，其餘按「顯示更多」
let cardLimit = PAGE_SIZE, lastRows = [];

const has = v => v != null && v !== '' && v !== '-' && v !== '—';

function starHTML(i) {
  const on = !!FAVS[i.k];
  return `<button class="star" data-fav="${esc(i.k)}" aria-pressed="${on}"
    aria-label="${on ? '從最愛移除' : '加入最愛'}"
    title="${on ? '從最愛移除' : '加入最愛'}">${on ? '★' : '☆'}</button>`;
}

function tagsHTML(i) {
  return (i.new ? '<span class="pill new">新上架</span>' : '')
    + (i.chg ? `<span class="pill down">${esc(i.chg)}</span>` : '')
    + (i.dup > 1 ? `<span class="pill">${i.dup} 家</span>` : '')
    + (i.gone ? '<span class="pill gone">已不在目前名單</span>' : '');
}

/* 手機用卡片：14 欄的表格在 375px 螢幕要橫向滑 5 倍才看得完一列 */
function renderCards(rows) {
  document.getElementById('cards').innerHTML = rows.map(i => `
    <div class="card2" tabindex="0" role="link" data-url="${esc(i.url)}"
         aria-label="在 591 開啟：${esc(i.ti)}">
      <div class="c-top">
        <span class="c-stn"><i class="sdot" style="background:${colorOf(i.s)}"></i>${esc(i.s)}</span>
        <span class="c-dist">${i.d == null ? '' : i.d + ' m'}</span>
        ${starHTML(i)}
      </div>
      ${tagsHTML(i) ? `<div class="c-tags">${tagsHTML(i)}</div>` : ''}
      <div class="c-ti">${esc(i.ti)}</div>
      <div class="c-price">
        <b>${fmt(i.p)}</b><span class="u">萬</span>
        ${i.hi ? `<span class="pill rng">最高 ${fmt(i.hi)}</span>` : ''}
        <span class="u">${fmt(i.u)} 萬/坪 · ${fmt(i.a)} 坪</span>
      </div>
      <div class="c-meta">${
        [esc(i.c) + (has(i.t) ? ' · ' + esc(i.t) : ''),
         has(i.fl) ? esc(i.fl) : '',
         has(i.ag) ? esc(i.ag) : '',
         esc(i.dt) + (has(i.ad) ? ' ' + esc(i.ad) : '')]
        .filter(Boolean).map(x => `<span>${x}</span>`).join('')}</div>
    </div>`).join('');
}

function draw(keepLimit) {
  if (!keepLimit) cardLimit = PAGE_SIZE;
  let rows = (state.favOnly ? favRows() : DATA.items).filter(i =>
    (!state.station || i.s === state.station) &&
    (!state.cat || i.c === state.cat) &&
    (!state.q || (i.s + i.ad + i.ti + i.dt + i.t).toLowerCase().includes(state.q)));

  const k = state.sort, sgn = state.asc ? 1 : -1;
  rows = rows.slice().sort((a, b) => {
    const x = a[k], y = b[k];
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * sgn;
    return String(x).localeCompare(String(y), 'zh-Hant') * sgn;
  });

  lastRows = rows;
  const more = document.getElementById('more');
  if (MQ.matches) {
    renderCards(rows.slice(0, cardLimit));
    const rest = rows.length - cardLimit;
    more.hidden = rest <= 0;
    if (rest > 0) more.textContent = `顯示更多（還有 ${rest} 間）`;
  } else {
    more.hidden = true;
  }
  if (!MQ.matches) document.getElementById('tb').innerHTML = rows.map(i => `<tr tabindex="0" role="link"
    data-url="${esc(i.url)}" aria-label="在 591 開啟：${esc(i.ti)}" title="點一下在 591 開啟">
    <td class="favcol">${starHTML(i)}</td>
    <td class="stat">${i.new ? '<span class="pill new">新上架</span>' : ''}${
      i.chg ? `<span class="pill down">${esc(i.chg)}</span>` : ''}</td>
    <td><i class="sdot" style="background:${colorOf(i.s)}"></i>${esc(i.s)}</td>
    <td class="r num">${i.d == null ? '—' : i.d + ' m'}</td>
    <td>${esc(i.c)}</td><td>${esc(i.t) || '—'}</td>
    <td class="r num">${fmt(i.p)}${
      i.hi ? `<span class="pill rng" title="另有仲介開價較高，這是同一間房">最高 ${fmt(i.hi)}</span>` : ''}</td>
    <td class="r num">${fmt(i.u)}</td>
    <td class="r num">${fmt(i.a)}</td><td>${esc(i.fl) || '—'}</td>
    <td>${esc(i.ag) || '—'}</td><td>${esc(i.dt)}</td><td>${esc(i.ad) || '—'}</td>
    <td class="ti"><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.ti)}</a>${
      i.dup > 1 ? `<span class="pill">${i.dup} 家</span>` : ''}${
      i.gone ? '<span class="pill gone">已不在目前名單</span>' : ''}</td>
  </tr>`).join('');
  if (MQ.matches) document.getElementById('tb').innerHTML = '';

  const nFav = Object.keys(FAVS).length;
  document.getElementById('favchip').textContent = nFav ? `★ 只看最愛 (${nFav})` : '★ 只看最愛';
  const bar = document.getElementById('favbar');
  bar.hidden = !state.favOnly;
  if (state.favOnly) {
    const gone = rows.filter(r => r.gone).length;
    document.getElementById('favmsg').textContent =
      nFav === 0 ? '還沒有標記任何物件。點每一列最左邊的 ☆ 就會加進來。'
      : gone ? `${nFav} 間，其中 ${gone} 間已經不在目前名單`
      : `${nFav} 間`;
  }

  document.getElementById('empty').hidden = rows.length > 0;
  document.getElementById('shown').textContent =
    '顯示 ' + rows.length + ' / ' + (state.favOnly ? nFav : DATA.items.length) + ' 間';
  syncSortUI();
}

(function showAge() {
  const el = document.getElementById('age');
  if (!el || !DATA.generated) return;
  const hrs = (Date.now() - new Date(DATA.generated)) / 36e5;
  if (hrs < 0) return;
  const label = hrs < 1 ? '不到 1 小時前'
    : hrs < 24 ? Math.round(hrs) + ' 小時前'
    : Math.round(hrs / 24) + ' 天前';
  el.textContent = '（' + label + '）';
  if (hrs > 48) el.className = 'stale';   // 超過兩天就標色提醒資料可能過時
})();

/* 最愛的按鈕與工具列 */
document.getElementById('favchip').addEventListener('click', function () {
  state.favOnly = !state.favOnly;
  this.setAttribute('aria-pressed', state.favOnly);
  draw();
});

document.getElementById('favshare').addEventListener('click', async function () {
  const keys = Object.keys(FAVS);
  if (!keys.length) return;
  const url = location.origin + location.pathname + '?fav=' + keys.join('.');
  try {
    await navigator.clipboard.writeText(url);
    this.textContent = '已複製';
  } catch (e) {
    // 剪貼簿被擋時退回手動複製
    const ta = document.createElement('textarea');
    ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    this.textContent = document.execCommand('copy') ? '已複製' : '複製失敗，請手動複製網址';
    document.body.removeChild(ta);
  }
  setTimeout(() => { this.textContent = '複製最愛的連結'; }, 2200);
});

document.getElementById('favclear').addEventListener('click', function () {
  if (!Object.keys(FAVS).length) return;
  if (!confirm('確定要清空所有最愛嗎？')) return;
  FAVS = {}; saveFavs(); draw();
});

/* 手機的排序控制：卡片版沒有欄位標題可以點 */
const msort = document.getElementById('msort'), mdir = document.getElementById('mdir');
function syncSortUI() {
  msort.value = ['sv', 'p', 'u', 'a', 'd', 's'].includes(state.sort) ? state.sort : 'sv';
  mdir.textContent = state.asc ? '低→高' : '高→低';
}
msort.addEventListener('change', () => {
  state.sort = msort.value;
  state.asc = msort.value !== 'sv';        // 狀態預設高在前，其他預設低在前
  draw();
});
mdir.addEventListener('click', () => { state.asc = !state.asc; draw(); });

/* 換直/橫向或換裝置寬度時要重畫，卡片與表格才會跟著切換 */
MQ.addEventListener('change', () => draw());
document.getElementById('more').addEventListener('click', () => {
  cardLimit += PAGE_SIZE;
  draw(true);
});

/* 整列／整張卡片可點：不用滑到最右邊才找得到連結。
   委派在 document 上，表格與卡片共用同一套處理。 */
(function rowLinks() {
  const open = el => {
    const u = el && el.dataset.url;
    if (u) window.open(u, '_blank', 'noopener');
  };
  document.addEventListener('click', e => {
    const star = e.target.closest('.star');
    if (star) { toggleFav(star.dataset.fav); return; }        // 星星自己處理，不要開 591
    if (e.target.closest('a')) return;                        // 標題本來就是連結
    const row = e.target.closest('[data-url]');
    if (!row) return;
    if (String(getSelection())) return;                       // 使用者在選字，不要跳走
    open(row);
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const star = e.target.closest('.star');
    if (star) { e.preventDefault(); toggleFav(star.dataset.fav); return; }
    const row = e.target.closest('[data-url]');
    if (!row) return;
    e.preventDefault();
    open(row);
  });
})();

drawBoard();
document.querySelector('#tbl thead th[data-k="sv"]').setAttribute('aria-sort', 'descending');
draw();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { drawBoard(); draw(); });
</script>"""


def main():
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        found = sorted(glob.glob(os.path.join(OUT_DIR, "591_*.csv")))
        if not found:
            print("out/ 裡找不到 CSV，請先跑 python3 house591.py")
            return 1
        csv_path = found[-1]

    rows = load_rows(csv_path)
    stations_ref = json.load(open(os.path.join(BASE_DIR, "mrt_stations.json"), encoding="utf-8"))
    cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))

    raw_stamp = os.path.basename(csv_path).replace("591_", "").replace(".csv", "")
    iso = ""
    stamp = raw_stamp
    try:
        dt = datetime.strptime(raw_stamp, "%Y%m%d_%H%M")
        stamp = dt.strftime("%Y-%m-%d %H:%M")
        iso = dt.astimezone().isoformat()   # 帶時區，訪客在別的時區也算得對
    except ValueError:
        pass

    data = build(rows, stations_ref, cfg)
    html = render(data, stamp, iso)

    # share.html 給 Claude Artifact 用(外層 html/head 由平台補)
    share = os.path.join(OUT_DIR, "share.html")
    with open(share, "w", encoding="utf-8") as f:
        f.write(html)

    # index.html 是完整的獨立網頁：可直接寄給人開，也可丟 GitHub Pages / Vercel
    standalone = ('<!doctype html>\n<html lang="zh-Hant">\n<head>\n'
                  '<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
                  # 自用工具，不需要被搜尋引擎收錄
                  '<meta name="robots" content="noindex,nofollow">\n'
                  '</head>\n<body>\n' + html + '\n</body>\n</html>\n')
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(standalone)

    # docs/ 是 GitHub Pages 的發布目錄
    docs = os.path.join(BASE_DIR, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as f:
        f.write(standalone)
    open(os.path.join(docs, ".nojekyll"), "w").close()
    open(os.path.join(docs, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")

    print("來源 CSV : %s (%d 間)" % (csv_path, len(rows)))
    print("分享頁面 : %s" % share)
    print("靜態首頁 : %s" % os.path.join(OUT_DIR, "index.html"))
    print("Pages    : %s" % os.path.join(BASE_DIR, "docs", "index.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
