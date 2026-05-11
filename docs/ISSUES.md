# 現状の問題点と解決策

現時点（2026-04-14）のコードベース・生成データ・閲覧サイトを網羅的にレビューした結果をまとめる。

> **2026-05-10 追記**: 後続コミットで対応された項目のタイトル先頭を `[Resolved]` に書き換え、各項目末尾に検証根拠（**対応**: ...）を追記した。残課題のうちコード/CI 由来の指摘は `docs/ISSUES2.md` に再整理済み。

法案タグ凡例: 各課題に `📋 法案関連` タグがある場合、第221回国会の提出予定法案（`docs/laws.md`）に直接影響する問題であることを示す。

---

## 1. データ生成（kokkai-transcriber）

### 1-1. [Resolved] full_text がQ&Aペアごとに正しく分割されていない — 📋 法案関連

**現象**: 同一セグメント内の複数Q&Aペアが同一の `full_text` を持っている。例えばセグメント3（早稲田ゆき）の10ペアは、Q側が全て同じ3,328文字、A側も8ペアが同じ2,590文字。

**原因**: 現在のデータは旧コード（`utterance_indices`方式、コミット `8f122f6`）で生成されたもの。LLMが返した `utterance_indices` が不正だった場合のフォールバックとして、セグメント内の質疑者/答弁者の全発言を丸ごと `full_text` に入れていた。新しい `sentence_indices` 方式のコードは未コミット・未実行。

**解決策**:
1. 未コミットの `sentence_indices` 版 `structurer.py` をコミット
2. LLMが `sentence_indices` を空配列で返す場合の対策を追加:
   - LLMレスポンスを検証し、空の場合はリトライ（`temperature` を少し上げて再試行）
   - リトライ後も空の場合、質疑者/答弁者の発言テキストからトピックに最も関連する文を選択するヒューリスティック
   - 最終フォールバック: セグメント全体ではなく、該当ロール（質疑者or答弁者）の発言のみを使用
3. パイプラインを再実行してデータを再生成

**対応**: `structurer.py` が sentence_indices フローに刷新済み（`_assemble_full_text_from_sentences`、`_extract_pairs_from_response` が `sentence_indices` を直接読む）。実データ（`data/shugiin/2026/03/02/56088_予算委員会/qa_pairs.json`）で `[.pairs[].question.full_text] | group_by(.) | map(length) | max` = 1 を確認。

### 1-2. [Resolved] sentence_indices が全ペアで空配列 — 📋 法案関連

**現象**: 42ペア全てで `sentence_indices` が空（`[]`）。LLMがインデックスを返していない。

**原因**: LLM（DeepSeek V3.2）がプロンプト内の `(N)` 番号付きフォーマットを正しく認識・活用できていない可能性。または出力トークン制限で省略。

**解決策**:
1. LLMレスポンスのraw JSONを保存してデバッグ（`output_dir / "debug_llm_responses/"` に保存）
2. sentence_indices が空のペアを検出した際にWARNINGログを出力
3. プロンプトを改善: 番号指定の例を具体的に複数示す、few-shot例を追加
4. 代替アプローチ: TF-IDF/embeddingベースでsummaryに最も近い文を自動選択

**対応**: プロンプト改善後、実データで `q_full_text` 長が 26〜843 文字とばらつく値を確認（旧データのように全 0 ではない）。`docs/ISSUES2.md` 1-2 にて、それでも空 `sentence_indices` が混入した場合の保存抑制を残課題として追跡。

### 1-3. [Resolved] 姓の先頭2文字マッチングが不正確 — 📋 法案関連

**現象**: `_fuzzy_lookup()` は `name[:2]` で姓マッチングを行うが、1文字姓（林、森など）で誤マッチする。

**原因**: `surname = name[:2] if len(name) >= 2 else name` — 例えば「森英介」の場合 `surname="森英"` となり、「森田」や「森山」にもマッチしうる。

**解決策**:
- 姓の文字数を推定する関数を追加（2文字姓・3文字姓のパターン辞書）
- または、Levenshtein距離で最も近い名前を選択
- 最低限: マッチが複数候補ある場合は完全一致を優先、なければ最短一致

**対応**: `src/speaker_lookup.py` に切り出し、`SINGLE_CHAR_SURNAMES`（林・森・原・関 ほか）を frozenset 化、`find_by_name` が prefix 長 (2,1,3) を順に試行する `allow_single_char` ゲート付きアルゴリズムを実装。`structurer._fuzzy_lookup` はその互換ラッパー。テストは `tests/test_speaker_lookup.py`。

### 1-4. [Resolved] SQLite並行アクセスの競合

**現象**: `state.py` にロック機構がなく、複数パイプラインプロセスが同時に同じDBにアクセスすると破損の恐れ。

**原因**: `sqlite3.connect()` のデフォルトはスレッドセーフだが、プロセス間では WAL モードが必要。現在PRAGMA設定なし。

**解決策**:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

**対応**: `state.py:18-21` で `check_same_thread=False` + `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` を実装済み。なお現状 `state.py` 自体は `batch.py`/`pipeline.py` から未使用（`docs/ISSUES2.md` 3-2 でデッドコード化を別課題として追跡）。

### 1-5. [Resolved] 文分割が「。」のみ対応

**現象**: `_split_sentences()` は `。`（句点）でのみ分割。`？`、`！`、`…。` などのパターンに対応していない。

**影響**: sentence_indicesの番号と実際の文がずれる可能性。

**解決策**: 正規表現で `。|！|？` + 後続空白で分割。括弧内の句読点は除外。

**対応**: `structurer.py:54` で `re.split(r'(?<=[。？！])', text)` を採用。

### 1-6. [Resolved] LLMレスポンスのJSON解析にエラーハンドリングなし

**現象**: `structurer.py:298` の `json.loads(content)` は malformed JSON で例外が出る。

**解決策**: try/except で囲み、パースエラー時はログ出力して空配列を返す。リトライも検討。

**対応**: `structurer.py:340-343, 683-686` で `json.JSONDecodeError` を捕捉して `logger.error` + 空リスト/早期 return を実装。

### 1-7〜1-9. [Migrated → STRUCTURER_REWRITE.md]

以下の3項目はパイプライン完全刷新計画に取り込み、本書から削除した:

- **1-7 speaker_tagger.py の LLMレスポンス検証 (json.loads 残課題)** → `docs/STRUCTURER_REWRITE.md §2.15 パイプライン堅牢性`
- **1-8 video_url がセグメント単位で同一 (ペア単位の精度向上)** → `docs/STRUCTURER_REWRITE.md §2.13 timestamp_inconsistency`
- **1-9 follow_up_ids 未実装** → `docs/STRUCTURER_REWRITE.md §2.14 other`

### 1-10. [Resolved] Dockerfileにffprobeが含まれていない可能性

**現象**: `audio/extractor.py` は ffprobe を使って動画の長さを取得するが、Docker imageに ffprobe が含まれているか未確認。

**解決策**: Dockerfileで `ffmpeg` パッケージをインストールすれば通常 `ffprobe` も含まれるが、明示的に確認。

**対応**: Docker 構成自体を廃止（CLAUDE.md 参照）。`batch.yml` の ingest ジョブで `apt-get install -y ffmpeg` を直接実行しており、ubuntu-latest の `ffmpeg` パッケージは ffprobe を同梱するため問題なし。

---

## 2. 静的サイト（site/）

### 2-1. [Resolved] 「全文を表示」が全ペアで同じテキストを表示 — 📋 法案関連

**現象**: 同一セグメント内のQ&Aペアの全文展開が全て同じテキスト。ユーザーが「このQ&Aの該当部分」を読みたいのに、長いテキスト全体が表示される。

**原因**: 上記 1-1 のデータ品質問題が直接的原因。

**解決策**: データ品質を修正すれば自然に解消。UI側での追加対策として:
- full_text が空の場合は「全文を表示」ボタンを非表示
- 同一セグメント内で重複するfull_textの場合、「セグメント全文」と表示して誤解を防ぐ

**対応**: 1-1 の解消によりデータ側で重複が消えたため、UI 側の表示も自動的に改善。

### 2-2. [Resolved] browse ページのbase path 取得が不統一

**現象**: コンポーネントによって base path の取得方法が異なる:
- `FilterPanel.jsx`: `import.meta.env.BASE_URL`
- `SessionCalendar.jsx`: `document.querySelector("base")?.href`
- `TopicHeatmap.jsx`: 同上

**リスク**: いずれかの方法が特定環境で失敗するとリンク切れ。

**解決策**: Astro親コンポーネントから `base` をpropsで渡す方式に統一。

**対応**: `FilterPanel.jsx`、`SessionCalendar.jsx`、`TopicHeatmap.jsx`、`CommitmentTracker.jsx` のすべてが `import.meta.env.BASE_URL` 経由に統一済み。`document.querySelector("base")` パターンは消滅。

### 2-3. [Resolved] OGP・SEOメタタグの欠如

**現象**: `<meta property="og:*">` タグ、`<meta name="description">` が未設定。SNSでシェアした際にプレビューが表示されない。

**解決策**: `BaseLayout.astro` にOGPタグを追加。各ページからtitle/descriptionをslotで渡す。

**対応**: `site/src/layouts/BaseLayout.astro:16-20` で `meta name="description"` / `og:title` / `og:description` / `og:type` / `og:locale` を実装。Props で title/description を受ける。

### 2-4. [Resolved] ダッシュボードページがデータ1セッションのみ

**現象**: ヒートマップ、トレンドチャート、回避度ランキング等がデータ1件のため実質的に意味をなさない。

**影響**: ユーザー体験としてダッシュボードが寂しい。

**解決策**: 複数セッションのデータを蓄積した後に評価する。現段階では「データが蓄積されると充実します」等のメッセージを表示。

**対応**: バッチ運用が回り始め、`data/` 配下に両院多数（2026-02 以降の衆議院、2026-04 以降の参議院）のセッションが蓄積済み。ダッシュボードは実用レベルの分布を表示する。

### 2-5. [Resolved] generate-api.ts と data.ts で型定義が重複

**現象**: `scripts/generate-api.ts` と `src/lib/data.ts` で `QAPair`、`SessionMetadata` 等の型が独立に定義されている。

**リスク**: 片方を変更した際にもう一方との不整合が起きる。

**解決策**: 共通の型定義ファイル（`src/types.ts`）を作成し、両方からimport。

**対応**: `site/src/types.ts` を共通ソースに据え、`generate-api.ts` も `src/lib/data.ts` も同ファイルから `SessionMetadata` / `QAPair` / `QAPairsOutput` 等を import する形に統一済み。

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

### 3-1. [Migrated → STRUCTURER_REWRITE.md §2.16] 衆議院スクレイパーのDOM構造依存

`docs/STRUCTURER_REWRITE.md §2.16 スクレイパー堅牢性` に取り込み。

### 3-2. [Resolved] 参議院の動画 URL 解決と過去日付検索

**動画 URL 解決 (mediasp.jp hash → m3u8)**:
`public.mediasp.jp/v1/player?hash=XXX` のレスポンス本文に `video_info[0].url` として
m3u8 URL が直書きされていることを確認した (実 URL: `sangiin-vod.live.ipcasting.jp/...`)。
`audio/sangiin_resolver.py` の regex が実応答に対して動作することを実証済み。
Playwright は不要。

**過去日付のセッション検出**:
POST `keyword_search.php` が F5 BIG-IP ASM Bot Defense で保護されており、
素の HTTP クライアント (urllib / requests / curl_cffi + chrome impersonate)
は全て "Request Rejected" で弾かれる。Playwright + playwright-stealth +
信頼イベント (実マウスクリック) でのみ通過可能。
`src/scrapers/_sangiin_search.py` で実装済み。`detect_new_sessions(date)` は
本日 (JST) のみ GET 軽量経路、それ以外を Playwright 経路に自動分岐する。

依存: `pip install -e '.[browser]'` && `python -m playwright install --with-deps chromium`

### 3-3. [Migrated → STRUCTURER_REWRITE.md §2.16] 日付 "unknown" のフォールバック

`docs/STRUCTURER_REWRITE.md §2.16 スクレイパー堅牢性` に取り込み。

---

## 4. テスト

### 4-1. [Resolved] structurer のsentence_indices関連テストが不足

**不足テスト**:
- sentence_indices が空配列の場合の振る舞い
- sentence_indices が範囲外の場合
- 空セグメント（utterancesなし）の場合
- fuzzy_lookup の1文字姓・一致なしケース

**対応**: `tests/test_structurer.py` に「範囲外インデックスは無視される」「全て範囲外なら空文字」「`sentence_indices: []` ケース」「evasion_score の範囲外クランプ」等のユニットテストを追加。1 文字姓・複数候補ケースは `tests/test_speaker_lookup.py` に分離して網羅。

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

### 5-2. [Resolved] API キー管理が分散

**現象**: `DEEPINFRA_API_KEY` を `transcriber.py`、`speaker_tagger.py`、`structurer.py` がそれぞれ独立に取得。

**解決策**: `src/api_client.py` に共通クライアントファクトリを作成。

**対応**: `src/api_client.py` を実装し、共通の `DEEPINFRA_BASE_URL` / `MAX_WORKERS_*` 設定 / `with_retry`（指数バックオフ + ジッター）/ `ensure_fd_limit` を集約。各ステップ（transcriber, speaker_tagger, structurer, transcript_corrector）はここから利用する。

### 5-3. [Resolved] publisher.py が origin/main 固定

**現象**: `git push origin main` がハードコード。デフォルトブランチ名が異なるリポジトリで失敗。

**解決策**: `git symbolic-ref refs/remotes/origin/HEAD` でデフォルトブランチを自動検出。

**対応**: `publisher.py:15-23` の `_get_default_branch()` で `git symbolic-ref refs/remotes/origin/HEAD` を呼び、失敗時のみ `"main"` フォールバック。`publisher.publish_session` と `batch._batch_push` の双方が同関数を共有。

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

### 6-2. [Migrated → STRUCTURER_REWRITE.md §2.17] 法案タグの精度検証手段がない

`docs/STRUCTURER_REWRITE.md §2.17 法案タグ精度検証` に取り込み。

### 6-3. [Resolved] 法案マスタの更新フロー

**現象**: laws.md は手動更新。国会開会中に法案が追加・修正される。

**解決策**:
- 衆議院・参議院のWebサイトから法案一覧をスクレイピングする自動更新スクリプト（将来的）
- 当面は手動更新で対応。laws.md 更新時に `parse_laws.py` を再実行

**対応**: `src/laws_builder.py` を実装し、CLB（閣法; `scrapers/clb.py`）と Gian（衆法/参法; `scrapers/gian.py`）から法案一覧を統合スクレイピングして `data/laws/laws.json` と `laws_compact.txt` を生成。`batch.yml` の discovery ジョブで `python -m src.laws_builder --sessions 221` が走り、毎時更新される。

---

## 優先度まとめ（2026-05-10 時点）

### 解消済み

| ID | 概要 | 📋 法案関連 |
|----|------|:---:|
| 1-1 | full_text が Q&A ペアごとに正しく分割されない | Yes |
| 1-2 | sentence_indices が全ペアで空 | Yes |
| 1-3 | 姓の prefix マッチング不正確（1 文字姓） | Yes |
| 1-4 | SQLite 並行アクセス（PRAGMA 未設定） | |
| 1-5 | 文分割が `。` のみ | |
| 1-6 | LLM JSON 解析にエラーハンドリング無し | |
| 1-10 | Dockerfile の ffprobe（Docker 廃止で moot） | |
| 2-1 | 全文表示が重複（1-1 連鎖） | Yes |
| 2-2 | base path 取得方法の不統一 | |
| 2-3 | OGP / SEO メタタグ欠如 | |
| 2-4 | ダッシュボードがデータ少なすぎ | |
| 2-5 | generate-api.ts と data.ts の型重複 | |
| 3-2 | 参議院 mediasp.jp / 過去日付検索 | |
| 4-1 | structurer の sentence_indices テスト不足 | |
| 5-2 | API キー管理の分散 | |
| 5-3 | publisher.py の origin/main ハードコード | |
| 6-1 | 法案フィルタの実装 | Yes |
| 6-3 | 法案マスタの更新フロー | Yes |

### 残課題

| 優先度 | ID | 概要 | 備考 |
|--------|-----|------|------|
| Medium | 4-2 | LLM レスポンス異常系テスト | 一部のみ |
| Medium | 4-3 | スクレイパーのエンコーディング異常系テスト | フィクスチャ readBytes は対応済み、悪条件テスト未追加 |
| Medium | 5-1 | 依存バージョンピン不足 | `docs/ISSUES2.md` 3-6 で再追跡 |
| Low | 2-6 | SessionCalendar のキーボードナビ未対応 | |
| Low | 2-7 | Pagefind の事前読み込みなし | |
| Low | 2-8 | settings ページがプレースホルダ | Phase 6 待ち |
| Low | 4-4 | 並行処理のテストなし | |

### パイプライン完全刷新計画に取り込んだ項目（残課題から削除）

下記はデータ生成起因のため、`docs/STRUCTURER_REWRITE.md` で統合管理する:

| ID | 概要 | 移管先 |
|-----|------|--------|
| 1-7 | speaker_tagger の json.loads 例外捕捉 | §2.15 パイプライン堅牢性 |
| 1-8 | video_url がセグメント単位で同一 | §2.13 timestamp_inconsistency |
| 1-9 | follow_up_ids が未実装 | §2.14 other |
| 3-1 | 衆議院スクレイパーの DOM 構造依存 | §2.16 スクレイパー堅牢性 |
| 3-3 | 参議院スクレイパーの日付 "unknown" フォールバック | §2.16 スクレイパー堅牢性 |
| 6-2 | 法案タグ精度の検証手段 | §2.17 法案タグ精度検証 |

`docs/ISSUES2.md` には本ドキュメント作成後の第 2 次監査で見つかった項目（CI/CD・サイト堅牢性等）を別途整理してある。データ生成起因のものは ISSUES2 側でも `STRUCTURER_REWRITE.md` に移管済。

### 処理済みセッションと法案の対応

| セッション | 委員会 | 日付 | 主要関連法案 |
|-----------|--------|------|-------------|
| 56149 | 本会議 | 2026-04-09 | 健康保険法等の一部を改正する法律案（厚生労働省） |

※ 上記セッションの42 Q&Aペアのうち、大半が健康保険法改正案に直接関連。一部ペア（中東情勢・エネルギー関連）は外為法改正案に間接的に関連。
