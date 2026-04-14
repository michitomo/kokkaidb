# 現状の問題点と解決策

現時点（2026-04-14）のコードベース・生成データ・閲覧サイトを網羅的にレビューした結果をまとめる。

法案タグ凡例: 各課題に `📋 法案関連` タグがある場合、第221回国会の提出予定法案（`docs/laws.md`）に直接影響する問題であることを示す。

---

## 1. データ生成（kokkai-transcriber）

### 1-1. [Critical] full_text がQ&Aペアごとに正しく分割されていない — 📋 法案関連

**現象**: 同一セグメント内の複数Q&Aペアが同一の `full_text` を持っている。例えばセグメント3（早稲田ゆき）の10ペアは、Q側が全て同じ3,328文字、A側も8ペアが同じ2,590文字。

**原因**: 現在のデータは旧コード（`utterance_indices`方式、コミット `8f122f6`）で生成されたもの。LLMが返した `utterance_indices` が不正だった場合のフォールバックとして、セグメント内の質疑者/答弁者の全発言を丸ごと `full_text` に入れていた。新しい `sentence_indices` 方式のコードは未コミット・未実行。

**解決策**:
1. 未コミットの `sentence_indices` 版 `structurer.py` をコミット
2. LLMが `sentence_indices` を空配列で返す場合の対策を追加:
   - LLMレスポンスを検証し、空の場合はリトライ（`temperature` を少し上げて再試行）
   - リトライ後も空の場合、質疑者/答弁者の発言テキストからトピックに最も関連する文を選択するヒューリスティック
   - 最終フォールバック: セグメント全体ではなく、該当ロール（質疑者or答弁者）の発言のみを使用
3. パイプラインを再実行してデータを再生成

### 1-2. [Critical] sentence_indices が全ペアで空配列 — 📋 法案関連

**現象**: 42ペア全てで `sentence_indices` が空（`[]`）。LLMがインデックスを返していない。

**原因**: LLM（DeepSeek V3.2）がプロンプト内の `(N)` 番号付きフォーマットを正しく認識・活用できていない可能性。または出力トークン制限で省略。

**解決策**:
1. LLMレスポンスのraw JSONを保存してデバッグ（`output_dir / "debug_llm_responses/"` に保存）
2. sentence_indices が空のペアを検出した際にWARNINGログを出力
3. プロンプトを改善: 番号指定の例を具体的に複数示す、few-shot例を追加
4. 代替アプローチ: TF-IDF/embeddingベースでsummaryに最も近い文を自動選択

### 1-3. [High] 姓の先頭2文字マッチングが不正確 — 📋 法案関連

**現象**: `_fuzzy_lookup()` は `name[:2]` で姓マッチングを行うが、1文字姓（林、森など）で誤マッチする。

**原因**: `surname = name[:2] if len(name) >= 2 else name` — 例えば「森英介」の場合 `surname="森英"` となり、「森田」や「森山」にもマッチしうる。

**解決策**:
- 姓の文字数を推定する関数を追加（2文字姓・3文字姓のパターン辞書）
- または、Levenshtein距離で最も近い名前を選択
- 最低限: マッチが複数候補ある場合は完全一致を優先、なければ最短一致

### 1-4. [High] SQLite並行アクセスの競合

**現象**: `state.py` にロック機構がなく、複数パイプラインプロセスが同時に同じDBにアクセスすると破損の恐れ。

**原因**: `sqlite3.connect()` のデフォルトはスレッドセーフだが、プロセス間では WAL モードが必要。現在PRAGMA設定なし。

**解決策**:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

### 1-5. [Medium] 文分割が「。」のみ対応

**現象**: `_split_sentences()` は `。`（句点）でのみ分割。`？`、`！`、`…。` などのパターンに対応していない。

**影響**: sentence_indicesの番号と実際の文がずれる可能性。

**解決策**: 正規表現で `。|！|？` + 後続空白で分割。括弧内の句読点は除外。

### 1-6. [Medium] LLMレスポンスのJSON解析にエラーハンドリングなし

**現象**: `structurer.py:298` の `json.loads(content)` は malformed JSON で例外が出る。

**解決策**: try/except で囲み、パースエラー時はログ出力して空配列を返す。リトライも検討。

### 1-7. [Medium] speaker_tagger.py のLLMレスポンス検証が不十分

**現象**: LLMが返すutterancesの `speaker`/`role`/`text` キーが欠損した場合、KeyErrorで落ちる。

**解決策**: `.get()` でデフォルト値を使い、欠損フィールドをログに記録。

### 1-8. [Low] video_url がセグメント単位で同一 — 📋 法案関連

**現象**: 同一セグメント内の全Q&Aペアが同じ `video_url` を持つ。ペアごとのタイムスタンプ精度がない。

**原因**: `video_url` はセグメントの開始時間を使っているため、ペアごとの開始時刻が区別できない。

**解決策**:
- utterances にタイムスタンプがあれば、Q&Aペアの開始utteranceの時刻を使用
- Whisperのword-level timestampsを活用してより精密なタイムスタンプを算出

### 1-9. [Low] follow_up_ids が未実装

**現象**: モデルに `follow_up_ids` フィールドがあるが、常に空配列。

**解決策**: 実装するか、モデルからフィールドを削除して混乱を防ぐ。

### 1-10. [Low] Dockerfileにffprobeが含まれていない可能性

**現象**: `audio/extractor.py` は ffprobe を使って動画の長さを取得するが、Docker imageに ffprobe が含まれているか未確認。

**解決策**: Dockerfileで `ffmpeg` パッケージをインストールすれば通常 `ffprobe` も含まれるが、明示的に確認。

---

## 2. 静的サイト（site/）

### 2-1. [High] 「全文を表示」が全ペアで同じテキストを表示 — 📋 法案関連

**現象**: 同一セグメント内のQ&Aペアの全文展開が全て同じテキスト。ユーザーが「このQ&Aの該当部分」を読みたいのに、長いテキスト全体が表示される。

**原因**: 上記 1-1 のデータ品質問題が直接的原因。

**解決策**: データ品質を修正すれば自然に解消。UI側での追加対策として:
- full_text が空の場合は「全文を表示」ボタンを非表示
- 同一セグメント内で重複するfull_textの場合、「セグメント全文」と表示して誤解を防ぐ

### 2-2. [Medium] browse ページのbase path 取得が不統一

**現象**: コンポーネントによって base path の取得方法が異なる:
- `FilterPanel.jsx`: `import.meta.env.BASE_URL`
- `SessionCalendar.jsx`: `document.querySelector("base")?.href`
- `TopicHeatmap.jsx`: 同上

**リスク**: いずれかの方法が特定環境で失敗するとリンク切れ。

**解決策**: Astro親コンポーネントから `base` をpropsで渡す方式に統一。

### 2-3. [Medium] OGP・SEOメタタグの欠如

**現象**: `<meta property="og:*">` タグ、`<meta name="description">` が未設定。SNSでシェアした際にプレビューが表示されない。

**解決策**: `BaseLayout.astro` にOGPタグを追加。各ページからtitle/descriptionをslotで渡す。

### 2-4. [Medium] ダッシュボードページがデータ1セッションのみ

**現象**: ヒートマップ、トレンドチャート、回避度ランキング等がデータ1件のため実質的に意味をなさない。

**影響**: ユーザー体験としてダッシュボードが寂しい。

**解決策**: 複数セッションのデータを蓄積した後に評価する。現段階では「データが蓄積されると充実します」等のメッセージを表示。

### 2-5. [Medium] generate-api.ts と data.ts で型定義が重複

**現象**: `scripts/generate-api.ts` と `src/lib/data.ts` で `QAPair`、`SessionMetadata` 等の型が独立に定義されている。

**リスク**: 片方を変更した際にもう一方との不整合が起きる。

**解決策**: 共通の型定義ファイル（`src/types.ts`）を作成し、両方からimport。

### 2-6. [Low] SessionCalendar のキーボードナビゲーション未対応

**現象**: カレンダーのセル（日付）にキーボードでフォーカス・選択ができない。

**解決策**: `tabIndex={0}` と `onKeyDown` ハンドラを追加。

### 2-7. [Low] Pagefind の事前読み込みなし

**現象**: 検索ページで Pagefind UI の JavaScript を動的importで読み込んでいるが、preloadなし。

**影響**: 検索窓への初回入力時に遅延が発生する。

**解決策**: `<link rel="modulepreload" href="/kokkaidb/pagefind/pagefind-ui.js">` を head に追加。

### 2-8. [Low] settings ページがプレースホルダー

**現象**: Phase 6用のBYOK設定ページが「Phase 6 で実装予定」のメッセージのみ。

**解決策**: Phase 6 実装時に対応。現時点ではナビゲーションから非表示にするか、「準備中」と明記。

---

## 3. スクレイパー

### 3-1. [Medium] 衆議院スクレイパーのDOM構造依存

**現象**: speaker抽出が `<a href=re("time=")>` → 5階層上の `<tr>` というDOM走査に依存。HTMLレイアウト変更で即座に壊れる。

**解決策**:
- HTML構造変更を検出するバリデーション（期待するタグ階層がない場合はWARNING）
- テスト用のHTMLフィクスチャを定期的に実サイトと比較するスモークテスト

### 3-2. [Medium] 参議院の mediasp.jp 解決がPlaywrightなし

**現象**: `sangiin_resolver.py` はAPIリクエストベースだが、mediasp.jp がJSレンダリング必須の場合に対応できない。コメントでは「Playwright fallback」と書かれているが未実装。

**解決策**: Playwright fallback を実装するか、現在のAPIベース方式で対応可能であることを確認・文書化。

### 3-3. [Low] 日付 "unknown" のフォールバック

**現象**: 参議院スクレイパーで日付解析に失敗した場合、`"unknown"` が返される。これがそのまま出力ディレクトリパスに使われると `data/sangiin/unkn/ow/n/` のようなおかしなパスが生成される。

**解決策**: 日付解析失敗時は例外を投げてパイプラインを停止。

---

## 4. テスト

### 4-1. [High] structurer のsentence_indices関連テストが不足

**不足テスト**:
- sentence_indices が空配列の場合の振る舞い
- sentence_indices が範囲外の場合
- 空セグメント（utterancesなし）の場合
- fuzzy_lookup の1文字姓・一致なしケース

### 4-2. [Medium] LLMレスポンス異常系テストがない

**不足テスト**:
- LLMがmalformed JSONを返した場合
- LLMレスポンスのフィールド欠損
- LLMがタイムアウトした場合

### 4-3. [Medium] スクレイパーのエンコーディングエラーテストがない

**不足テスト**:
- EUC-JPのバイト列をUTF-8として解析した場合の挙動
- HTML構造が想定外の場合

### 4-4. [Low] 並行処理のテストがない

**不足テスト**:
- StateManager の並行アクセス
- ThreadPoolExecutor でのエラー伝播

---

## 5. インフラ・運用

### 5-1. [Medium] 依存関係のバージョンピン不足

**現象**: `pyproject.toml` で `requests>=2.31` のように下限のみ指定。メジャーバージョンアップで壊れるリスク。

**解決策**: `uv.lock` または `requirements.txt` で lockfile を生成・管理。

### 5-2. [Medium] API キー管理が分散

**現象**: `DEEPINFRA_API_KEY` を `transcriber.py`、`speaker_tagger.py`、`structurer.py` がそれぞれ独立に取得。

**解決策**: `src/api_client.py` に共通クライアントファクトリを作成。

### 5-3. [Low] publisher.py が origin/main 固定

**現象**: `git push origin main` がハードコード。デフォルトブランチ名が異なるリポジトリで失敗。

**解決策**: `git symbolic-ref refs/remotes/origin/HEAD` でデフォルトブランチを自動検出。

---

## 6. 法案タグ付け機能

### 6-1. [Implemented] セッションに関連法案タグを付与し、browse ページでフィルタ可能にする

**実装済み**:

1. **法案マスタ解析** (`site/scripts/generate-api.ts` の `parseLawsMd`):
   - `docs/laws.md`（gitignore済み）をパースし、73法案の `id`/`title`/`short_title`/`ministry`/`tags` を抽出
   - 各法案のイタリック行 `` *`tag1` `tag2`* `` からキーワードを自動取得

2. **セッション–法案マッチング** (`matchLaws`):
   - セッション内全Q&Aペアの `topic` + `question_summary` + `answer_summary` を結合
   - 各法案のタグと照合し、30%以上かつ2つ以上ヒットした法案を `related_laws` に追加
   - 結果: セッション56149 → `law_035`（健康保険法等の一部を改正する法律案）

3. **API出力**:
   - `site/public/api/laws.json`: 73法案のマスタ（`id`/`title`/`short_title`/`ministry`）
   - `site/public/api/index.json`: 各セッションに `related_laws: string[]` を追加

4. **browse ページの法案フィルタ** (`FilterPanel.jsx`):
   - MultiSelect「関連法案」を追加（short_title表示、id でフィルタ）
   - URLパラメータ `?law=law_035` で共有可能
   - リセット・hasActiveFilters にも対応

**未実装（将来拡張）**:
- 法案別ページ（`/kokkaidb/laws/[law_id]`）
- ダッシュボードの法案別回避度サマリー
- Q&Aペア単位の法案タグ付け（現在はセッション単位）

### 6-2. [Medium] 法案タグの精度検証手段がない

**現象**: 自動タグ付けの精度を検証する仕組みがない。

**解決策**:
- 手動アノテーション用のCSVを用意し、自動タグとの一致率を計測
- 初期は少数セッションで手動検証し、閾値を調整

### 6-3. [Low] 法案マスタの更新フロー

**現象**: laws.md は手動更新。国会開会中に法案が追加・修正される。

**解決策**:
- 衆議院・参議院のWebサイトから法案一覧をスクレイピングする自動更新スクリプト（将来的）
- 当面は手動更新で対応。laws.md 更新時に `parse_laws.py` を再実行

---

## 優先度まとめ

| 優先度 | ID | 概要 | 影響範囲 | 📋 法案関連 |
|--------|-----|------|----------|:---:|
| **Critical** | 1-1, 1-2 | full_text が正しく分割されない / sentence_indices が空 | データ品質・UX | Yes |
| **High** | 1-3 | 姓マッチングの不正確さ | speaker/role 誤帰属 | Yes |
| **High** | 1-4 | SQLite並行アクセス競合 | データ破損 | |
| **High** | 2-1 | 全文表示が重複 | UX | Yes |
| **High** | 4-1 | structurer テスト不足 | 品質保証 | |
| **Done** | 6-1 | 法案フィルタ（browse ページ） | 実装済み | Yes |
| **Medium** | 1-5〜1-7, 2-2〜2-5, 3-1〜3-2, 4-2〜4-3, 5-1〜5-2, 6-2 | 各種改善 | 堅牢性・保守性 | |
| **Low** | 1-8〜1-10, 2-6〜2-8, 3-3, 4-4, 5-3, 6-3 | 細かい改善 | 体験向上 | |

### 処理済みセッションと法案の対応

| セッション | 委員会 | 日付 | 主要関連法案 |
|-----------|--------|------|-------------|
| 56149 | 本会議 | 2026-04-09 | 健康保険法等の一部を改正する法律案（厚生労働省） |

※ 上記セッションの42 Q&Aペアのうち、大半が健康保険法改正案に直接関連。一部ペア（中東情勢・エネルギー関連）は外為法改正案に間接的に関連。
