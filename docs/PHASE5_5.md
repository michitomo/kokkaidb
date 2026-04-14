# Phase 5.5: Phase 5 残存タスク整理

> **目的**: Phase 5（ダッシュボード・ビジュアライゼーション）の実装完了後、Phase 6 に進む前に消化すべきタスクを整理する。
> **前提**: Phase 5 の全コンポーネント・ページ・テストは実装済み。ビルド・テストともにパス。ただし未コミット・未確認事項あり。

---

## 1. Git コミット（必須・即時）

Phase 5 の全変更が unstaged / untracked のまま残っている。Phase 3・4 の変更も混在しているため、フェーズごとに分けてコミットする。

### 対象ファイル

**Phase 3（参議院対応）相当の変更:**
```
kokkai-transcriber/src/scrapers/sangiin.py          (新規)
kokkai-transcriber/src/audio/sangiin_resolver.py     (新規)
kokkai-transcriber/tests/test_sangiin_scraper.py     (新規)
kokkai-transcriber/tests/test_sangiin_resolver.py    (新規)
kokkai-transcriber/tests/fixtures/sangiin_*.html     (新規)
kokkai-transcriber/tests/fixtures/mediasp_player.js  (新規)
kokkai-transcriber/src/models.py                     (変更)
kokkai-transcriber/src/pipeline.py                   (変更)
kokkai-transcriber/src/speaker_tagger.py             (変更)
kokkai-transcriber/tests/test_pipeline.py            (変更)
kokkai-transcriber/tests/test_speaker_tagger.py      (変更)
```

**Phase 4（フィルタ・エクスポート）相当の変更:**
```
site/src/components/FilterPanel.jsx                  (新規)
site/src/components/FilteredQAList.jsx               (新規)
site/src/components/MultiSelect.jsx                  (新規)
site/src/lib/tsv-export.ts                           (新規)
site/src/components/__tests__/                       (新規)
site/src/lib/__tests__/                              (新規)
site/src/pages/browse.astro                          (変更)
site/vitest.config.ts                                (新規)
site/vitest.setup.ts                                 (新規)
site/package.json                                    (変更)
site/package-lock.json                               (変更)
```

**Phase 5（ダッシュボード）の変更:**
```
site/scripts/generate-api.ts                         (新規)
site/scripts/__tests__/generate-dashboard.test.ts    (新規)
site/src/layouts/DashboardLayout.astro               (新規)
site/src/pages/dashboard/index.astro                 (新規)
site/src/pages/dashboard/topics.astro                (新規)
site/src/pages/dashboard/tracker.astro               (新規)
site/src/pages/dashboard/speakers.astro              (新規)
site/src/components/MonthlyTrendChart.jsx             (新規)
site/src/components/SessionCalendar.jsx               (新規)
site/src/components/TopicHeatmap.jsx                  (新規)
site/src/components/EvasionTracker.jsx                (新規)
site/src/components/CommitmentTracker.jsx              (新規)
site/src/components/TimelineView.jsx                  (新規)
site/src/components/QAPairCard.astro                  (変更)
site/src/layouts/BaseLayout.astro                     (変更)
site/src/pages/[chamber]/.../[slug].astro             (変更)
site/tests/                                           (新規: フィクスチャ含む)
```

### コミット戦略

```bash
# 1. Phase 3: 参議院スクレイパー・リゾルバー
git add kokkai-transcriber/src/scrapers/sangiin.py \
        kokkai-transcriber/src/audio/sangiin_resolver.py \
        kokkai-transcriber/tests/test_sangiin_*.py \
        kokkai-transcriber/tests/fixtures/sangiin_*.html \
        kokkai-transcriber/tests/fixtures/mediasp_player.js \
        kokkai-transcriber/src/models.py \
        kokkai-transcriber/src/pipeline.py \
        kokkai-transcriber/src/speaker_tagger.py \
        kokkai-transcriber/tests/test_pipeline.py \
        kokkai-transcriber/tests/test_speaker_tagger.py
git commit -m "Implement Phase 3: Sangiin scraper and audio resolver"

# 2. Phase 4: フィルタ・エクスポート
git add site/src/components/FilterPanel.jsx \
        site/src/components/FilteredQAList.jsx \
        site/src/components/MultiSelect.jsx \
        site/src/lib/tsv-export.ts \
        site/src/components/__tests__/ \
        site/src/lib/__tests__/ \
        site/src/pages/browse.astro \
        site/vitest.config.ts \
        site/vitest.setup.ts \
        site/package.json \
        site/package-lock.json
git commit -m "Implement Phase 4: Filter panel, multi-select, and TSV export"

# 3. Phase 5: ダッシュボード
git add site/scripts/ \
        site/src/layouts/DashboardLayout.astro \
        site/src/pages/dashboard/ \
        site/src/components/MonthlyTrendChart.jsx \
        site/src/components/SessionCalendar.jsx \
        site/src/components/TopicHeatmap.jsx \
        site/src/components/EvasionTracker.jsx \
        site/src/components/CommitmentTracker.jsx \
        site/src/components/TimelineView.jsx \
        site/src/components/QAPairCard.astro \
        site/src/layouts/BaseLayout.astro \
        "site/src/pages/[chamber]/[year]/[month]/[day]/[slug].astro" \
        site/tests/
git commit -m "Implement Phase 5: Dashboard, visualizations, and session timeline"
```

---

## 2. `.gitignore` 整備（必須・即時）

`site/public/api/` はビルド生成物（`generate-api.ts` が出力）。リポジトリに混入させない。

### 対処

`site/.gitignore` に以下を追記:

```
# build-generated API data
public/api/
```

コミット前に実施すること。

---

## 3. ブラウザ目視確認（必須・コミット後）

`npm run dev` でローカルサーバーを起動し、以下のチェックリストを消化する。

### チェックリスト

| # | ページ | 確認項目 | 状態 |
|---|--------|----------|------|
| 1 | `/dashboard` | サマリカード4枚が表示される | [ ] |
| 2 | `/dashboard` | MonthlyTrendChart が衆参別棒グラフを表示 | [ ] |
| 3 | `/dashboard` | SessionCalendar のグリッドが描画される | [ ] |
| 4 | `/dashboard` | 最近のセッション5件・トップトピックが表示される | [ ] |
| 5 | `/dashboard` | サブページナビカード4枚のリンクが正しい | [ ] |
| 6 | `/dashboard/topics` | TopicHeatmap の色グラデーションが白→青 | [ ] |
| 7 | `/dashboard/topics` | 院フィルタ（全体/衆/参）切替が動作 | [ ] |
| 8 | `/dashboard/topics` | EvasionTracker の3色スタックバーが表示 | [ ] |
| 9 | `/dashboard/topics` | ソート切替（回避度順/件数順）が動作 | [ ] |
| 10 | `/dashboard/tracker` | CommitmentTracker のカード一覧が表示 | [ ] |
| 11 | `/dashboard/tracker` | テキスト検索・院フィルタ・トピックグルーピングが動作 | [ ] |
| 12 | `/dashboard/tracker` | ソースリンクが正しいセッション詳細ページへ遷移 | [ ] |
| 13 | `/dashboard/speakers` | 発言者テーブルが表示される | [ ] |
| 14 | `/dashboard/speakers` | 回避度スコアの色分けが正しい | [ ] |
| 15 | セッション詳細 | TimelineView が `utterances.json` 存在時のみ表示 | [ ] |
| 16 | 全ダッシュボード | タブバーのアクティブ状態が正しいページをハイライト | [ ] |
| 17 | 全ダッシュボード | モバイル表示（375px幅）でレイアウト破綻なし | [ ] |
| 18 | グローバルナビ | 「ダッシュボード」リンクが `/dashboard` へ遷移 | [ ] |
| 19 | 全ページ | 出所明示（フッター）が表示される | [ ] |

### 空データ状態の確認

現在 `data/` には1セッション分のみ。以下の空状態UIが適切に表示されることを確認:

- ヒートマップ: セルが1〜3個のみでも破綻しない
- カレンダー: 色付きセルが1日分のみ
- EvasionTracker: 該当データ少数でもグラフ表示
- CommitmentTracker: 0件の場合「約束事項データが蓄積されると…」メッセージ

---

## 4. Phase 1 パイプライン実行（推奨・Phase 6 前に）

Phase 1〜4 のコードは実装済みだが、実際のデータ処理は未実行。`data/` 配下にはテスト用の1セッション分しかない。

Phase 6 の BYOK 分析機能（答弁比較・フォローアップ提案等）は Q&A データの存在が前提。ダッシュボードの意味ある表示にも複数セッションが必要。

### 最低限の実行計画

```bash
# 衆議院 PoC セッション（ARCH.md で指定）
docker compose run --rm transcriber python -m src.pipeline \
  --chamber shugiin --session-id 56149

# 追加で2〜3セッション処理すると、ダッシュボードの見栄えが改善
docker compose run --rm transcriber python -m src.pipeline \
  --chamber shugiin --session-id 56200
```

**前提条件:**
- Docker / docker compose が動作すること
- `kokkai-transcriber/.env` に `DEEPINFRA_API_KEY` が設定済みであること
- ffmpeg がDockerイメージに含まれていること

**注意**: APIコストが発生する（Whisper $0.0002/min + DeepSeek V3.2）。1セッション約3時間として概算 $0.05〜0.10 程度。

---

## 5. PHASE5.md Step 9 チェックリスト残項目（推奨）

PHASE5.md の Step 9（統合テスト + ビジュアルレビュー）に記載のチェック項目のうち、実データがないと確認できない項目:

- [ ] `/dashboard` — サマリカードの数値が `data/` 内のセッション数と一致
- [ ] `/dashboard/topics` — セルクリックで browse ページの正しいフィルタ結果へ遷移
- [ ] `/dashboard/tracker` — ソースリンクが正しいセッションの正しいQ&Aペアへ飛ぶ
- [ ] セッション詳細ページのタイムラインビューが発言順に表示される
- [ ] タイムラインのバークリックで発言テキスト展開 + 動画リンクが機能
- [ ] 答弁回避度の3色スタックが合計件数と一致

これらはタスク4（パイプライン実行）の後に確認する。

---

## 6. Pagefind 除外の確認（推奨）

ダッシュボードページが検索インデックスに含まれないことを確認する。

```bash
cd site
npm run build
npx pagefind --site dist --glob "**/*.html"
# → "Indexed N pages" の N にダッシュボードページが含まれないこと
# ダッシュボードページは data-pagefind-ignore 属性により除外される
```

---

## 優先順位まとめ

| 優先度 | タスク | 所要時間 | ブロッカー |
|--------|--------|----------|------------|
| P0 | `.gitignore` に `public/api/` 追加 | 1分 | なし |
| P0 | Phase 3/4/5 を分割コミット | 10分 | .gitignore 完了後 |
| P1 | ブラウザ目視確認（19項目） | 30分 | コミット後 |
| P1 | Pagefind 除外確認 | 5分 | なし |
| P2 | Phase 1 パイプライン実行（実データ生成） | 1〜2時間 | Docker + API Key |
| P2 | Step 9 残チェックリスト消化 | 30分 | 実データ生成後 |

---

## Phase 6 への移行条件

以下がすべて完了していれば Phase 6 に着手可能:

1. Phase 5 の全変更がコミット済み
2. `npm run build` と `npm test` がパス（現在パス済み）
3. ブラウザ目視確認で重大な表示崩れがない
4. （望ましい）`data/` に2セッション以上の実データがある
