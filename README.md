# 591 捷運沿線置產工具

抓 591 上指定捷運站周邊的物件售價，產出 CSV、本機報告，以及一頁可分享的網頁。
只用 Python 3 標準函式庫，**不需要 pip install 任何套件**。

目前設定：台北市 17 個站的 **一樓店面 / 土地 / 透天**，30 坪以上、離站 1000 公尺內。

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
| `merge_duplicates` | 同一間房被多家仲介刊登時合併成一筆（強烈建議開著） |
| `request_delay_sec` | 每頁之間的間隔秒數。請不要調太低 |

## 產出

```
out/591_日期_時間.csv    Excel 直接開（UTF-8 BOM，不會亂碼）
out/591_日期_時間.html   本機看的完整報告
out/share.html          分享頁（給 Claude Artifact 用）
out/index.html          分享頁（完整獨立網頁，給 Vercel 等靜態空間用）
data/snapshot.json      上次結果，用來比對新上架 / 降價 / 已下架
```

第一次跑會建立比對基準，**第二次以後**才會標出新上架與降價。

## 幾個實務重點

- **重複刊登很多。** 同一間房常有 3～5 家仲介同時刊登。工具用「行政區＋類別＋坪數＋總價」當指紋合併，保留離站最近那筆，其餘記在「其他仲介」欄。以這次的資料為例：991 筆刊登 → 符合條件 568 筆 → 實際只有 363 間。不合併的話筆數和中位數都會嚴重灌水。
- **591 的「捷運站附近」收到 2 公里**，走路要 25 分鐘以上。`max_distance_m` 就是為了這個而設。
- **一樓店面含 B1 的物件**，591 的樓層欄會顯示成 `B1/7F`，那是「B1＋1樓」的店面，不是地下室店面，屬正常結果。
- **成交價請以內政部實價登錄為準**，591 上是開價。

## 部署到 Vercel（給夥伴看）

`out/index.html` 是完整的獨立網頁，把 `out/` 整個目錄當靜態網站丟上去就會動，裡面已附 `vercel.json`。

這台電腦目前**沒有裝 Node/npm**，所以 Vercel CLI 不能直接用。兩條路：

**A. 接 GitHub（推薦，之後更新只要 push）**

```bash
cd ~/Documents/Github/house591 && git init && git add -A && git commit -m "591 捷運沿線置產工具"
```

推到 GitHub 後，在 Vercel → Add New Project → 匯入這個 repo，Root Directory 選 `out`，Framework 選 Other，就完成了。以後每次跑完 `make_share_page.py` 再 commit + push，網站就會自動更新。

**B. 裝 Node 後用 CLI**

```bash
brew install node && npx vercel deploy ~/Documents/Github/house591/out --prod
```

第一次會開瀏覽器要你登入 Vercel。

> 注意：Vercel 的正式網址預設是**公開**的，任何拿到網址的人都看得到。若只想給特定人看，用 Vercel 的 Deployment Protection，或改用 Claude Artifact 的分享連結。

## 資料來源

591 網站前端自己在呼叫的公開介面（`bff-house.591.com.tw/v1/web/sale/list`）。
這是自用小工具，請維持 `request_delay_sec` 的低頻率，不要拿去大量爬。
