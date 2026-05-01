# 99. 優先順位ロードマップ

[← 戻る](README.md)

各章の指摘を、**衆議院本格稼働前に必ず潰すべき P0**、**稼働後 1 ヶ月で潰すべき P1**、**Tier 1 着手前に整えたい P2**、**長期 P3** に分類する。

判定軸:
- **影響範囲**: 何人のユーザー／何ページに影響するか
- **修正コスト**: 工数（S = 半日 / M = 数日 / L = 数週間）
- **リスク**: 法的・社会的・データ品質のいずれの軸で問題になるか

---

## P0 — 本格稼働前マスト（推定: 1〜2 週間スプリント 1 本）

| # | 項目 | 章 | コスト | 影響範囲 | リスク種別 |
|---|------|----|------|--------|----------|
| 1 | トピックフィルタの語彙ズレを修正（ヒートマップ → 一覧で 0 件問題） | [02.1](02-cross-cutting-issues.md) | M | 全トピック導線 | 信用 |
| 2 | 「LLM 自動評価」注記を全画面フッタに追加 | [09.2](09-trust-transparency.md) | S | 全画面 | 法的 |
| 3 | 「方法論」ページ（`/about/methodology`）を新設し、回避度の定義・閾値・サンプルサイズの注意を載せる | [05.2](05-qa-quality-metrics.md) [09.1](09-trust-transparency.md) | M | リファレンス | 法的 |
| 4 | 発言者分析: `totalAnswers < 10` の除外しきい値、棒にサンプルサイズ併記、委員長の除外 | [04.3](04-dashboard.md) [05.4](05-qa-quality-metrics.md) | S | ダッシュボード | データ品質 |
| 5 | モバイル `/browse` のフィルタ折りたたみ修正 | [08.1](08-mobile-accessibility.md) | S | モバイル全体 | UX |
| 6 | フィルタ結果 0 件時の「条件 1 つ外せば N 件」サジェスト | [06.1](06-filtering-search.md) | M | /browse | UX |
| 7 | ホーム・/browse・セッション詳細フィルタを 1 コンポーネントに集約（QAFeed） | [03.1](03-information-architecture.md) | L | コア | 保守性 |
| 8 | 役割フィルタを「発言タイプ × 答弁者属性」の 2 軸に分割 | [06.2](06-filtering-search.md) | S | /browse | UX |
| 9 | settings ページの「Phase 6 で…」表記を「準備中」リッチデザインに置き換え or ナビから外す | [03.6](03-information-architecture.md) | XS | settings | UX |
| 10 | 用語ラベルの強さを下げる（「回避度高」→「論点に直接触れていない」等） | [05.3](05-qa-quality-metrics.md) | S | Q&A カード | 法的 |

**P0 完了の判定基準（ローンチクライテリア）**
- ヒートマップの全クリックでフィルタ結果が 0 件以外になる
- フッタに LLM 注記、`/about/methodology` がアクセス可能
- モバイルでフィルタが折りたたまれている
- 発言者分析でサンプル不足の警告が見える
- 「LLM 評価」の単語がトップ・ダッシュボードの少なくとも 1 箇所に出ている

---

## P1 — 稼働後 1 ヶ月以内（推定: スプリント 2〜3 本）

| # | 項目 | 章 | コスト |
|---|------|----|------|
| 11 | 発言者名の正規化（議員 ID + 役職 alias 辞書） | [02.4](02-cross-cutting-issues.md) | M |
| 12 | 「不明」委員会・空文字フィールドの除外 | [02.5](02-cross-cutting-issues.md) | S |
| 13 | SessionCalendar → /browse の `?date=` 対応 | [02.6](02-cross-cutting-issues.md) | XS |
| 14 | 約束トラッカーの status 拡張（unverified / restated / progress / realized） | [04.4](04-dashboard.md) | M |
| 15 | 発言者一覧のページネーション・サンプル不足折りたたみ・役職バッジ | [04.5](04-dashboard.md) | M |
| 16 | ダッシュボード概要を「ハイライト」「異常値」中心に再構成、ナビカード 3 枚を削除 | [04.1](04-dashboard.md) | M |
| 17 | ヒートマップを `<table>` ベース＋固定タクソノミーに変更 | [04.2](04-dashboard.md) [08.5](08-mobile-accessibility.md) | M |
| 18 | レイアウト最大幅を 1 本に統合（960 → 1080px） | [03.4](03-information-architecture.md) | XS |
| 19 | フッタに「データ最終更新」表示 | [02.9](02-cross-cutting-issues.md) [09.4](09-trust-transparency.md) | XS |
| 20 | 訂正報告動線（Q&A → ⋯メニュー → GitHub Issue） | [09.5](09-trust-transparency.md) | S |
| 21 | About / 利用規約 / データ仕様ページの整備 | [09.1](09-trust-transparency.md) | M |
| 22 | TSV 以外（CSV BOM 付・JSON）エクスポート、フィルタ URL 共有ボタン | [06.4](06-filtering-search.md) | S |
| 23 | ページネーション件数選択 + 検索結果ハイライト（`:target`） | [06.6](06-filtering-search.md) [06.10](06-filtering-search.md) | S |
| 24 | フィルタチップ表示と階層化（適用中条件を上に） | [06.3](06-filtering-search.md) | M |
| 25 | セッション詳細の左サイドバー目次（デスクトップ） | [07.2](07-session-detail.md) | M |
| 26 | 全文展開のロジック統一（`<details>` ベース） | [06.12](06-filtering-search.md) [07.6](07-session-detail.md) | S |
| 27 | タップターゲット 44px 確保 | [08.4](08-mobile-accessibility.md) | XS |
| 28 | キーボード操作: ヒートマップ・タイムラインの focus / Enter | [08.7](08-mobile-accessibility.md) | M |
| 29 | スキップリンク追加 | [08.8](08-mobile-accessibility.md) | XS |
| 30 | カラーコントラスト改善（グレー #6b7280 統一・回避度色＋アイコン併用） | [08.6](08-mobile-accessibility.md) | S |

---

## P2 — Tier 1 開始前 / 半年以内

| # | 項目 | 章 |
|---|------|----|
| 31 | 用語統一（"Q&A ペア" → "質疑応答" 等）と style guide ドキュメント | [02.7](02-cross-cutting-issues.md) |
| 32 | OG image 自動生成（セッション・Q&A ごと） | [07.10](07-session-detail.md) [09.8](09-trust-transparency.md) |
| 33 | タイムラインのモバイル縦表示モード | [08.3](08-mobile-accessibility.md) |
| 34 | MultiSelect: 選択済みチップ表示 | [06.7](06-filtering-search.md) |
| 35 | 法案ページ `/laws/:law_id` の新設 | [10.2.2](10-future-features.md) |
| 36 | 同一発言／類似質問の検出 | [10.2.3](10-future-features.md) |
| 37 | 最低限の英語化（ナビ・委員会名・要約） | [08.10](08-mobile-accessibility.md) [10.4](10-future-features.md) |
| 38 | 「フォロー」localStorage 機能 | [10.1.1](10-future-features.md) |
| 39 | RSS フィード（最新・議員別・法案別） | [10.7.1](10-future-features.md) |
| 40 | API ドキュメント（OpenAPI / JSON Schema） | [10.3.1](10-future-features.md) |

---

## P3 — 長期（Tier 1 BYOK 含む）

| # | 項目 | 章 |
|---|------|----|
| 41 | Tier 1 設定画面の本格実装（OpenRouter BYOK） | [10.5](10-future-features.md) |
| 42 | 比較ビュー（議員 vs 議員 / 委員会 vs 委員会） | [10.2.1](10-future-features.md) |
| 43 | 議員レーダーチャート | [10.2.5](10-future-features.md) |
| 44 | トピック共起ネットワーク（D3 force） | [10.8.2](10-future-features.md) |
| 45 | コメント・注釈（GitHub Discussions ベース） | [10.6.1](10-future-features.md) |
| 46 | PWA / オフラインキャッシュ | [8.11](08-mobile-accessibility.md) |
| 47 | 一括ダウンロード（月次 zip） | [10.3.2](10-future-features.md) |
| 48 | 利用統計ダッシュボード（Plausible / Cloudflare） | [10.9.2](10-future-features.md) |

---

## 推奨スプリントの組み方

### スプリント 1（本格稼働前 — 2 週間）
- P0 全件
- 受け入れテスト: ローンチクライテリア（上記）+ ヒートマップ・カレンダー → /browse の手動回遊テスト
- ステークホルダーに**新ローンチクライテリアを共有**してから開始

### スプリント 2（稼働後 4 週間）
- P1 11–20（データ品質・ダッシュボード再構成・About 整備）
- 受け入れテスト: P1 の各項目に対し screenshot diff or visual regression

### スプリント 3（稼働後 8 週間）
- P1 21–30 + P2 着手判断
- このタイミングで利用統計を見て、優先 P2 を決め直す

### スプリント 4 以降
- P2 + Tier 1 設計
- データ整理が進んだあとに、外部 API 公開（プレスリリース）

---

## チェックリスト（P0 完了確認用）

```
[ ] 1. /browse?topic=（既存トピック名）で >0 件返る
[ ] 2. /dashboard/topics のヒートマップ任意セルクリックで 結果ページに >0 件
[ ] 3. 全画面フッタ or QA カードに「LLM 自動評価」注記が見える
[ ] 4. /about/methodology が公開されており、回避度の定義・閾値・既知の限界が書かれている
[ ] 5. 発言者分析でサンプルサイズ < 10 が除外され、警告 N 件が見える
[ ] 6. iPhone 13 / Pixel 6 で /browse を開いてフィルタが畳まれている
[ ] 7. /browse で 0 件時に「条件を 1 つ外す」サジェストが出る
[ ] 8. ホーム・/browse・セッション詳細の同じ Q&A が共通カードコンポーネントで描画されている
[ ] 9. 役割フィルタが「発言タイプ × 答弁者属性」になっている
[ ] 10. /settings ページに「Phase 6 で…」表記が無い（リッチな coming soon or ナビから除外）
```

---

[← 戻る](README.md)
