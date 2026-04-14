# Phase 4: フィルタ + エクスポート — 実装・テスト計画

> **目標**: `/browse` ページにクライアントサイド多軸フィルタリングを実装し、フィルタ済みQ&AペアのTSVエクスポート機能を提供する。動画タイムスタンプリンクを両院で完備する。
> **所要期間**: 1日
> **前提**: Phase 1〜3 が完了していること。`site/` のAstroプロジェクトが動作し、`data/` にJSON群が存在すること。
> **対応要件**: F-12（多軸フィルタ）、F-16（TSVエクスポート）、F-14（動画リンク完備）

---

## 成果物

Phase 4 完了時に以下が揃う:

1. `/browse` ページで院・日付範囲・委員会・政党/会派・発言者名・役割・トピックの7軸フィルタが動作する
2. フィルタ結果のQ&AペアをTSVとしてクリップボードにコピーできる
3. 全Q&Aカードから衆議院TV / 参議院TVの該当タイムスタンプへの動画リンクが機能する
4. `site/public/api/` 配下にビルド時生成のフィルタ用マスタJSONが存在する
5. FilterPanel / TSVエクスポートの単体テスト

---

## アーキテクチャ概要

```
[Astro ビルド時]
  data/**/*.json → astro.config.mjs (Content Collections) → site/public/api/*.json
                                                           → 各ページの静的HTML

[ブラウザ実行時 — /browse]
  ┌─────────────────────────────────────────────┐
  │  FilterPanel.jsx (React島, client:load)      │
  │                                               │
  │  ┌─ フィルタUI ──────────────────────────────┐ │
  │  │ 院セレクタ / 日付レンジ / 委員会 /         │ │
  │  │ 政党 / 発言者名 / 役割 / トピック          │ │
  │  └───────────────────────────────────────────┘ │
  │              ↓ state変更                        │
  │  ┌─ 結果表示 ────────────────────────────────┐ │
  │  │ QAPairCardリスト（フィルタ済み）            │ │
  │  │ + 動画リンク + TSVコピーボタン              │ │
  │  └───────────────────────────────────────────┘ │
  └─────────────────────────────────────────────┘
```

**設計判断:**
- フィルタロジックはすべてクライアントサイド（React島内）で実行する。サーバー不要（NF-01準拠）
- フィルタ用のマスタデータ（委員会一覧、政党一覧、発言者一覧、トピック一覧）はビルド時に `site/public/api/` に静的JSONとして生成する
- Q&Aペアデータは `/api/index.json` として全件を1ファイルに集約する。数千件規模までは1ファイルで問題ない（NF-04: 初回検索3秒以内）
- URLクエリパラメータでフィルタ状態を永続化し、リンク共有を可能にする

---

## ステップ

### Step 1: ビルド時フィルタマスタJSON生成

**やること:**
- Astroの `src/lib/data-loader.ts` を作成し、`data/` ディレクトリのJSON群を読み込むユーティリティ関数を実装する
- ビルド時に以下の静的JSONを `site/public/api/` に生成する:

| ファイル | 内容 | 生成ロジック |
|---------|------|-------------|
| `index.json` | 全セッション + 全Q&Aペアの集約データ | 全 `data/{chamber}/**/metadata.json` + `qa_pairs.json` を結合 |
| `speakers.json` | 発言者マスタ（名前、所属、登場回数） | 全 `metadata.json` の `speakers` を名寄せ・集約 |
| `parties.json` | 政党/会派マスタ（名前、所属議員数） | 全 `speakers` の `affiliation` をユニーク化・集約 |
| `topics.json` | トピックマスタ（名前、関連セッション数） | 全 `topics.json` の `topics` をユニーク化・集約 |
| `committees.json` | 委員会マスタ（名前、院、セッション数） | 全 `metadata.json` の `committee` をユニーク化・集約 |

**`index.json` のスキーマ:**

```typescript
interface IndexEntry {
  session_id: string;
  chamber: "shugiin" | "sangiin";
  date: string;           // YYYY-MM-DD
  committee: string;
  source_url: string;
  speakers: string[];     // 発言者名リスト
  parties: string[];      // 所属政党リスト（ユニーク）
  topics: string[];       // トピックリスト
  qa_pairs: {
    id: string;
    topic: string;
    question_speaker: string;
    question_party: string;
    question_summary: string;
    question_intent: string;
    answer_speaker: string;
    answer_role: string;
    answer_summary: string;
    evasion_score: number;
    has_commitment: boolean;
    commitment_text: string;
    video_url: string;
  }[];
}
```

**実装場所:**
- `site/src/lib/data-loader.ts` — データ読み込み + 集約ユーティリティ
- `site/src/pages/api/` は使わない（静的サイトなのでビルドスクリプトで生成する）
- `site/scripts/generate-api.ts` — ビルド前に `public/api/` を生成するスクリプト。`package.json` の `prebuild` に追加

**テスト:**
- `site/scripts/__tests__/generate-api.test.ts` — テスト用の最小限 `data/` フィクスチャを使い、生成されるJSONの構造を検証
- 各マスタJSONが空でないこと
- `index.json` のQ&Aペアが `qa_pairs.json` の件数と一致すること

---

### Step 2: FilterPanel React コンポーネント

**やること:**
- `site/src/components/FilterPanel.jsx` を実装する（React島、`client:load`）
- 起動時に `/api/index.json` を `fetch` してメモリに保持する
- 以下の7つのフィルタ軸を提供する:

| フィルタ軸 | UIコンポーネント | データソース | デフォルト |
|-----------|-----------------|-------------|-----------|
| 院（chamber） | ラジオボタン（全て / 衆議院 / 参議院） | 固定値 | 全て |
| 日付範囲 | 開始日 / 終了日の `<input type="date">` | — | 制限なし |
| 委員会 | 複数選択ドロップダウン | `/api/committees.json` | 全て |
| 政党/会派 | 複数選択ドロップダウン | `/api/parties.json` | 全て |
| 発言者名 | テキスト入力（インクリメンタル検索） | `/api/speakers.json` | 空 |
| 役割 | チェックボックス（質疑者 / 答弁者 / 政府参考人 / 委員長） | 固定値 | 全て |
| トピック | 複数選択ドロップダウン | `/api/topics.json` | 全て |

**フィルタロジック:**
- 全フィルタは AND 条件で結合する
- 複数選択フィルタ内は OR 条件（例: 委員会=「内閣委員会」OR「法務委員会」）
- フィルタ変更のたびにQ&Aペアリストをリアクティブに更新する
- マッチ件数をフィルタパネル上部に常時表示する（例: `125件 / 全1,832件`）

**URLクエリパラメータ連携:**
- フィルタ状態を `?chamber=shugiin&from=2026-04-01&to=2026-04-14&committee=...` 形式でURLに反映する
- ページロード時にURLパラメータからフィルタ状態を復元する
- `window.history.replaceState` で履歴を汚さずにURL更新する

**パフォーマンス:**
- フィルタ関数に `useMemo` を使い、フィルタ条件が変わったときのみ再計算する
- テキスト入力にはデバウンス（300ms）を適用する
- 初回データロード中はスケルトンUIを表示する

**実装ファイル:**
- `site/src/components/FilterPanel.jsx` — メインコンポーネント（状態管理 + フィルタロジック + UI）
- `site/src/components/FilteredQAList.jsx` — フィルタ結果のQ&Aカードリスト表示
- `site/src/components/MultiSelect.jsx` — 汎用の複数選択ドロップダウン（委員会 / 政党 / トピックで共用）

**テスト:**
- `site/src/components/__tests__/FilterPanel.test.jsx` — React Testing Library + Vitest
  - 初期状態で全件表示されること
  - 院フィルタ切替で件数が変わること
  - 日付範囲フィルタが正しく絞り込むこと
  - 複数フィルタのAND結合が正しく動作すること
  - URLパラメータからの復元が正しいこと
  - 0件の場合にメッセージが表示されること
- `site/src/components/__tests__/MultiSelect.test.jsx`
  - 選択 / 解除が正しく動作すること
  - 検索テキストで候補が絞られること

---

### Step 3: TSVエクスポート機能

**やること:**
- `site/src/lib/tsv-export.ts` を作成し、Q&Aペア配列をTSV文字列に変換するユーティリティを実装する
- フィルタ結果のQ&AペアをTSVとしてクリップボードにコピーするボタンを `FilteredQAList.jsx` に配置する

**TSVフォーマット（F-16準拠、Google Sheets貼り付け想定）:**

```
日付	院	委員会	トピック	質問者	質問者所属	質問要旨	答弁者	答弁者役職	答弁要旨	回避度	約束有無	約束内容	動画URL	出典URL
2026-04-09	衆議院	本会議	高額療養費の多数回該当リセット	古川あおい	チームみらい	がん患者が毎年1月に...	上野賢一郎	厚生労働大臣	問題を認識しており...	0.3	あり	次期制度改正の...	https://...	https://...
```

**列定義（15列）:**

| # | 列名 | ソース |
|---|------|--------|
| 1 | 日付 | `session.date` |
| 2 | 院 | `session.chamber` → "衆議院" / "参議院" |
| 3 | 委員会 | `session.committee` |
| 4 | トピック | `qa.topic` |
| 5 | 質問者 | `qa.question.speaker` |
| 6 | 質問者所属 | `qa.question.party` |
| 7 | 質問要旨 | `qa.question.summary` |
| 8 | 答弁者 | `qa.answer.speaker` |
| 9 | 答弁者役職 | `qa.answer.role` |
| 10 | 答弁要旨 | `qa.answer.summary` |
| 11 | 回避度 | `qa.answer.evasion_score` |
| 12 | 約束有無 | `qa.answer.has_commitment` → "あり" / "なし" |
| 13 | 約束内容 | `qa.answer.commitment_text` |
| 14 | 動画URL | `qa.video_url` |
| 15 | 出典URL | `session.source_url` |

**エスケープルール:**
- タブ文字をスペースに置換
- 改行を `\n`（リテラル）に置換
- ダブルクォートのエスケープは不要（TSV形式のため）

**クリップボードコピーUI:**
- ボタンラベル: `TSVをコピー（{N}件）`
- `navigator.clipboard.writeText()` を使用する
- コピー成功時: ボタンテキストを一時的に `コピーしました ✓` に変更（2秒後に復帰）
- コピー失敗時（権限なし等）: フォールバックとして `<textarea>` に表示し手動コピーを促す

**実装ファイル:**
- `site/src/lib/tsv-export.ts` — `qaPairsToTsv(pairs, sessions): string` 関数
- エクスポートボタンは `FilteredQAList.jsx` 内に配置

**テスト:**
- `site/src/lib/__tests__/tsv-export.test.ts` — Vitest
  - ヘッダ行が正しいこと（15列）
  - タブ・改行のエスケープが正しいこと
  - 空の配列で空文字列（ヘッダのみ）が返ること
  - 日本語文字列が正しく出力されること
  - `chamber` → 日本語変換が正しいこと
  - `has_commitment` → "あり"/"なし" 変換が正しいこと

---

### Step 4: 動画タイムスタンプリンク完備

**やること:**
- Q&AカードおよびQ&Aリスト内の各エントリに、衆議院TV / 参議院TVの該当箇所への動画リンクを表示する
- 動画リンクは `qa_pairs.json` 内の `video_url` フィールドから取得する

**衆議院の動画リンク形式:**
```
https://www.shugiintv.go.jp/jp/index.php?ex=VL&media_type=&deli_id={session_id}&time={start_seconds}
```

**参議院の動画リンク形式:**
```
https://webtv.sangiin.go.jp/webtv/detail.php?sid={session_id}#{start_seconds}
```

**UI仕様:**
- 各Q&Aカードの右上に動画アイコンリンクを配置する
- リンクは `target="_blank"` `rel="noopener noreferrer"` で開く
- ツールチップ: `動画を見る（{開始時間}〜）`
- 出所明示（著作権法第48条対応）: カード下部に `出典: 衆議院TV` / `出典: 参議院TV` のテキストリンクを `source_url` へ向けて表示する

**実装場所:**
- `site/src/components/QAPairCard.astro` — 既存のQ&Aカードに動画リンクと出典リンクを追加
- `site/src/components/FilteredQAList.jsx` — リスト表示内のカードにも同様のリンクを配置

**テスト:**
- 手動テスト: 衆議院・参議院それぞれのQ&Aカードで動画リンクをクリックし、正しいタイムスタンプで動画が再生されることを確認する
- リンクが `video_url` フィールドの値と一致することをスナップショットテストで検証

---

### Step 5: `/browse` ページ統合

**やること:**
- `site/src/pages/browse.astro` を実装する
- FilterPanel を React島として配置する

**ページ構成:**

```
┌─────────────────────────────────────────────┐
│ ヘッダ: 質疑データベース — 絞り込み検索        │
├─────────────────────────────────────────────┤
│ FilterPanel (React島)                        │
│ ┌─────────────────────────────────────┐      │
│ │ [衆] [参] [全て]  日付: [__] 〜 [__] │      │
│ │ 委員会: [▼ 複数選択]                  │      │
│ │ 政党: [▼ 複数選択]                    │      │
│ │ 発言者: [テキスト入力________]         │      │
│ │ 役割: ☑質疑者 ☑答弁者 ☑政府参考人     │      │
│ │ トピック: [▼ 複数選択]                 │      │
│ ├─────────────────────────────────────┤      │
│ │ 125件 / 全1,832件                     │      │
│ │ [TSVをコピー（125件）] [フィルタをリセット] │ │
│ ├─────────────────────────────────────┤      │
│ │ ┌─ Q&Aカード ─────────────────┐     │      │
│ │ │ 質問: ...     │ 答弁: ...    │ 🎥  │      │
│ │ │ 古川あおい    │ 上野賢一郎   │     │      │
│ │ │ (チームみらい) │ (厚労大臣)   │     │      │
│ │ │ 回避度: ██░░░ 0.3            │     │      │
│ │ │ 出典: 衆議院TV              │     │      │
│ │ └──────────────────────────────┘     │      │
│ │ ...（以下繰り返し）                    │      │
│ └─────────────────────────────────────┘      │
├─────────────────────────────────────────────┤
│ ページネーション: < 1 2 3 ... 13 >           │
└─────────────────────────────────────────────┘
```

**ページネーション:**
- 1ページあたり20件のQ&Aペアを表示する
- ページ番号もURLパラメータ `?page=2` で管理する
- フィルタ変更時はページ1にリセットする

**レスポンシブ対応:**
- モバイル（< 768px）: フィルタパネルは折りたたみ式。Q&Aカードは縦積み（質問→答弁の順）
- デスクトップ（>= 768px）: フィルタパネルは常時表示。Q&Aカードは左右並列

**実装ファイル:**
- `site/src/pages/browse.astro` — ページシェル + FilterPanel島の配置
- レイアウトは既存の `site/src/layouts/` を使用する

**テスト:**
- ブラウザ手動テスト:
  - [ ] フィルタの全軸が動作すること
  - [ ] URLパラメータでフィルタ状態が保存・復元されること
  - [ ] TSVコピーが動作し、Google Sheetsに貼り付けられること
  - [ ] 動画リンクが正しいタイムスタンプで開くこと
  - [ ] ページネーションが正しく動作すること
  - [ ] モバイルでのレスポンシブ表示
  - [ ] 0件の場合にメッセージが表示されること
  - [ ] フィルタリセットボタンで全フィルタがクリアされること

---

### Step 6: E2Eテスト + ビルド検証

**やること:**
- テスト用のダミーデータ（衆議院2セッション + 参議院1セッション）を `site/tests/fixtures/data/` に配置する
- ビルドが正常に完了することを検証する
- 生成された `public/api/*.json` の構造を検証する

**ダミーデータ仕様:**

| セッション | 院 | 日付 | 委員会 | Q&A数 |
|-----------|-----|------|--------|-------|
| テスト衆議院1 | shugiin | 2026-04-09 | 本会議 | 3 |
| テスト衆議院2 | shugiin | 2026-04-10 | 内閣委員会 | 2 |
| テスト参議院1 | sangiin | 2026-04-09 | 法務委員会 | 2 |

- 複数の政党（3党以上）、複数のトピック（4つ以上）、複数の発言者（6名以上）を含める
- `evasion_score` は0.1〜0.9の範囲でバリエーションを持たせる
- `has_commitment = true` のペアを最低1つ含める

**テスト手順:**

```bash
# 1. テスト用データでビルド
cd site
DATA_DIR=tests/fixtures/data npm run build

# 2. API JSONの検証
node -e "
const idx = require('./dist/api/index.json');
console.assert(idx.length === 3, 'セッション数');
console.assert(idx.flatMap(s => s.qa_pairs).length === 7, 'Q&Aペア数');
"

# 3. Vitestで全テスト実行
npm test

# 4. 開発サーバーで手動確認
npm run dev
# → http://localhost:4321/browse で動作確認
```

---

## ファイル一覧（新規作成・変更）

| ファイル | 新規/変更 | 内容 |
|---------|----------|------|
| `site/scripts/generate-api.ts` | 新規 | ビルド前のAPI JSON生成スクリプト |
| `site/src/lib/data-loader.ts` | 新規 | data/ JSON読み込みユーティリティ |
| `site/src/lib/tsv-export.ts` | 新規 | TSV変換ユーティリティ |
| `site/src/components/FilterPanel.jsx` | 新規 | 多軸フィルタUI（React島） |
| `site/src/components/FilteredQAList.jsx` | 新規 | フィルタ結果表示 + TSVコピーボタン |
| `site/src/components/MultiSelect.jsx` | 新規 | 汎用複数選択ドロップダウン |
| `site/src/pages/browse.astro` | 新規 | フィルタ付きブラウズページ |
| `site/src/components/QAPairCard.astro` | 変更 | 動画リンク + 出典リンク追加 |
| `site/package.json` | 変更 | `prebuild` スクリプト追加 |
| `site/scripts/__tests__/generate-api.test.ts` | 新規 | API生成テスト |
| `site/src/components/__tests__/FilterPanel.test.jsx` | 新規 | フィルタテスト |
| `site/src/components/__tests__/MultiSelect.test.jsx` | 新規 | 複数選択テスト |
| `site/src/lib/__tests__/tsv-export.test.ts` | 新規 | TSVエクスポートテスト |
| `site/tests/fixtures/data/` | 新規 | テスト用ダミーJSONデータ |

---

## 依存関係（追加パッケージ）

```bash
cd site

# テスト
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

既存のAstro + Reactで十分。追加のUIライブラリは不要。MultiSelectは自前実装する（外部ライブラリの学習コストを回避）。

---

## 実装順序と依存関係

```
Step 1: ビルド時JSON生成
  ↓（Step 2, 3 は Step 1 の JSON スキーマに依存）
Step 2: FilterPanel  ←→  Step 3: TSVエクスポート（並行可能）
  ↓
Step 4: 動画リンク（並行可能、Q&Aカード変更）
  ↓
Step 5: /browse ページ統合（Step 2, 3, 4 すべてに依存）
  ↓
Step 6: E2Eテスト + ビルド検証
```

**推奨作業順:**
1. Step 1 → Step 3 → Step 2 → Step 4 → Step 5 → Step 6
2. Step 3（TSVエクスポート）はロジックのみで最もシンプルなので先にテストを書きやすい
3. Step 2（FilterPanel）は最大のコンポーネントなので十分な時間を確保する

---

## リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| `index.json` が大きすぎて初回ロードが遅い | UX劣化 | セッション数1,000以上でページ分割を検討。Phase 4時点では数十セッション想定なので問題なし。将来的には `index_{page}.json` に分割 |
| Clipboard API が HTTPS 以外で動かない | TSVコピー失敗 | `textarea` フォールバックを用意。GitHub Pages は HTTPS なので本番では問題なし |
| 参議院TV の動画リンク形式が変更される | リンク切れ | `video_url` はパイプライン側で生成するため、Phase 3 のスクレイパー修正で対応 |
| 発言者名の表記揺れ（同一人物の複数表記） | フィルタ漏れ | Phase 4 では厳密一致。名寄せは Phase 5 以降の改善項目 |
| 複数選択ドロップダウンの候補が多すぎる | 操作性劣化 | ドロップダウン内にテキスト検索を付ける（MultiSelect に実装） |

---

## コーディング規約（Phase 4 固有）

- React コンポーネントは JSX（TypeScript なし）。Astro コンポーネントは `.astro`
- CSS は各コンポーネント内の `<style>` タグ（Astro scoped styles）または React コンポーネント内のインラインスタイル / CSS Modules
- `sessionStorage` / `localStorage` は使用しない（フィルタ状態は URL パラメータのみ）
- OpenRouter APIキーに関連するコードは Phase 4 では一切触れない（Phase 6 スコープ）
- 全ての動画リンクに `出典: 衆議院TV` / `出典: 参議院TV` テキストを併記すること（著作権法第48条対応）
