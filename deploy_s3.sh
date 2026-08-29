#!/usr/bin/env bash
#
# 把 docs/ 部署成 AWS 靜態網站。
#
#   ./deploy_s3.sh                        # 只用 S3（HTTP，最快）
#   ./deploy_s3.sh --cloudfront           # S3 + CloudFront（有 HTTPS）
#   ./deploy_s3.sh --cloudfront my-bucket # 自訂 bucket 名稱
#   AWS_REGION=us-east-1 ./deploy_s3.sh   # 自訂區域
#
# 前提：先跑過 aws configure 設定好憑證。
# 可重複執行：bucket 與 CloudFront distribution 都會沿用既有的，不會重建。
#
set -euo pipefail

USE_CF=0
BUCKET=""
for arg in "$@"; do
  case "$arg" in
    --cloudfront) USE_CF=1 ;;
    -*) echo "不認得的參數：$arg"; exit 1 ;;
    *)  BUCKET="$arg" ;;
  esac
done
BUCKET="${BUCKET:-house591-mrt-board}"
REGION="${AWS_REGION:-ap-northeast-1}"
SRC="$(cd "$(dirname "$0")" && pwd)/docs"
CF_COMMENT="house591-mrt-board"

command -v aws >/dev/null || { echo "找不到 aws，請先 brew install awscli"; exit 1; }

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS 憑證還沒設定。請先執行："
  echo "    aws configure"
  echo "需要 Access Key ID / Secret Access Key，在 AWS Console 的 IAM 建立。"
  exit 1
fi
echo "帳號：$(aws sts get-caller-identity --query Account --output text) ｜ 區域：$REGION"

# S3 靜態網站端點：舊區域用 dash，新區域用 dot
case "$REGION" in
  us-east-1|us-west-1|us-west-2|ap-southeast-1|ap-southeast-2|ap-northeast-1|eu-west-1|sa-east-1|us-gov-west-1)
    WEB_HOST="$BUCKET.s3-website-$REGION.amazonaws.com" ;;
  *)
    WEB_HOST="$BUCKET.s3-website.$REGION.amazonaws.com" ;;
esac

# ---------------------------------------------------------------- S3

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "bucket $BUCKET 已存在，沿用"
else
  echo "建立 bucket $BUCKET …"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
fi

# 靜態網站要能公開讀取，得先關掉預設的封鎖
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

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

aws s3api put-bucket-website --bucket "$BUCKET" --website-configuration \
  '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}'

# HTML 不要被快取住，不然更新後看到舊的
echo "上傳 $SRC …"
aws s3 sync "$SRC" "s3://$BUCKET/" --delete \
  --cache-control "public, max-age=0, must-revalidate" \
  --content-type "text/html; charset=utf-8" \
  --exclude "*" --include "*.html" >/dev/null
aws s3 sync "$SRC" "s3://$BUCKET/" --exclude "*.html" >/dev/null

if [ "$USE_CF" = 0 ]; then
  echo
  echo "完成：http://$WEB_HOST"
  echo "（S3 網站端點只有 HTTP。要 HTTPS 請加 --cloudfront）"
  exit 0
fi

# ---------------------------------------------------------------- CloudFront

echo
DIST_ID="$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='$CF_COMMENT'].Id | [0]" \
  --output text 2>/dev/null || true)"

if [ -z "$DIST_ID" ] || [ "$DIST_ID" = "None" ]; then
  echo "建立 CloudFront distribution …"
  # 以 S3 網站端點當自訂來源：目錄自動補 index.html 的行為由 S3 處理，設定最單純。
  # CachingOptimized 會尊重來源的 Cache-Control，我們的 HTML 是 max-age=0，所以不會卡舊版。
  CFG="$(cat <<JSON
{
  "CallerReference": "$CF_COMMENT-$(date +%s)",
  "Comment": "$CF_COMMENT",
  "Enabled": true,
  "HttpVersion": "http2and3",
  "PriceClass": "PriceClass_200",
  "DefaultRootObject": "index.html",
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "s3-website",
      "DomainName": "$WEB_HOST",
      "CustomOriginConfig": {
        "HTTPPort": 80,
        "HTTPSPort": 443,
        "OriginProtocolPolicy": "http-only",
        "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "s3-website",
    "ViewerProtocolPolicy": "redirect-to-https",
    "Compress": true,
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"],
      "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}
    },
    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }
}
JSON
)"
  OUT="$(aws cloudfront create-distribution --distribution-config "$CFG" \
        --query 'Distribution.[Id,DomainName]' --output text)"
  DIST_ID="$(echo "$OUT" | cut -f1)"
  CF_HOST="$(echo "$OUT" | cut -f2)"
  echo "distribution $DIST_ID 已建立"
  echo
  echo "完成：https://$CF_HOST"
  echo "第一次部署要 5～15 分鐘才會生效，這段期間開會是錯誤頁，屬正常。"
  echo "進度：aws cloudfront wait distribution-deployed --id $DIST_ID"
else
  CF_HOST="$(aws cloudfront get-distribution --id "$DIST_ID" \
             --query 'Distribution.DomainName' --output text)"
  echo "沿用既有 distribution $DIST_ID，清快取 …"
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
    --query 'Invalidation.Id' --output text >/dev/null
  echo
  echo "完成：https://$CF_HOST"
  echo "快取清除約 1～2 分鐘生效。"
fi
