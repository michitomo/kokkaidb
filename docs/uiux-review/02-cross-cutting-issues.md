# 02. 横断的な根本問題（最優先）

[← 戻る](README.md)

このページに載せた問題は、特定の画面ではなく**サイト横断のデータ／用語／挙動の不整合**で、見つけにくいが影響範囲が広い。**P0 級が複数含まれる**。

---

## 2.1【P0】トピックの広域／狭域語彙が分離していて、トピックフィルタが事実上機能しない

### 現象
- `/browse?topic=防災庁の組織機能と権限` を開くと、ヒット 0 件。
- `/dashboard/topics` のヒートマップ（防災庁の組織機能と権限 × 災害対策特別委員会 = 2 件）をクリック → `/browse?topic=防災庁の組織機能と権限&committee=災害対策特別委員会` → 0 件。
- ダッシュボード「注目トピック」のチップ・ホームのキーワードタグから / browse へ飛んでも同じ。

### 根本原因
2 つの「トピック語彙」が存在し、互いにほぼ素集合になっている:

| ソース | フィールド | 性質 | 件数 |
|--------|-----------|------|------|
| `topics.json`（セッション単位）| `topics[].name` | LLM が**セッション全体を要約した広域トピック**（例: 「防災庁の組織機能と権限」）| 829（unique） |
| `qa_pairs.json`（Q&A 単位）| `pair.topic` | LLM が**個別 Q&A に付与した狭域トピック**（例: 「防災庁の勧告権の実効性と運用基準について」）| 6,286（unique） |
| 共通集合 | | | **わずか 10** |

`FilterPanel` の Q&A レベル絞り込み:
```js
const topicFiltered = selectedTopics.length > 0
  ? speakerFiltered.filter((qa) => selectedTopics.includes(qa.topic))
  : speakerFiltered;
```
ここで `selectedTopics`（広域）と `qa.topic`（狭域）が一致しないため、ほぼ常に 0 件。

加えてヒートマップのリンク先（`TopicHeatmap.jsx`）も広域トピックを `?topic=` に渡している:
```js
window.location.href = `${base}/browse?topic=${encodeURIComponent(topic)}&committee=${...}`;
```

### ユーザー影響
- **トピック起点の導線がほぼ全て死んでいる**（ヒートマップ／注目トピック／キーワードタグ／URL 直叩き）
- 「データはあるのに 0 件」という最も信用を失う表示が出る
- 改善前は新規ユーザーの離脱要因 No.1 になり得る

### 改善案
1. **トピック ID を導入**して、広域・狭域に階層関係を持たせる:
   - `topics.json`: `{ id: "topic_001", name: "防災庁の組織機能と権限", related_qa_ids: [...] }` を ID 一次キーで持つ
   - `qa_pairs.json` の `pair.topic` は表示用 short label と、所属する広域 topic ID を `parent_topic_id` で持つ
   - フィルタは `parent_topic_id` で絞る
2. 暫定対応として、**`FilterPanel` のトピック絞り込みを「`entry.topics` に含まれているセッション内の Q&A 全てを返す」に変える**（つまり QA レベルの filter を外す）。これだけでクリック導線が直ぐ繋がる。
3. ヒートマップ → 一覧の遷移時に「related_qa_ids」を URL に積めるなら、`?qa_ids=qa_021,qa_022,...` のような ID リスト指定で確実に当てる手もある。
4. より長期的には、**LLM プロンプト側でトピックタクソノミーを固定**する（例: 「防災・災害」「外交・安保」「経済・財政」… のような上位 30 カテゴリに必ず分類）。

---

## 2.2【P0】「回避度」の方法論が利用者にも内部関係者にも見えない

詳しくは [05-qa-quality-metrics.md](05-qa-quality-metrics.md) に分離するが、横断的な観点だけ:

- どこにも算出根拠の説明文がない（フッタにも `/about/methodology` のような専用ページもない）。
- LLM の解釈が後から変わると、過去スコアと比較できなくなる（モデル ID は metadata に記録されているが、UI に出ていない）。
- 1 件答弁でも `100%` の表示が成立し、メディアの数字遊びに使われ得る。**法的・社会的に最大のリスク**。

---

## 2.3【P0】ホーム／一覧／セッション詳細の絞り込みが 3 重に実装されている

詳しくは [03-information-architecture.md](03-information-architecture.md) に。本ページではポイントだけ:

- セッション詳細（`[chamber]/[year]/[month]/[day]/[slug].astro`）の発言者・トピックフィルタは Astro 内 `<script>` で生 JS、URL ハッシュ `#speaker=...&topic=...` で表現。
- 一覧（`browse.astro`）は React の `FilterPanel.jsx` で、URL クエリ `?speaker=...&topic=...&...` で表現。
- ホーム（`index.astro`）はフィルタ無しで日付グルーピングだけ。
- 同じ「Q&A をフィルタする」UI が異なるパラダイムで 2 つ動いている。バグ修正は両方に必要、A/B テストもしづらい。

---

## 2.4【P1】発言者名の名寄せが弱い（同一人物が複数行に分散）

### 現象（`evasion.json` から）
- `上野賢一郎`（議員名）と `上野厚生労働大臣`（役職名）が別レコード
- 大臣が変わると役職名 alias が分裂（`牧野大臣` ≠ 後任）
- 発言者総数 502 名中、`totalAnswers < 5` が 966 / 1,160 件（評価困難）
- これは Whisper・Speaker tagger の段階で `affiliation` と `name` を別々に持っているのに、`speakers.json` 集計で `name` のみで group by しているのが直因。

### ユーザー影響
- 議員秘書（P3）・記者（P2）の検索で「○○さん」を引いたつもりが半分しか出ない
- 発言者分析の上位ランキングが、現職大臣の役職名 alias で歪む

### 改善案
1. **正規化辞書 `speakers_master.json` を作る**: 議員名・役職名・別表記をまとめた（議員 ID）→ alias 一覧。
2. パイプラインで session 終了後、speaker_tagger の出力に `canonical_speaker_id` を付与。
3. UI 側はこの ID で集計し、表示は「氏名（役職）」に統一。
4. 暫定: `evasion.json` 集計で `totalAnswers < 5` を「サンプル不足」と明示し、棒グラフから除外 or グレーアウト。

---

## 2.5【P1】「不明」委員会・空文字メタデータがそのまま UI に出る

### 現象
- `topics-heatmap.json` の `committees` に `"不明"` が混入。
- 一部 `metadata.json` の `duration: ""`、`role: ""` 空文字をそのまま表示している。
- セッション 56206 のスラッグは `56206_不明`。

### 改善案
- `generate-api.ts` 段階で `committee === '不明'` のセッションをヒートマップから除外し、別カウンタとして `unclassified` を出す。
- UI 側で空文字フィールドは表示しない（`{role && <span>...}` パターンを徹底）。
- 委員会名の正規化辞書（`本会議` / `予算委員会` / `特別委員会(○○)` …）を一箇所で管理し、`committee_id` で参照。

---

## 2.6【P1】SessionCalendar → /browse のクエリ形式が一致していない

### 現象
- `SessionCalendar.jsx` のセルクリックは `?date=2026-04-23` を発行。
- `FilterPanel.jsx` は `from` / `to` のみ受け付け、`date` を読まない。
- 結果、カレンダークリックでフィルタが適用されないまま全件表示になる。

### 改善案
- 暫定: `parseUrlParams` に `date` を追加し、`from = to = date` として展開。
- 望ましい: カレンダークリックで `?from=YYYY-MM-DD&to=YYYY-MM-DD` を直接生成。

---

## 2.7【P2】用語のばらつき（「セッション」「審議」「会議」「Q&A ペア」）

サイト内の用語が画面ごとに揺れていて、初見の市民にやさしくない。

| 用語 | 出現箇所 | 推奨 |
|------|---------|------|
| セッション | dashboard、metadata | 「会議」or「審議回」 |
| 審議 | ホーム見出し | OK |
| Q&A ペア | dashboard 統計、ボタン | 「質疑応答」 |
| TSV をコピー | browse | 「表をコピー（Excel 用）」 |
| 概要 / [概要] | search、session detail | 「セッション要約」or「会議サマリ」 |
| 約束事項 | dashboard、QA カード | 「閣僚の言質（コミットメント）」 |

「Q&A」は省略形で IT 業界・教育用語色が強く、政治記者・議員秘書には硬く感じる。

### 改善案
- 用語表を `docs/style-guide.md` で 1 枚化し、コードベースで grep して置換。
- 「Q&A ペア」は CSS／JSON フィールドに残してよいが、UI 表示は「質疑応答」に統一。

---

## 2.8【P2】Tier 0 / Tier 1 の境界が UI 上どこにも見えない

`ARCH.md` 上は Tier 0（キー不要）／Tier 1（OpenRouter BYOK）に分かれているが、**現状サイトには Tier 1 への入口が全く無い**（settings ページは Phase 6 placeholder）。これは Phase 6 までは仕様だが、本格稼働の段階で:

- 「あなたが今見ているのはビルド時データの静的解析。BYOK で動的解析が可能」というガイダンスがあると訴求になる。
- 設定ページ（`settings.astro`）が「Phase 6 で〜」と書かれているのは内部表記であり、一般ユーザーに見せて良い文言ではない。

---

## 2.9【P2】lastUpdated が dashboard 概要にしか出ない

- 静的サイトとしてリアルタイム性をアピールしているのに、ホーム・一覧・セッション詳細にはデータ最終更新時刻が出ない。
- ニュース速報的な使われ方だと「更新止まってない？」が頻発する。

### 改善案
- `BaseLayout` のフッタに `最終データ更新: YYYY-MM-DD HH:MM` をビルド時に焼き込む。
- 各セッションの `processed_at` を詳細ページの出所行と並べて出す。

---

[← 戻る](README.md) ｜ [次の章: 03-information-architecture.md →](03-information-architecture.md)
