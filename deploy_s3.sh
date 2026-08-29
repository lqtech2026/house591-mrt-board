#!/usr/bin/env bash
#
# 把 docs/ 部署成 AWS S3 靜態網站。
#
#   ./deploy_s3.sh                      # 用預設 bucket 名稱
#   ./deploy_s3.sh my-bucket-name       # 自訂 bucket 名稱
#   AWS_REGION=us-east-1 ./deploy_s3.sh # 自訂區域
#
# 前提：先跑過 aws configure 設定好憑證。
#
set -euo pipefail

BUCKET="${1:-house591-mrt-board}"
REGION="${AWS_REGION:-ap-northeast-1}"
SRC="$(cd "$(dirname "$0")" && pwd)/docs"

command -v aws >/dev/null || { echo "找不到 aws，請先 brew install awscli"; exit 1; }

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS 憑證還沒設定。請先執行："
  echo "    aws configure"
  echo "需要 Access Key ID / Secret Access Key，在 AWS Console 的 IAM 建立。"
  exit 1
fi
echo "帳號：$(aws sts get-caller-identity --query Account --output text) ｜ 區域：$REGION"

# 1. 建 bucket（已存在就跳過）
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "bucket $BUCKET 已存在，沿用"
else
  echo "建立 bucket $BUCKET …"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION"
  fi
fi

# 2. 靜態網站要能公開讀取，得先關掉預設的封鎖
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

# 3. 公開讀取政策
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicRead",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::$BUCKET/*"
  }]
}
JSON
)"

# 4. 開啟靜態網站代管
aws s3api put-bucket-website --bucket "$BUCKET" --website-configuration \
  '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}'

# 5. 上傳。HTML 不要被快取住，不然更新後看到舊的
aws s3 sync "$SRC" "s3://$BUCKET/" --delete \
  --cache-control "public, max-age=0, must-revalidate" \
  --content-type "text/html; charset=utf-8" \
  --exclude "*" --include "*.html"
aws s3 sync "$SRC" "s3://$BUCKET/" --exclude "*.html"

URL="http://$BUCKET.s3-website-$REGION.amazonaws.com"
echo
echo "完成：$URL"
echo
echo "注意：S3 網站端點只有 HTTP，沒有 HTTPS。要 HTTPS 得再掛 CloudFront。"
