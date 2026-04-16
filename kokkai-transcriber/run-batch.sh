#!/usr/bin/env bash
# 国会TV バッチ処理 → サイトビルド → git push
#
# 使い方:
#   ./run-batch.sh                          # 2026-02-01〜今日、衆議院、4並列
#   ./run-batch.sh --since 2026-04-01       # 4月以降のみ
#   ./run-batch.sh --workers 2              # 2並列（API制限対策）
#   ./run-batch.sh --no-push                # pushなし（ローカル確認用）
#   ./run-batch.sh --dry-run                # 対象一覧のみ表示
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SITE_DIR="$REPO_ROOT/site"

# デフォルト値
SINCE="2026-02-01"
WORKERS=4
CHAMBER="shugiin"
NO_PUSH=""
DRY_RUN=""
EXTRA_ARGS=()

# 引数パース
while [[ $# -gt 0 ]]; do
  case $1 in
    --since) SINCE="$2"; shift 2 ;;
    --until) EXTRA_ARGS+=("--until" "$2"); shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --chamber) CHAMBER="$2"; shift 2 ;;
    --no-push) NO_PUSH="--no-push"; shift ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

echo "================================================"
echo "  国会TV バッチ処理"
echo "  院: $CHAMBER  開始日: $SINCE  並列: $WORKERS"
echo "================================================"

# Step 1: パイプラインバッチ実行
cd "$SCRIPT_DIR"
uv run python -m src.batch \
  --chamber "$CHAMBER" \
  --since "$SINCE" \
  --workers "$WORKERS" \
  --no-push \
  $DRY_RUN \
  "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"

if [[ -n "$DRY_RUN" ]]; then
  exit 0
fi

# Step 2: サイトビルド（prebuild で generate-api.ts が自動実行される）
echo ""
echo "================================================"
echo "  サイトビルド (generate-api.ts → astro build)"
echo "================================================"
cd "$SITE_DIR"
npm run build

# Step 3: git commit + push
if [[ -z "$NO_PUSH" ]]; then
  echo ""
  echo "================================================"
  echo "  git commit + push"
  echo "================================================"
  cd "$REPO_ROOT"

  # data/ と site/ の変更をステージ
  git add data/

  SESSIONS=$(git diff --cached --stat -- data/ | tail -1 | sed 's/^ *//')
  if [[ -z "$SESSIONS" ]] || [[ "$SESSIONS" == *"0 files changed"* ]]; then
    echo "No new data to commit"
  else
    DATE_RANGE="$SINCE〜$(date +%Y-%m-%d)"
    git commit -m "data: batch $CHAMBER $DATE_RANGE ($SESSIONS)"
    git push origin main
    echo "Pushed to origin/main"
  fi
else
  echo ""
  echo "================================================"
  echo "  --no-push: スキップ"
  echo "  手動で push する場合:"
  echo "    cd $REPO_ROOT"
  echo "    git add data/"
  echo "    git commit -m 'data: batch update'"
  echo "    git push origin main"
  echo "================================================"
fi
