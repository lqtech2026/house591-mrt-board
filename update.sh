#!/usr/bin/env bash
#
# 重抓 591 資料、重產分享頁、有變動就 push（GitHub Pages 會自動重新發布）。
#
#   ./update.sh
#
# 這支要在你自己的機器上跑，不能放 GitHub Actions —— 591 會對資料中心 IP 回 403。
#
set -euo pipefail
cd "$(dirname "$0")"

# launchd 排程執行時 PATH 很精簡，這裡補齊。
# /usr/bin 要在 /opt/homebrew/bin 前面 —— 見下面 PY 的說明。
export PATH="/usr/bin:/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"

# 一定要用系統的 python3。Homebrew 的 python3 帶 OpenSSL 3.x，會因為
# 591 的憑證缺少 Subject Key Identifier 而拒絕連線；系統 python3 用
# LibreSSL 則沒問題。要換直譯器就設環境變數 PYTHON。
PY="${PYTHON:-/usr/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"

echo "───────── $(date '+%Y-%m-%d %H:%M:%S') ─────────"

"$PY" house591.py
"$PY" make_share_page.py

git add docs/ data/snapshot.json
if git diff --cached --quiet; then
  echo "資料沒有變動，不用 push"
  exit 0
fi

git commit -q -m "自動更新 591 資料 $(date '+%Y-%m-%d %H:%M')"
git push -q
echo "已推送，GitHub Pages 約一分鐘後更新"
