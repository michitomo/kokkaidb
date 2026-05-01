# 国会議事録リアルタイムDB — UI/UX 改善レビュー

衆議院本格稼働を前提とした、現状サイトの網羅的な UI/UX レビュー。
画面実装・生成データ・スクリーンショット（`screenshots/` 配下）に基づく。

## このレビューの読み方

- **章ごとに 1 ファイル**。優先度や論点で分けてある。
- **ペルソナ視点**は `01-personas.md` を読んでから他の章に入ると、各指摘がどのユーザーに刺さるかが追える。
- **すぐ着手したい人**は `99-priority-roadmap.md` の P0 / P1 から見れば良い。
- 各章末に「具体的な改善案」を箇条書きで添えている。実装イメージは別途。

## 章構成

| # | ファイル | 概要 |
|---|---------|------|
| 1 | [01-personas.md](01-personas.md) | 想定ペルソナ 7 人と各人にとっての成功シナリオ |
| 2 | [02-cross-cutting-issues.md](02-cross-cutting-issues.md) | 全章にまたがる根本的な不具合・データ起因の問題（**P0 多数**） |
| 3 | [03-information-architecture.md](03-information-architecture.md) | ナビ／URL／ページ間の重複（ホーム・一覧・セッション詳細・検索） |
| 4 | [04-dashboard.md](04-dashboard.md) | ダッシュボードが使われていない理由とリデザイン |
| 5 | [05-qa-quality-metrics.md](05-qa-quality-metrics.md) | 「回避度」を置き換える Q&A 品質評価の 12 軸フレームワーク（V4 プロンプト確定済み） |
| 6 | [06-filtering-search.md](06-filtering-search.md) | 一覧フィルタと全文検索 |
| 7 | [07-session-detail.md](07-session-detail.md) | セッション詳細（質疑応答・タイムライン・発言全文） |
| 8 | [08-mobile-accessibility.md](08-mobile-accessibility.md) | モバイル／アクセシビリティ／i18n |
| 9 | [09-trust-transparency.md](09-trust-transparency.md) | 透明性・出典・LLM 解釈に関する免責 |
| 10 | [10-future-features.md](10-future-features.md) | Tier 1（BYOK）含む拡張・比較・購読系機能 |
| 99 | [99-priority-roadmap.md](99-priority-roadmap.md) | P0–P3 の優先順位ロードマップ |

## 全体感（Executive Summary）

### 良いところ（残したい設計）

- **静的サイト + 構造化 JSON**という土台が効いている。Pagefind で全文検索、Recharts でダッシュボード、フィルタは React 島でクライアント完結。低コストで保守性が高い。
- **出典明示**（衆議院TV / 参議院TV へのリンク）が QA カード・セッションフッタ・グローバルフッタに 3 段で入っており、著作権法 48 条への対応が丁寧。
- **政党カラー**を NHK 選挙報道準拠で揃えたタイムラインは、政治関係者にも違和感が少ない。
- セッション詳細の「発言タイムライン → Q&A → 発言全文」の縦動線は、議論の構造を追いやすい。

### 致命傷（最優先で直すべき）

1. **トピックフィルタの 99.8% が機能不全**。`/browse?topic=...` に渡される「広域トピック」（topics.json の name）と、Q&A レコードが持つ「狭域トピック」（qa_pairs.json の topic）がほぼ別語彙で、フィルタを通すと 0 件になる。ヒートマップの全クリック・ダッシュボード「注目トピック」のチップ・ホームの法案タグ等、トピック起点の導線が**ほぼ全て死んでいる**（詳細: [02-cross-cutting-issues.md](02-cross-cutting-issues.md)）。
2. **「回避度」一指標では質疑の良し悪しが捉えられない**。実データ 6,308 ペアで確認したところ、直接性しか測らない単一指標は (a) 質問側の作り込みを評価できない、(b) 「直接的だが価値の低い事務確認」と「回避的だが議事録に残る重要追及」を区別できない、(c) コミットメント強度や議事録価値を表現できない。この問題に対し、質問の質 5 軸／答弁の実質度 4 軸／ペアの帰結 3 軸からなる多軸評価体系と、その判定用 LLM プロンプト（V4）を定義した（詳細: [05-qa-quality-metrics.md](05-qa-quality-metrics.md)）。
3. **ホーム（一覧）／ /browse ／ セッション詳細のフィルタが、別実装で 3 重化**。ご指摘の通り Astro 側 `<script>` と React の FilterPanel が並走しており、URL 設計・状態同期も別。ナビ階層もホームと一覧がほぼ同じ役割を担っている（詳細: [03-information-architecture.md](03-information-architecture.md)）。
4. **モバイルで一覧画面のフィルタが折りたたまれない**（`🔍 フィルタ ▼` トグルが効いていない／開閉ロジックが SSR / hydration とズレている）。スマホ閲覧時はファーストビューがフィルタで埋まる（詳細: [08-mobile-accessibility.md](08-mobile-accessibility.md)）。
5. **発言者分析の 83%（966/1160 名）が `totalAnswers < 5` の超少数サンプル**で、回避度バーが赤一色になり判断材料にならない。委員長や政府参考人も混入しており、本当に追跡したい大臣・副大臣の比較が埋もれる。

### サイト全体への提言（章を跨いだ方向性）

- **「広域トピック」と「狭域トピック」を分離した語彙設計**にする。広域は閲覧導線（カテゴリ）、狭域は検索結果のラベル、の二層構造へ。
- **ホーム = 「最近の論点」要約／/browse = 「全件絞り込み」／検索 = 「全文検索」**と役割を明確化し、サイドバーを共通化したリスト UI を 1 コンポーネントに集約。
- **旧「回避度」を多軸 Q&A 品質指標（QQ-1〜5 / AS-1〜4 / OC-1〜3）に置き換える**。「直接回答度」（旧回避度の反転）に加えて、質問の論点明確度・行動要求度、答弁のコミットメント強度（Lv0〜4）、ペアの議事録価値などを別軸で見る。総合スコアは出さず、信頼度フィールド (`scoring_confidence`) を併記して低信頼ペアを明示する。詳細・V4 プロンプト全文は [05-qa-quality-metrics.md](05-qa-quality-metrics.md)。
- **ダッシュボードを "国会全体の今" を見るランディング**として再構成し、Tier 0 の入口（ホーム）と統合する選択肢を検討。
- **本格稼働前に "About / 方法論 / 免責事項" ページを必須**とし、運営主体・更新頻度・LLM の限界を明示する。

### スクリーンショットの参照表

| 画像 | 内容 |
|------|------|
| `screenshots/20-home-aboveFold.png` | ホーム（デスクトップ・ファーストビュー） |
| `screenshots/30-home-mobile-aboveFold.png` | ホーム（モバイル） |
| `screenshots/21-browse-aboveFold.png` | 一覧 `/browse`（フィルタ＋結果） |
| `screenshots/22-browse-mobile-aboveFold.png` | 一覧（モバイル — フィルタが畳まれていない） |
| `screenshots/29-browse-real-topic.png` | 既存トピックで `/browse?topic=...` を開いて 0 件になる現象 |
| `screenshots/06-search-desktop.png` | 検索ページ（dev mode で input 不在） |
| `screenshots/23-dashboard-aboveFold.png` | ダッシュボード概要 |
| `screenshots/24-dashboard-topics-aboveFold.png` | トピック分析（ヒートマップ密度 5%） |
| `screenshots/25-dashboard-tracker-aboveFold.png` | 約束トラッカー（status は常に "未確認"） |
| `screenshots/26-dashboard-speakers-aboveFold.png` | 発言者分析（赤一色／姓名切れ／表が長い） |
| `screenshots/27-session-detail-aboveFold.png` | セッション詳細（タイムライン＋発言者一覧） |
| `screenshots/28-session-detail-qa.png` | セッション詳細 Q&A セクション |

> 上記はビルド前の dev server で撮影。検索ページは Pagefind が build 後にしか動かないため、本番では入力欄が表示される（dev mode 限定の現象）。
