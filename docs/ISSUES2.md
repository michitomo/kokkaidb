# 第2次コード監査の課題リスト

実コードに照らして検証した監査結果（2026-05-10、`michitomo/structurer-rewrite-plan` 時点）。データ品質は対象外、コードと CI/CD 構成のみが対象。

`docs/ISSUES.md` が「データ生成の品質」を中心に扱うのに対し、本ドキュメントは「実装と運用基盤の堅牢性」にフォーカスする。

## 既に対応済み（参考）

以下は本監査で挙がった HIGH/MEDIUM のうち、コミット `17b3b60`（main）で解消済み。

- `batch.yml` に `concurrency: kokkai-batch` を追加（多重起動レース解消）
- `finalize` ジョブの checkout を `fetch-depth: 0` 化（rebase + push retry の信頼性向上）
- `.gitignore` に `.venv/` を追加

---

## 1. パイプライン堅牢性（kokkai-transcriber）

### 1-1〜1-2. [Migrated → STRUCTURER_REWRITE.md]

データ生成起因のためパイプライン完全刷新計画に取り込み、本書から削除した:

- **1-1 [High] ffmpeg サブプロセスに timeout が設定されていない** → `docs/STRUCTURER_REWRITE.md §2.15 パイプライン堅牢性`
- **1-2 [High] structurer.py が空の `full_text` を含む QA ペアを保存する** → `docs/STRUCTURER_REWRITE.md §2.10 content_missing`（drop 条件追加・統計サマリの実装に統合）

---

### 1-3. [Medium] `_batch_push()` が rebase なしで push する

**現象**: `src/batch.py:149-168` の `_batch_push()` は単純に `git add → commit → push` するのみ。`finalize` ワークフローと違って rebase + retry ループがない。

**影響**:
- `python -m src.batch ... --workers N` をローカルや `workflow_dispatch` から実行した際、CI が同時間帯に push していると `non-fast-forward` で 1 発失敗
- 現時点で main の concurrency を入れたので CI 同士のレースは無いが、人間操作との競合は残る

**修正**:
- push 前に `git fetch origin <branch>` + `git rebase origin/<branch>`
- もしくは `finalize` ジョブと同等の 5 回リトライループを `_batch_push` に展開
- conflict 時は `git rebase --abort` + 上位に raise

---

### 1-4. [Medium] `pipeline.py` がスクレイプ前に `output_dir` を mkdir する

**現象**: `src/pipeline.py:124` で `output_dir.mkdir(parents=True, exist_ok=True)` を呼んだ後にスクレイプ。`SessionNotReadyError` で抜けると空ディレクトリだけ残る。

**影響**:
- ローカル実行で `data/` ツリーが汚れる
- CI では artifact upload に空ディレクトリが含まれる可能性
- `_has_processed_output` の判定基準（`qa_pairs.json` 存在）には影響しないので機能影響は限定的

**修正**: スクレイプ成功（`session_detail` 取得後）に mkdir する。

---

### 1-5. [Medium] HLS セグメント取得が 4xx でもリトライする

**現象**: `src/audio/extractor.py:_fetch_one` (197-218) は `requests.RequestException` を捕捉してリトライ。`raise_for_status()` は `HTTPError`（`RequestException` のサブクラス）を投げるので 403/404 でも 3 回リトライする。

**影響**:
- 永続的に失敗するセグメントで無駄に backoff（2.0/4.0/6.0 秒）を待つ
- 相手側のレート制限を踏むリスク

**修正**:
```python
except requests.HTTPError as e:
    if 400 <= e.response.status_code < 500:
        raise  # 即座に上位へ
    last_err = e
    ...
except requests.RequestException as e:
    last_err = e
    ...
```

---

## 2. 静的サイト（site/）

### 2-1. [High] `[slug].astro` の Q&A コネクタがセグメントを取り違える

**現象**: `site/src/pages/[chamber]/[year]/[month]/[day]/[slug].astro:102-114`

```js
const qSeg = segs.findIndex((s) => s.segment_speaker === pair.question.speaker);
const aSeg = segs.findIndex((s) => s.segment_speaker === pair.answer.speaker && segs.indexOf(s) > qSeg);
```

speaker 名のみでマッチしているため、同じ質疑者が後の回でも質問しているセッションでは別の segment が引かれる。`pair.segment_index` が QA ペアに既にあるのに使っていない。

**影響**:
- タイムラインビューで Q&A コネクタ線が誤った位置に伸びる
- 大臣が複数質疑者から同じ話題で答弁しているケースで顕著

**修正**:
```js
const qSeg = segs.findIndex(s => s.segment_index === pair.segment_index);
const aSeg = qSeg;  // 同一 segment 内の質疑→答弁が前提
```

タイムラインの可視化で「質問→答弁」を別 segment にまたぐ表現が必要なら、その意図に合わせて `pair.segment_index` を起点に絞り込み直す。

---

### 2-2. [High] `getAllSessions()` がページ毎にディスク全走査する

**現象**: `site/src/lib/data.ts:73-83` の `getAllSessions()` は `glob.sync('**/metadata.json')` + 各ファイルを `JSON.parse`。これを `index.astro` / `browse.astro` / `dashboard/*.astro` / 個別セッションページの `getStaticPaths` などが各々呼んでいる。

**影響**:
- ビルド時のみだが O(pages × sessions × file IO)
- セッション数増加で線形に build 時間が伸びる
- 既に `site/public/api/index.json` に統合データはあるのに二重読み込み

**修正**:
- `data.ts` 内で module-scope メモ化:
  ```ts
  let _allSessions: SessionMetadata[] | null = null;
  export function getAllSessions(): SessionMetadata[] {
    if (_allSessions) return _allSessions;
    // ...
    _allSessions = sessions.sort(...);
    return _allSessions;
  }
  ```
- もしくは `site/public/api/index.json` を読む実装に切り替え

---

### 2-3. [Medium] `QAPairCard.astro` の `would_be_referenced` 欠損で undefined が画面に出る

**現象**: `site/src/components/QAPairCard.astro:79-95`

```astro
class={`record-value-${metrics.would_be_referenced}`}
```
```astro
{recordValueLabel[metrics.would_be_referenced] ?? metrics.would_be_referenced}
```

`metrics.would_be_referenced` が欠損していると `record-value-undefined` というクラス名が付き、ラベルは `undefined` 文字列が描画される。

**影響**: 古いデータや LLM 出力欠損で見た目が崩れる。

**修正**:
```astro
{metrics?.would_be_referenced && ['high','medium','low'].includes(metrics.would_be_referenced) && (
  <button class={`record-value-btn record-value-${metrics.would_be_referenced}`} ...>
    📋 {recordValueLabel[metrics.would_be_referenced]}
  </button>
)}
```

---

### 2-4. [Medium] `EvasionTracker.jsx` が null/undefined speaker で TypeError

**現象**: `site/src/components/EvasionTracker.jsx:49` 付近

```jsx
d.speaker.length > 6 ? d.speaker.slice(0, 6) + "…" : d.speaker
```

`d.speaker` が `null` / `undefined` だと `.length` で例外。

**影響**: structurer の `_resolve_answerer_from_sentences` は実装上 `("", "")` を返すケースがあり、空文字なら通過するが、上流が将来 null を返す可能性は否定できない。Evasion ダッシュボード全体がクラッシュするとリスク高。

**修正**:
```jsx
const name = d.speaker ?? '';
return name.length > 6 ? name.slice(0, 6) + "…" : name;
```

---

### 2-5. [Medium] `[slug].astro` の topic ボタンが JSON 配列を data 属性に重複出力

**現象**: `[slug].astro:166` 付近

```astro
{displayTopics.map(t => (
  <button data-qa-ids={JSON.stringify(topicQaMap[t] || [])}>{t}</button>
))}
```

XSS リスクは Astro の属性自動エスケープで無いが、トピックごとに同じ `qa_ids` 配列がページ HTML に複数回シリアライズされる。

**影響**:
- ページ HTML が冗長に膨らむ（特に多トピックセッションで顕著）
- 帯域・初回描画の負荷

**修正**:
```astro
<script type="application/json" id="topic-qa-map">{JSON.stringify(topicQaMap)}</script>
```
を 1 つだけ置き、ボタン側は `data-topic={t}` のみ。クリックハンドラ側で `topicQaMap[topic]` を引く。

---

## 3. CI/CD・設定

### 3-1. [Medium] `batch.yml` の `permissions:` がトップレベルで過剰付与

**現象**: `.github/workflows/batch.yml:23-26`

```yaml
permissions:
  contents: write
  pages: write
  id-token: write
```

`pages: write` と `id-token: write` は `build` / `deploy` ジョブでしか使わないが、`discovery` / `ingest` / `finalize` にも継承されている。

**影響**: 最小権限原則違反。スクレイパーが任意のサイトを叩くため、万一マルウェア化したパッケージを引いた場合の被害範囲を広げる。

**修正**:
```yaml
permissions:
  contents: write

jobs:
  build:
    permissions:
      contents: read
      pages: write
      id-token: write
  deploy:
    permissions:
      contents: read
      pages: write
      id-token: write
```

---

### 3-2. [Medium] `state.py` がデッドコード（ARCH.md と矛盾）

**現象**: `src/state.py` には `WAL` モード / `busy_timeout` / `check_same_thread=False` / スキーママイグレーションまで揃った `StateManager` が実装済みだが、`batch.py` も `pipeline.py` も import していない。実際の冪等判定は `_has_processed_output()` が `qa_pairs.json` の存在を見るだけ。

ARCH.md §4.5 では SQLite 状態管理を設計の中核に据えているが、実装は filesystem-as-state に切り替わっている。

**影響**:
- 設計ドキュメントと実装の乖離（新規参加者が混乱）
- `state.db` も `.gitignore` に残るが意味がない
- リトライ追跡や処理ログを将来追加する際の判断基準が不明確

**修正**: 以下のいずれか
1. `state.py` を削除し、ARCH.md §4.5 を「filesystem-as-state」に書き換える
2. `state.py` を実際に使う（pending_retry トラッキング、processing_log への詳細書き込み等）

---

### 3-3. [Medium] `cache: 'pip'` と手動 `.venv` キャッシュが二重

**現象**: `batch.yml:36-40, 62-67`（discovery）と `140-144, 152-157`（ingest）で、`setup-python` の `cache: 'pip'`（`~/.cache/pip` を保存）と `actions/cache` の `kokkai-transcriber/.venv` キャッシュが両方有効。

**影響**:
- venv キャッシュがヒットすると `pip install` がスキップされ、pip キャッシュは更新されない
- 結果として pip キャッシュの存在意義がほぼ無い（無駄なストレージ・転送）

**修正**: `setup-python` から `cache: 'pip'` と `cache-dependency-path` を外し、venv キャッシュ単独に統一。

---

### 3-4. [Low] Playwright ブラウザキャッシュキーが pyproject ハッシュ依存

**現象**: `batch.yml:85, 175`

```yaml
key: playwright-chromium-${{ runner.os }}-${{ hashFiles('kokkai-transcriber/pyproject.toml') }}
```

pyproject 上で playwright のバージョンを変えていなくても、Chromium バイナリの実体が GitHub Actions runner 側で更新されていればキャッシュは古いまま。

**影響**: ごく稀に `Target page, context or browser has been closed` 系の挙動差を引く可能性。

**修正**: pyproject の playwright バージョンを実値で含めるか、明示的に `playwright-chromium-v<MAJOR>-...` を入れる。

---

### 3-5. [Low] `node-version: 22` が浮動

**現象**: `build-deploy.yml`、`batch.yml` ともに `node-version: 22` を指定。`site/package.json` の engines は `>=22.12.0`。

**影響**: 22 系の minor が変わるとビルド差分が出る可能性（特に Astro の adapter / vite まわり）。再現性が下がる。

**修正**: `node-version-file: site/.nvmrc` に切り替えるか、明示的なパッチピン。

---

### 3-6. [Low] Python 依存に上限がない

**現象**: `kokkai-transcriber/pyproject.toml` の依存がすべて `>=` のみ。`pydantic` や `requests` の major アップグレードで破壊的変更を踏むリスク。

**修正**: 主要依存に `<N` を追加（例: `pydantic>=2.5,<3.0`、`requests>=2.31,<3.0`）。

---

## 4. 細かい改善

### 4-1. [Low] `data.ts:51` の `lawMap.get(id)` 二重呼び出し

```ts
return entry.related_laws.flatMap(id => lawMap.get(id) ? [lawMap.get(id)!] : []);
```

機能的には正常だが冗長。

**修正**:
```ts
return entry.related_laws.flatMap(id => {
  const law = lawMap.get(id);
  return law ? [law] : [];
});
```

---

### 4-2. [Migrated → STRUCTURER_REWRITE.md §2.16] `find_committee_in_body` が下位タグまで全文走査して誤検知し得る

データ生成起因のため `docs/STRUCTURER_REWRITE.md §2.16 スクレイパー堅牢性` に取り込み。

---

## 監査の補足

本監査の最初の自動レポート（3 つの subagent による出力）には事実誤認がいくつか含まれていたため、以下は**不採録**としている:

- 「committee 名で path traversal の可能性」: `_COMMITTEE_PATTERN = [一-鿿ぁ-んァ-ヶ・]+委員会` が日本語文字のみ受理するため、`/` や `..` を含み得ない
- 「`data-qa-ids` で XSS」: Astro の属性は自動エスケープされる（サイズの問題は 2-5 として残した）
- 「`tsv-export.test.ts` のアサーションが間違っている」: 実コード未確認

監査時点のコミット: `michitomo/structurer-rewrite-plan` ブランチ。
