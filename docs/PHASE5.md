# Phase 5: ダッシュボード・ビジュアライゼーション — 実装・テスト計画

> **目標**: 両院横断のダッシュボードページ群を構築し、セッションデータの可視化・分析機能を提供する。
> **所要期間**: 2〜3日
> **前提**: Phase 1〜4 が完了していること。`data/` 配下に複数セッションのJSON（metadata, utterances, qa_pairs, summary, topics）が存在すること。`site/` のAstroプロジェクトが動作しており、Pagefind・フィルタ・エクスポートが機能していること。

---

## 成果物

Phase 5 完了時に以下が揃う:

1. `/dashboard` — ダッシュボード概要ページ（各サブページへのナビ + サマリ統計）
2. `/dashboard/topics` — トピック×委員会ヒートマップ
3. `/dashboard/speakers` — 発言者ネットワーク図（Phase 6 の BYOK 前提ではない Tier 0 版）
4. `/dashboard/tracker` — 約束トラッカー（`key_commitments` 時系列表示）
5. セッション詳細ページ内のタイムラインビュー（`TimelineView.jsx`）
6. セッションカレンダー（GitHub Contributions 風）
7. `site/public/api/stats.json` — ビルド時に集計したダッシュボード用統計データ
8. 各コンポーネントの単体テスト + ビジュアルレビュー確認

---

## アーキテクチャ方針

### 静的サイト完結

すべてのダッシュボードデータはAstroビルド時に `data/` のJSONを読み取って集計・生成する。ランタイムのAPIコールは不要（Tier 0）。集計結果は:

- Astroページに直接埋め込む（小規模データ）
- `site/public/api/*.json` として出力（大規模データ、クライアントで遅延ロード）

### React島パターン

インタラクティブなチャート・グラフはReact島として `client:visible`（ビューポートに入ったらハイドレーション）で配置。データはAstroのサーバーサイドビルド時にpropsとして渡すか、`public/api/*.json` をfetchして使う。

### ライブラリ

| 用途 | ライブラリ | 備考 |
|------|-----------|------|
| チャート（ヒートマップ、バーチャート） | Recharts | React互換、宣言的API |
| ネットワーク図 | D3 force-directed | `d3-force` + `d3-selection`。React内でrefを使ってSVGを制御 |
| カレンダー | 自前実装（CSS Grid） | 軽量。GitHubのContribution Calendarを模倣 |

---

## データ集計スクリプト

### `site/src/lib/dataLoader.js`

ビルド時に `data/` ディレクトリを走査し、全セッションのJSONを読み込んで集計する共通モジュール。Phase 2〜4 で既に基本的なデータロード機能があるはずなので、それを拡張する。

**追加する集計関数:**

```typescript
// 全セッションの metadata.json を読み込み
function loadAllSessions(): SessionMetadata[]

// トピック×委員会のクロス集計（ヒートマップ用）
function aggregateTopicsByCommittee(): { topic: string; committee: string; count: number }[]

// 発言者ペア（質疑者↔答弁者）の集計（ネットワーク図用）
function aggregateSpeakerPairs(): { questioner: string; respondent: string; count: number; party?: string }[]

// 約束事項の一覧（トラッカー用）
function aggregateCommitments(): Commitment[]

// 答弁回避度の集計（大臣別・テーマ別）
function aggregateEvasionScores(): { speaker: string; topic: string; avgScore: number; count: number }[]

// 日別セッション数（カレンダー用）
function aggregateSessionsByDate(): { date: string; count: number; chamber: string }[]

// 全体統計（ダッシュボード概要用）
function computeStats(): DashboardStats
```

### `site/public/api/stats.json`（ビルド時生成）

```json
{
  "totalSessions": 42,
  "totalQAPairs": 580,
  "totalSpeakers": 210,
  "totalCommitments": 35,
  "avgEvasionScore": 0.42,
  "sessionsByChamber": { "shugiin": 28, "sangiin": 14 },
  "sessionsByMonth": [{ "month": "2026-04", "count": 12 }],
  "topTopics": [{ "topic": "高額療養費", "count": 15 }],
  "lastUpdated": "2026-04-14T12:00:00+09:00"
}
```

他に `topics.json`, `commitments.json`, `speakers.json` もビルド時に更新する（ARCH.md セクション4.3参照）。

---

## ステップ

### Step 1: データ集計モジュールの拡張

**やること:**
- `site/src/lib/dataLoader.js`（または `.ts`）に上記の集計関数を追加
- 既存のデータロード関数を活用し、ダッシュボード固有の集計ロジックを実装
- `site/public/api/stats.json` をビルド時に生成するスクリプトを追加（`astro.config.mjs` の `integrations` hook、または `src/pages/api/stats.json.js` としてAstroの静的エンドポイント）

**出力形式の決定事項:**
- ヒートマップ用: `{ rows: string[], cols: string[], data: number[][] }` の行列形式
- ネットワーク用: `{ nodes: Node[], links: Link[] }` のD3互換形式
- カレンダー用: `{ [date: string]: { count: number, sessions: { chamber, committee, slug }[] } }` のマップ形式

**テスト:**
- テスト用のダミーJSONデータ（3〜5セッション分）を `site/tests/fixtures/` に配置
- 各集計関数が正しい結果を返すことの単体テスト
- 空データ（0セッション）の場合にエラーにならないこと
- 両院混在データで chamber フィルタが正しく動作すること

---

### Step 2: ダッシュボード概要ページ (`/dashboard`)

**やること:**
- `site/src/pages/dashboard/index.astro` を作成
- ビルド時にデータ集計を実行し、概要統計をページに埋め込む
- 表示内容:
  - **サマリカード**: 総セッション数、総Q&Aペア数、総発言者数、約束事項数
  - **最近のセッション**: 直近5件のセッション（院・委員会・日付）
  - **サブページナビ**: トピック分析 / 約束トラッカー / 発言者ネットワーク / カレンダー へのリンクカード
  - **月別トレンド**: 過去6ヶ月のセッション数推移（Rechartsの `BarChart`）

**コンポーネント構成:**

```
dashboard/index.astro
├── DashboardStats.astro          # 静的: サマリカード群（SSR、ハイドレーションなし）
├── RecentSessions.astro          # 静的: 最近のセッション一覧
├── MonthlyTrendChart.jsx         # React島 (client:visible): Recharts BarChart
└── DashboardNav.astro            # 静的: サブページナビゲーション
```

**MonthlyTrendChart.jsx のprops:**

```typescript
interface MonthlyTrendChartProps {
  data: { month: string; shugiin: number; sangiin: number }[];
}
```

**テスト:**
- `npm run build` が成功し、`/dashboard/index.html` が生成されること
- `npm run dev` でページを開き、サマリカードの数値が正しいこと
- MonthlyTrendChart が衆参それぞれの棒グラフを表示すること
- セッション0件の状態でもページがレンダリングされること（空状態UI）

---

### Step 3: トピック×委員会ヒートマップ (`/dashboard/topics`)

**やること:**
- `site/src/pages/dashboard/topics.astro` を作成
- `site/src/components/TopicHeatmap.jsx` を実装（React島）

**TopicHeatmap.jsx の仕様:**

| 項目 | 仕様 |
|------|------|
| 横軸 | 委員会名（ソート: セッション数降順） |
| 縦軸 | トピック名（ソート: 言及回数降順、上位20件 + 「その他」） |
| セル色 | 言及回数に応じたグラデーション（白→青、0件は白） |
| ツールチップ | ホバーで「{トピック} × {委員会}: {N}件」を表示 |
| クリック | セルクリックで `/browse?topic={topic}&committee={committee}` へ遷移 |
| 院フィルタ | 上部に「全体 / 衆議院 / 参議院」トグル |
| レスポンシブ | 横スクロール対応（委員会数が多い場合） |

**Rechartsでの実装方針:**
- Rechartsにはネイティブのヒートマップがないため、カスタムセルを使った `ScatterChart` または素のSVG + Recharts の `Tooltip` を組み合わせる
- 代替案: SVGを直接描画し、React stateでフィルタ・ツールチップを管理。こちらのほうがシンプルな場合はこちらを採用

**データ形式（props）:**

```typescript
interface TopicHeatmapProps {
  data: {
    topics: string[];        // 行ラベル
    committees: string[];    // 列ラベル
    matrix: number[][];      // topics.length × committees.length
  };
}
```

**テスト:**
- ダミーデータで TopicHeatmap が正しくレンダリングされること
- 院フィルタの切り替えでデータが再集計されること
- 0件のセルが白色でレンダリングされること
- セルクリックで正しい URL に遷移すること
- ブラウザで目視確認: 色グラデーションが直感的か、ラベルが読めるか

---

### Step 4: 答弁回避度トラッカー

**やること:**
- `/dashboard/topics` ページ内、またはダッシュボード概要ページの一セクションとして実装（独立ページにするほどの規模ではない場合はセクションで可）
- `site/src/components/EvasionTracker.jsx` を実装（React島）

**EvasionTracker.jsx の仕様:**

| 項目 | 仕様 |
|------|------|
| 表示形式 | 大臣（答弁者）ごとの横棒グラフ |
| 棒の内訳 | 3色スタック: 明確回答（緑、score < 0.3）/ 検討する系（黄、0.3 ≤ score < 0.7）/ 回避的（赤、score ≥ 0.7） |
| ソート | 回避度平均が高い順（デフォルト）。件数順に切替可 |
| フィルタ | テーマ別フィルタ（セレクトボックス） |
| ドリルダウン | 棒クリックで該当大臣のQ&Aペア一覧を展開 |

**データ形式（props）:**

```typescript
interface EvasionTrackerProps {
  data: {
    speaker: string;
    role: string;
    totalAnswers: number;
    clearCount: number;       // evasion_score < 0.3
    hedgingCount: number;     // 0.3 ≤ evasion_score < 0.7
    evasiveCount: number;     // evasion_score ≥ 0.7
    avgEvasionScore: number;
    byTopic: { topic: string; avgScore: number; count: number }[];
  }[];
}
```

**テスト:**
- 棒グラフの3色が正しい比率で描画されること
- ソート切替が動作すること
- テーマフィルタで大臣の表示内容が変わること
- 答弁が0件の大臣が表示されないこと

---

### Step 5: 約束トラッカー (`/dashboard/tracker`)

**やること:**
- `site/src/pages/dashboard/tracker.astro` を作成
- `site/src/components/CommitmentTracker.jsx` を実装（React島）
- データソース: 各セッションの `summary.json` → `key_commitments` 配列

**CommitmentTracker.jsx の仕様:**

| 項目 | 仕様 |
|------|------|
| 表示形式 | 時系列カードリスト（日付降順） |
| カード内容 | 約束テキスト、発言者名（役職）、トピック、日付、出典リンク |
| グルーピング | トピック別にグルーピング可能（トグル） |
| 検索 | テキスト検索（クライアントサイドフィルタ） |
| ステータス | `未確認` / `進展あり` / `履行済み` / `未履行`（Phase 5 では全件 `未確認` で表示。手動更新機能は Phase 6 以降） |
| 院フィルタ | 全体 / 衆議院 / 参議院 |
| ソースリンク | 該当セッションのQ&Aペアへのリンク（`qa_id` を使用） |

**データ形式（props）:**

```typescript
interface Commitment {
  id: string;                    // "shugiin_56149_qa_001" 等
  speaker: string;
  role: string;
  text: string;
  topic: string;
  date: string;                  // "2026-04-09"
  chamber: string;
  committee: string;
  qaId: string;
  sessionSlug: string;           // セッション詳細ページへのパス構築用
  status: "unverified";          // Phase 5 では固定
}

interface CommitmentTrackerProps {
  commitments: Commitment[];
}
```

**テスト:**
- 約束事項が日付降順で表示されること
- トピック別グルーピングが正しく動作すること
- テキスト検索で絞り込みが動作すること
- ソースリンクが正しいセッション詳細ページのQ&Aペアに飛ぶこと
- 約束が0件の場合に適切な空状態メッセージが表示されること

---

### Step 6: セッションタイムラインビュー

**やること:**
- `site/src/components/TimelineView.jsx` を実装（React島）
- セッション詳細ページ（`[chamber]/[year]/[month]/[day]/[slug].astro`）内に配置
- データソース: 該当セッションの `utterances.json`

**TimelineView.jsx の仕様:**

| 項目 | 仕様 |
|------|------|
| 横軸 | 時間（秒 → `HH:MM` 表示） |
| バー | 発言セグメント。幅=発言時間、色=話者（同一話者は同色） |
| 色分け | role ベース: 委員長=グレー、質疑者=青系、答弁者=赤系、政府参考人=緑系 |
| Q&Aコネクタ | Q&Aペアの質問→答弁をアーチ線で接続 |
| クリック | バークリックで該当発言テキストを下部に展開 + 動画リンク |
| ツールチップ | ホバーで「{話者名}（{role}）{開始時刻}〜{終了時刻}」 |
| レスポンシブ | 横スクロール対応。最小バー幅を保証 |

**実装方針:**
- SVGベースで描画。Rechartsではなく素のSVG + Reactで制御（タイムラインの特殊なレイアウトのため）
- 話者の凡例を上部に配置
- Q&Aコネクタはオプション表示（トグル）

**データ形式（props）:**

```typescript
interface TimelineSegment {
  segmentIndex: number;
  speaker: string;
  role: string;
  startSeconds: number;
  endSeconds: number;
  utteranceCount: number;
  videoUrl: string;
}

interface QAConnection {
  qaId: string;
  questionStart: number;     // 秒
  answerStart: number;       // 秒
  topic: string;
}

interface TimelineViewProps {
  segments: TimelineSegment[];
  qaConnections: QAConnection[];
  totalDurationSeconds: number;
}
```

**テスト:**
- セグメントが時系列順に正しく配置されること
- 話者ごとに色が一貫していること
- バークリックで発言テキストが展開されること
- Q&Aコネクタ線が正しいペアを接続すること
- 長時間セッション（3時間+）でもレイアウトが破綻しないこと

---

### Step 7: セッションカレンダー

**やること:**
- `site/src/components/SessionCalendar.jsx` を実装（React島）
- ダッシュボード概要ページ（`/dashboard`）に配置

**SessionCalendar.jsx の仕様:**

| 項目 | 仕様 |
|------|------|
| 表示形式 | GitHub Contributions 風の年間カレンダー（横=週、縦=曜日） |
| セル色 | セッション数に応じた4段階: 0件=`#ebedf0`、1件=`#9be9a8`、2-3件=`#40c463`、4件+=`#216e39` |
| ツールチップ | ホバーで「{日付}: {N}セッション（衆{X} 参{Y}）」 |
| クリック | セルクリックでその日のセッション一覧（`/browse?date=YYYY-MM-DD`）へ遷移 |
| 範囲 | 直近12ヶ月（デフォルト）。スクロールまたはページネーションで過去分を表示 |
| 月ラベル | 上部に月名ラベル |

**実装方針:**
- CSS Grid で 53列（週）× 7行（曜日）のグリッドを描画
- 各セルは `<div>` にインラインスタイルで背景色を設定
- 外部ライブラリ不要。軽量に自前実装

**データ形式（props）:**

```typescript
interface SessionCalendarProps {
  data: Record<string, { count: number; shugiin: number; sangiin: number }>;
  // key: "YYYY-MM-DD"
}
```

**テスト:**
- 365日分のグリッドが正しく描画されること
- 色の段階が仕様どおりであること
- セルホバーでツールチップが表示されること
- セルクリックで正しいURLに遷移すること
- セッション0件の日が最も薄い色であること

---

### Step 8: ダッシュボードナビゲーション + レイアウト統合

**やること:**
- ダッシュボード共通レイアウト（サイドバーまたはタブナビゲーション）を実装
- サイトのグローバルナビに「ダッシュボード」リンクを追加
- 各ダッシュボードページ間の遷移がスムーズであることを確認
- ページタイトル・メタ情報の設定

**レイアウト構成:**

```
site/src/layouts/DashboardLayout.astro
├── グローバルヘッダー（既存）
├── ダッシュボードタブバー
│   ├── 概要 (/dashboard)
│   ├── トピック分析 (/dashboard/topics)
│   ├── 約束トラッカー (/dashboard/tracker)
│   └── 発言者分析 (/dashboard/speakers)  ← Phase 6 で D3 ネットワーク追加
└── メインコンテンツ（slot）
```

**テスト:**
- 全ダッシュボードページ間のナビゲーションが動作すること
- タブのアクティブ状態が正しいページをハイライトすること
- モバイルブレークポイントでタブが横スクロールになること

---

### Step 9: 統合テスト + ビジュアルレビュー

**やること:**
- 実データ（Phase 1〜4 で処理済みの全セッション）を使って `npm run build` を実行
- 各ダッシュボードページの表示を確認
- 以下のチェックリストを消化:

**チェックリスト:**

- [ ] `/dashboard` — サマリカードの数値が `data/` 内のセッション数と一致
- [ ] `/dashboard` — MonthlyTrendChart が衆参別に正しい件数を表示
- [ ] `/dashboard` — SessionCalendar がデータのある日にのみ色がつく
- [ ] `/dashboard/topics` — ヒートマップの行列が正しい（データに存在するトピック×委員会のみ）
- [ ] `/dashboard/topics` — 院フィルタで衆参切替が動作
- [ ] `/dashboard/topics` — セルクリックで browse ページの正しいフィルタ結果へ遷移
- [ ] `/dashboard/tracker` — 約束事項が日付降順
- [ ] `/dashboard/tracker` — ソースリンクが正しいセッションの正しいQ&Aペアへ飛ぶ
- [ ] セッション詳細ページのタイムラインビューが発言順に表示される
- [ ] タイムラインのバークリックで発言テキスト展開 + 動画リンクが機能
- [ ] 答弁回避度の3色スタックが合計件数と一致
- [ ] 全ページで出所明示（衆議院TV / 参議院TV リンク）が表示される
- [ ] モバイル表示（375px幅）でレイアウトが破綻しない
- [ ] Pagefind インデックスにダッシュボードページが含まれないこと（ダッシュボードはデータビューであり検索対象外）

---

## ファイル一覧（新規作成・変更）

### 新規作成

```
site/src/layouts/DashboardLayout.astro
site/src/pages/dashboard/index.astro
site/src/pages/dashboard/topics.astro
site/src/pages/dashboard/tracker.astro
site/src/components/MonthlyTrendChart.jsx
site/src/components/TopicHeatmap.jsx
site/src/components/EvasionTracker.jsx
site/src/components/CommitmentTracker.jsx
site/src/components/TimelineView.jsx
site/src/components/SessionCalendar.jsx
site/tests/fixtures/dashboard-sessions/    # テスト用ダミーJSON
site/tests/dataLoader.test.js              # 集計関数の単体テスト
```

### 変更

```
site/src/lib/dataLoader.js                 # 集計関数追加
site/src/pages/[chamber]/[year]/[month]/[day]/[slug].astro  # TimelineView追加
site/src/layouts/BaseLayout.astro           # グローバルナビに「ダッシュボード」追加
site/astro.config.mjs                       # 必要に応じてビルド時フック追加
site/package.json                           # recharts, d3-force 等の依存追加
```

---

## 依存関係の追加

```bash
cd site
npm install recharts d3-force d3-selection
```

既存の React 依存（Astro の `@astrojs/react`）は Phase 2 でセットアップ済みの前提。

---

## コンポーネント実装の注意事項

### Recharts の使い方

```jsx
// MonthlyTrendChart.jsx の例
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts";

export default function MonthlyTrendChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data}>
        <XAxis dataKey="month" />
        <YAxis />
        <Tooltip />
        <Legend />
        <Bar dataKey="shugiin" name="衆議院" fill="#3b82f6" stackId="a" />
        <Bar dataKey="sangiin" name="参議院" fill="#ef4444" stackId="a" />
      </BarChart>
    </ResponsiveContainer>
  );
}
```

### React島の配置

```astro
---
// dashboard/index.astro
import DashboardLayout from "../../layouts/DashboardLayout.astro";
import MonthlyTrendChart from "../../components/MonthlyTrendChart.jsx";
import SessionCalendar from "../../components/SessionCalendar.jsx";
import { computeStats, aggregateSessionsByDate, aggregateSessionsByMonth } from "../../lib/dataLoader";

const stats = await computeStats();
const calendarData = await aggregateSessionsByDate();
const monthlyData = await aggregateSessionsByMonth();
---
<DashboardLayout title="ダッシュボード">
  <!-- 静的セクション -->
  <section class="stats-cards">
    <div class="card">セッション数: {stats.totalSessions}</div>
    <div class="card">Q&Aペア数: {stats.totalQAPairs}</div>
    <!-- ... -->
  </section>

  <!-- React島 -->
  <MonthlyTrendChart client:visible data={monthlyData} />
  <SessionCalendar client:visible data={calendarData} />
</DashboardLayout>
```

### ヒートマップの色計算

```javascript
// 0〜max の値を色に変換
function getHeatmapColor(value, max) {
  if (value === 0) return "#f3f4f6";  // gray-100
  const intensity = Math.min(value / max, 1);
  // 白→青のグラデーション
  const r = Math.round(239 - intensity * 180);
  const g = Math.round(246 - intensity * 180);
  const b = Math.round(255);
  return `rgb(${r}, ${g}, ${b})`;
}
```

### TimelineView のSVG描画

```jsx
// TimelineView.jsx の骨格
export default function TimelineView({ segments, qaConnections, totalDurationSeconds }) {
  const svgWidth = 1200;
  const svgHeight = 120;
  const barHeight = 40;
  const yOffset = 50;

  const xScale = (seconds) => (seconds / totalDurationSeconds) * svgWidth;

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={svgWidth} height={svgHeight}>
        {/* 時間軸 */}
        {/* 発言バー */}
        {segments.map((seg) => (
          <rect
            key={seg.segmentIndex}
            x={xScale(seg.startSeconds)}
            y={yOffset}
            width={xScale(seg.endSeconds) - xScale(seg.startSeconds)}
            height={barHeight}
            fill={roleColor(seg.role)}
            onClick={() => handleSegmentClick(seg)}
          />
        ))}
        {/* Q&Aコネクタ（アーチ線） */}
      </svg>
    </div>
  );
}
```

---

## `/dashboard/speakers` について

ARCH.md の F-21（質疑者↔答弁者の対話ネットワーク）は優先度 **Could** で Phase 6 にも含まれている。Phase 5 では以下のスコープで実装する:

- **Phase 5 スコープ**: ページの骨格 + 発言者一覧テーブル（名前、所属、発言回数、平均回避度）。ソート・フィルタ可能。
- **Phase 6 で追加**: D3 force-directed ネットワーク図。これは BYOK 機能と同じ Phase に入っているが、ネットワーク図自体は Tier 0（キー不要）で実装可能。Phase 5 でページを用意しておき、Phase 6 で `SpeakerNetwork.jsx` を追加挿入する。

---

## テスト構成

```
site/
├── tests/
│   ├── fixtures/
│   │   └── dashboard-sessions/           # テスト用ダミーセッションJSON
│   │       ├── shugiin/2026/04/09/56149_本会議/
│   │       │   ├── metadata.json
│   │       │   ├── qa_pairs.json
│   │       │   ├── summary.json
│   │       │   └── topics.json
│   │       ├── shugiin/2026/04/10/56200_内閣委員会/
│   │       │   └── (同上)
│   │       └── sangiin/2026/04/10/1234_法務委員会/
│   │           └── (同上)
│   ├── dataLoader.test.js                # 集計関数の単体テスト
│   └── components/
│       ├── TopicHeatmap.test.jsx          # (任意) React Testing Library
│       └── CommitmentTracker.test.jsx     # (任意) React Testing Library
```

**テスト方針:**
- データ集計ロジックは純粋関数なので単体テストを必須で書く
- Reactコンポーネントのテストは任意（目視確認を優先）。書く場合は React Testing Library + Vitest
- `npm run build` の成功を CI での最低限の統合テストとする
- Pagefind のインデックスからダッシュボードページを除外するには、ダッシュボードページに `data-pagefind-ignore` 属性を追加

---

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| セッション数が少なく、ヒートマップ・カレンダーが寂しい | UXが悪い | データが少ない場合の空状態UIを設計。「データが蓄積されると表示が充実します」メッセージ |
| Rechartsのバンドルサイズが大きい | 初期ロード遅延 | `client:visible` で遅延ハイドレーション。treeshakeが効くようimportを個別に |
| トピック名の表記ゆれ（LLM生成のため） | ヒートマップの行が分散 | ビルド時にトピック正規化（類似トピックのマージ）を簡易実装。完全な解決は Phase 6 で |
| D3とReactの共存 | DOM競合 | D3はSVG要素の生成にのみ使用し、DOMの更新はReact（useRef + useEffect）に任せる |
| `data/` のセッション数が増えるとビルド時間が伸びる | CI遅延 | 集計結果をキャッシュ可能な形にする。現時点では問題になる規模ではない |

---

## 実装順序の推奨

ジュニア開発者向けに、以下の順序で実装することを推奨する。各ステップで動作確認してから次に進む。

1. **Step 1** (データ集計) → テストで正しい集計結果を確認
2. **Step 8** (レイアウト・ナビ) → ダッシュボードページの空枠を作成
3. **Step 2** (概要ページ) → 静的部分のみ先に表示確認
4. **Step 7** (カレンダー) → 概要ページに組み込み。CSS Gridで自前実装なので外部依存が少ない
5. **Step 2 続き** (MonthlyTrendChart) → Rechartsの初回導入。シンプルなBarChartで慣れる
6. **Step 3** (ヒートマップ) → Rechartsまたは素SVGでの描画
7. **Step 4** (回避度トラッカー) → Rechartsの StackedBarChart
8. **Step 5** (約束トラッカー) → 比較的シンプルなカードリストUI
9. **Step 6** (タイムライン) → 最も複雑。SVG直接描画 + クリックインタラクション
10. **Step 9** (統合テスト) → 全体通しで確認
