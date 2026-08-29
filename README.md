# 591 捷運沿線置產工具

抓 591 上指定捷運站周邊的物件售價，產出 CSV、本機報告，以及一頁可分享的網頁。
只用 Python 3 標準函式庫，**不需要 pip install 任何套件**。

目前設定：台北市 17 個站的 **一樓店面 / 土地 / 透天**，30 坪以上、離站 1000 公尺內、排除地下室。

## 用法

```bash
cd ~/Documents/Github/house591

python3 house591.py              # 抓資料 → out/*.csv + out/*.html
python3 make_share_page.py       # 把最新 CSV 轉成分享頁 → out/share.html + out/index.html

python3 house591.py --dry-run    # 只看各條件有幾筆，不抓明細（很快）
python3 house591.py --stations   # 列出全台可用的捷運站名
```

## 改條件

只改 `config.json`，不用動程式：

| 欄位 | 說明 |
|---|---|
| `stations` | 要查的捷運站，站名照 `--stations` 列出來的寫 |
| `categories` | 一樓店面 / 店面 / 土地 / 透天 / 別墅 / 住宅 / 公寓 / 電梯大樓 / 華廈 / 住辦 / 辦公 / 套房 / 廠房 / 車位 / 法拍屋 / 其他 |
| `min_area_ping` / `max_area_ping` | 坪數範圍 |
| `max_distance_m` | 離站距離上限。591 本身收到 2000 公尺，預設收緊到 1000 |
| `min_price_wan` / `max_price_wan` | 總價範圍（萬元） |
| `min_unit_price_wan` | 單價下限，用來擋掉混進來的「店面頂讓」等非售屋物件 |
| `exclude_basement` | 排除樓層 B 開頭（B1、B2…）的物件。預設開啟 |
| `merge_duplicates` | 同一間房被多家仲介刊登時合併成一筆（強烈建議開著） |
| `request_delay_sec` | 每頁之間的間隔秒數。請不要調太低 |

## 產出

```
out/591_日期_時間.csv    Excel 直接開（UTF-8 BOM，不會亂碼）
out/591_日期_時間.html   本機看的完整報告
out/share.html          分享頁（給 Claude Artifact 用）
docs/index.html         GitHub Pages 發布的版本
out/index.html          分享頁（完整獨立網頁，給 Vercel 等靜態空間用）
data/snapshot.json      上次結果，用來比對新上架 / 降價 / 已下架
```

第一次跑會建立比對基準，**第二次以後**才會標出新上架與降價。

## 幾個實務重點

- **重複刊登很多。** 同一間房常有 3～5 家仲介同時刊登。工具用「行政區＋類別＋坪數＋總價」當指紋合併，保留離站最近那筆，其餘記在「其他仲介」欄。以這次的資料為例：991 筆刊登 → 符合條件 568 筆 → 實際只有 363 間。不合併的話筆數和中位數都會嚴重灌水。
- **591 的「捷運站附近」收到 2 公里**，走路要 25 分鐘以上。`max_distance_m` 就是為了這個而設。
- **591 的「一樓店面」會混進 B1 物件**（樓層顯示成 `B1/7F`，是 B1＋1樓的複合店面）。
  `exclude_basement` 預設會把它們濾掉，只留純一樓。透天的 `整棟` / `1F~2F` 不受影響。
- **成交價請以內政部實價登錄為準**，591 上是開價。

## 給夥伴看（免登入的公開網址）

`docs/index.html` 是完整的獨立網頁，**GitHub Pages 直接指到 `docs/` 就會動**。
本機 repo 已經 commit 好了，剩下兩步：

```bash
cd ~/Documents/Github/house591 && gh repo create house591-mrt-board --public --source=. --push
```

```bash
gh api -X POST repos/lqtech2026/house591-mrt-board/pages -f "source[branch]=main" -f "source[path]=/docs"
```

約一分鐘後網址就會是：
**https://lqtech2026.github.io/house591-mrt-board/**

任何人點開就能看，不用登入、不用裝東西。（第二步也可以在 repo 的
Settings → Pages → Source 選 `main` + `/docs` 用點的。）

### 自動更新（在你自己的 Mac 上排程）

**不能用 GitHub Actions** —— 實測過，591 會對資料中心 IP 直接回 `403 Forbidden`。
抓取必須從家用網路出去，所以排程放在本機：

```bash
cp ~/Documents/Github/house591/com.jeff.house591.update.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.jeff.house591.update.plist
```

每天 09:00 會自動重抓、重產分享頁、有變動才 commit + push，GitHub Pages 隨即更新。
Mac 在 09:00 睡著的話，醒來後 launchd 會補跑。紀錄在 `logs/update.log`。

停用：`launchctl unload ~/Library/LaunchAgents/com.jeff.house591.update.plist`

### 手動更新

```bash
cd ~/Documents/Github/house591 && ./update.sh
```

> `update.sh` 固定用 `/usr/bin/python3`。Homebrew 的 python3 帶 OpenSSL 3.x，
> 會因為 591 憑證缺少 Subject Key Identifier 而連不上；系統 python3 的 LibreSSL 沒這問題。

### 資料新舊

網頁**不會即時去撈 591**，那是靜態快照。標題列會顯示資料是幾小時前抓的，
超過兩天變色提醒。`data/snapshot.json` 有進版控，「新上架 / 降價」的比對能跨次延續；
591 分頁結果會些微跳動，所以連續兩次沒出現才判定下架，避免每天冒出假異動。

### 其他選項

- **直接傳檔案（$0）**：`out/index.html` 是自包的單一檔案，用 LINE / Email 傳過去，
  對方瀏覽器開就能看，連網路都不用。缺點是每次更新要重傳。
- **AWS（S3 + CloudFront）—— 會產生費用，這個用途不建議**：
  `awscli` 已裝好，`deploy_s3.sh` 也寫好了（`./deploy_s3.sh --cloudfront` 可拿到 HTTPS 網址）。
  但 AWS **必須綁信用卡**，帳單金額雖然小卻不是零，設定錯了還可能被灌流量。
  純粹分享一頁靜態網站沒有理由付這個錢，腳本留著當備案就好。
- **Vercel**：免費方案可用，但這台電腦沒裝 Node，要先 `brew install node`，
  再 `npx vercel deploy out --prod`（第一次會要你登入）。`out/vercel.json` 已備好。

> `docs/` 裡放了 `robots.txt` 與 `noindex`，網址是公開的但不會被搜尋引擎收錄。

## 資料來源

591 網站前端自己在呼叫的公開介面（`bff-house.591.com.tw/v1/web/sale/list`）。
這是自用小工具，請維持 `request_delay_sec` 的低頻率，不要拿去大量爬。
