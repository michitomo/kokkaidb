# パイプライン完全刷新計画 — 監査結果に基づく全カテゴリ対応

国会議事録 DB 全156セッションのうち 90セッション・1,202件の品質監査を実施し、13カテゴリの問題を発見した。さらに 4セッションで Step 4.5+ 再実行検証を行い、47件中の解消率は 19% (9/47) にとどまり、退行 2セッションも確認された。

本書は **全ステップ刷新 + 全データ再生成** を前提に、各問題カテゴリへの採用方針と段階的検証戦略を統合的に記述する。スコープを限定せず、データ精度の最大化を優先する。

---

## 0. 実装前提

### 0.1 全データ削除

実装前にすべての生成済みデータを削除する:

```bash
cd /Users/michitomo/git/kokkaidb

# バックアップ (任意)
git tag pre-rewrite-snapshot

# 全削除
rm -rf data/shugiin data/sangiin
rm -rf data/search-index
rm -f site/public/api/search-index.json

# 状態DBもリセット
rm -f kokkai-transcriber/state.db kokkai-transcriber/state-*.db
```

### 0.2 段階的検証で進める

修正後いきなり全件再生成せず、**サンプル → 検証 → ゴーサイン → 次フェーズ** の順で進める。詳細は §3。

---

## 1. 監査結果サマリ

### 1.1 監査範囲

- 期間: 2026-05-10
- 対象: 90/156 セッション (Sonnet 並列監査)
- 形式: `docs/QUALITY_AUDIT_FORMAT.md` 準拠の JSON
- 結果: `docs/audit-results/*.json` (90ファイル)

### 1.2 全体統計

| 指標 | 値 |
|---|---|
| セッション数 | 90 |
| 発見総数 | 1,202件 |
| 重要度 高 | 325件 |
| 重要度 中 | 515件 |
| 重要度 低 | 362件 |
| 平均 finding 数/セッション | 13.4 |
| 「品質高」と判定されたセッション | **0** |
| 「品質低」と判定されたセッション | 9 |

### 1.3 カテゴリ分布 (頻度順)

| # | カテゴリ | 件数 | 出現セッション率 | likely_systemic |
|---|---|---:|---:|---:|
| 1 | `whisper_misrecognition` | 269 | 96% | 195 |
| 2 | `schema_empty_field` | 186 | 100% | 183 |
| 3 | `schema_inconsistency` | 137 | 90% | 127 |
| 4 | `speaker_misattribution` | 110 | 73% | 90 |
| 5 | `content_missing` | 85 | 70% | 56 |
| 6 | `role_label_error` | 74 | 63% | 67 |
| 7 | `metadata_missing_speaker` | 71 | 73% | 68 |
| 8 | `summary_qa_divergence` | 70 | 67% | 41 |
| 9 | `whisper_hallucination_loop` | 62 | 48% | 52 |
| 10 | `fact_error` | 43 | 44% | 30 |
| 11 | `duplicate` | 35 | 37% | 27 |
| 12 | `other` (follow_up_ids 等) | 32 | 31% | 21 |
| 13 | `timestamp_inconsistency` | 27 | 30% | 26 |

加えて既知の **`transcript_truncation`** (qa_pairs.json の `full_text` 途切れ) は監査対象外として別カテゴリで扱う (§2.1)。

### 1.4 Step 4.5+ 再実行検証の結果

4セッション (56074, 56075, 56211, 8967) で Step 4.5 (transcript_corrector) → 5 → 5.5 → 6 を再実行し、47 findings を比較:

| 状態 | 件数 | 割合 |
|---|---:|---:|
| RESOLVED | 9 | 19% |
| PARTIAL | 7 | 15% |
| UNCHANGED | 28 | **60%** |
| NEW_ISSUE (退行) | 2 | 4% |
| NA_BY_DESIGN | 1 | 2% |
| NEW_ONLY (新規発生) | 8 | + |

セッション別: 56074 = 退行, 8967 = 退行, 56211 = low improvement, 56075 = medium improvement。

**結論**: Step 4.5+ だけでは多くの問題が UNCHANGED で残り、リグレッションも発生する。全ステップ刷新が必要。詳細は `docs/PIPELINE_FIX_STATUS.md` および `docs/regen-comparison/*.json`。

---

## 2. カテゴリ別 観察 → 採用方針

各カテゴリで「観察」「現コード状態」「採用方針」「実装箇所」を列挙する。

### 2.1 transcript_truncation — qa_pairs の full_text 途切れ

**観察**: `answer.full_text` が末尾切れ 21.1%、`question.full_text` が末尾切れ 52.5% (衆議院138セッション・5,770ペアでの集計)。例: 56209 厚生労働委員会 qa_022 で田中局長答弁の「お答えいたします…」「令和7年7月に拡充…75万円を助成」が消失。

**現コード状態**: NOT FIXED。`structurer.py` が LLM に `sentence_indices` を返させ、コードで連結する設計。LLM が末尾文を選び忘れる失敗モードを構造的に防げない。

**採用方針**: **utterance_indices ベーススキーマへの全面移行**。LLM に文番号配列ではなく utterance 番号配列を返させ、`full_text` はコードが utterance 全文を連結する。複数ペアが共有する utterance には sentence-level anchor で境界を明示。詳細は **Appendix A**。

**実装箇所**:
- `src/prompts.py:QA_SEGMENT_SYSTEM_PROMPT` 全面書き換え (V2)
- `src/structurer.py` `_extract_pairs_from_response` / `_generate_qa_for_segment` / 文番号関連ヘルパー全面書き換え
- `src/models.py` `QuestionDetail` / `AnswerDetail` 整合確認
- `_INPUT_CHAR_LIMIT = 20000` 撤廃または `_split_segment_into_blocks` ベース分割に置換

**期待解消率**: ~95%

---

### 2.2 schema_empty_field — answer.role 99%空、metadata 必須項目空

**観察**:
- `answer.role` が全 qa_pairs の 99% で空文字列 (例: 8967 で 107/139 ペア空)
- `metadata.duration` 衆議院は取得済 / 参議院は空、`committee_id` / `session_number` 全セッション null
- `metrics` null 24.6% (検証評価指標が一部欠損)
- `follow_up_ids` 全件空配列、`related_law_ids` 一部空

**現コード状態**: NOT FIXED。`answer.role` 空の根本原因は metadata.speakers に答弁者 (大臣・政府参考人) が未登録のため `_resolve_answerer_from_sentences` が空文字を返す。Step 4.5+ 再実行でも UNCHANGED (6/7)。

**採用方針**: 複合対応:
- **A1: utterances → metadata.speakers 逆補完** (Step 5↔5.5 間に enrichment ステップを新設)。speaker_tagger が抽出した発言者 (`role∈{答弁者, 政府参考人}`) で `metadata.speakers` に未登録のものを追記。Step 5.5 normalizer が拡張済 metadata.speakers でマッチングして role を埋める
- `committee_id` / `session_number` を scraper で取得 (TV ページの `第◯回` 表示 + 委員会名→ID 辞書)
- `duration` を sangiin scraper でも取得 (要 HTML 調査)
- `follow_up_ids` / `related_law_ids` の充足は §2.12 / §2.7 と統合

**実装箇所**:
- `src/pipeline.py` Step 5↔5.5 間に `enrich_metadata_from_utterances()` 挿入
- 新規 `src/metadata_enricher.py` (~80行)
- `src/scrapers/shugiin.py` / `sangiin.py` `_extract_committee_id`, `_extract_session_number`, `_extract_duration` 追加 (~50行)
- `src/normalizer.py` `coerce_role` で答弁者 affiliation を空のままにせず推定値を入れる

**期待解消率**: ~85%

---

### 2.3 metadata_missing_speaker — 答弁者・政府参考人が metadata.speakers 未登録

**観察**: 大臣・政府参考人 平均30名/セッションが metadata.speakers から欠落。例: 8968 で 12名全員 (林芳正・高市早苗・堀内照男など) 未登録。

**現コード状態**: NOT FIXED。TV サイトのタイムスタンプリンクに答弁者リンクが存在しない (HTML仕様の制約)。Step 4.5+ では UNCHANGED 2/2。

**採用方針**: §2.2 の **A1 と同一機構** で連動解消。speaker_tagger 出力から `unmatched=true` & `role∈{答弁者, 政府参考人}` の発言者を metadata に逆補完。

加えて補強:
- 補完時の affiliation 推定: utterance テキストから「○○大臣」「○○局長」等の役職パターン正規表現抽出
- 同名異人問題の緩和: 既存 `metadata.speakers` との fuzzy 重複検出 (`speaker_lookup.find_by_name` を allow_single_char=True で再利用)

**実装箇所**: §2.2 と統合 (`src/metadata_enricher.py`)

**期待解消率**: ~85%

---

### 2.4 duplicate — metadata.speakers の重複エントリ

**観察**: 同一人物が複数エントリ (例: 8986 予算委員会で辰巳孝太郎が3エントリ、長友・和田・高山が各2エントリ。本会議の山下貴司が午前/午後で2エントリ)。

**現コード状態**: NOT FIXED。`scrapers/{shugiin,sangiin}.py` の `_extract_speakers` に dedup なし。`speaker_lookup.build_lookup` は最初の登場のみ採用するため downstream 影響は限定的だが、`metadata.json` 自体には重複が残る。

**採用方針**: **scraper レベルで `(name, affiliation)` キーで dedup**。同一人物の複数持ち時間スロットは `start_seconds` の最小値を保持、`duration_minutes` は合算。

```python
# scrapers/shugiin.py / sangiin.py 共通
seen: dict[tuple[str, str], SpeakerInfo] = {}
for sp in raw_speakers:
    key = (sp.name, sp.affiliation)
    if key in seen:
        # 既存エントリに duration を合算、start_seconds は若い方
        existing = seen[key]
        existing.duration_minutes += sp.duration_minutes
        existing.start_seconds = min(existing.start_seconds, sp.start_seconds)
    else:
        seen[key] = sp
unique = list(seen.values())
```

**実装箇所**: `scrapers/shugiin.py:_extract_speakers`, `scrapers/sangiin.py:_extract_speakers` (~10行 × 2)

**期待解消率**: ~95%

---

### 2.5 whisper_hallucination_loop — Whisperの繰り返しループ

**観察**: 「議長＊小寺君。」が 6,904回繰り返し (56075 本会議、約115分相当が消失)。「ご視聴ありがとうございました。」がセグメント全体を占有。「最高裁判所で性同一性障害特例法に、国会議員」の文脈外テキスト混入。

**現コード状態**: PARTIAL FIXED。Whisper prompt V2 (`transcriber.py:26-57`) でループ誘発源 3系統 (石井副議長・法律名・出席議員リスト) を除去済。ただし旧 raw_transcript.json は V1 で生成されており、ループが永続。Step 4.5+ で transcript_corrector がループ除去を試みるが 80%縮小チェック (`transcript_corrector.py:319-336`) が極端ケースで棄却し残存。再実行検証では 1/4 のみ resolved。

**採用方針**: 複合対応:
- **完全再生成 (Step 3-4 含む) で V2 prompt を全セッションに適用**
- transcript_corrector の **安全チェック緩和**: ループ判定時 (`pattern が連続 3回以上反復) は 80%縮小制約を無効化
- corrector の除去ルール強化: 「同一文の3回以上繰り返し」「`議長＊○○君` 等の挿入句」を明示的に検出して削除

**実装箇所**:
- `src/transcriber.py` Whisper prompt V2 (既存、確認のみ)
- `src/transcript_corrector.py:319-336` 安全チェック条件分岐 (~20行)
- `src/transcript_corrector.py:56-63` プロンプトのループ除去ルール強化 (~10行)

**期待解消率**: ~70-80%

---

### 2.6 whisper_misrecognition — 人名・地名・固有名詞の誤認識

**観察**: 269件 (96% のセッションに発生)。例:
- 「木原稔」→「木川田」「木原大臣」を context なしで補正できず
- 「八潮市」→「八代市」(LLM補正による地名書き換え)
- 「OSA (Official Security Assistance)」→「OSC」(LLM が存在しない略語に変換)
- 「財政投融資計画」→「財政投入計画」
- 「れいわ新選組」→「令和新選組」、「参政党」→「賛成党」

**現コード状態**: PARTIAL FIXED。transcript_corrector が `metadata.speakers` を context として固有名詞補正するが、speakers にない人物 (政府参考人・局長) は補正できない。`_WHISPER_PROMPT_BASE` には閣僚7名のみ列挙。

**採用方針**: 複合対応:
- **§2.2 A1 連動**: enrichment で metadata.speakers に答弁者を追加 → corrector の context が拡充される
- **拡張閣僚リスト**: 第221回国会の現職閣僚16名 + 主要参議院議員リスト + 主要政党名 (れいわ新選組・参政党等) を `_WHISPER_PROMPT_BASE` に列挙
- corrector 禁止事項の強化: 「存在しない略語の創作禁止」「公的固有名詞の改変禁止 (地名・法律名・政府機関名)」を明示

**実装箇所**:
- `src/transcriber.py:_WHISPER_PROMPT_BASE` (~30行追加)
- `src/transcript_corrector.py` プロンプト禁止事項追加 (~20行)
- `src/scrapers/_role.py` または専用ファイルに「閣僚リスト」「主要委員会委員長リスト」を定義 (~50行)

**期待解消率**: ~50-60%

---

### 2.7 fact_error — LLM 補正による事実改変

**観察**: 43件。例:
- 「八潮市」→「八代市」(熊本県と埼玉県の混同)
- 「OSA」→「OSC」(存在しない略語の創作)
- 「総理大臣秘書官」→「総理大臣正官」(存在しない役職)
- 参議院セッション summary が「衆議院において」と誤記
- LLM が括弧注釈を勝手に挿入

**現コード状態**: PARTIAL FIXED。`session_meta` で chamber/committee を明示渡しすることで院名誤記は構造的に解消済。corrector の禁止事項で抑制されているが完全には防げない。Step 4.5+ で 1/1 resolved。

**採用方針**: 現状維持 + §2.6 の禁止事項強化と統合。追加で:
- summary 生成時の **post-validation**: chamber/committee/date が出力に含まれる場合、入力 metadata と一致することを検証 → 不一致なら 1回リトライ
- corrector の禁止事項に「存在しない略語・役職名・地名の創作禁止」を追加 (§2.6 と統合)

**実装箇所**:
- `src/structurer.py` `generate_session_summary` post-validation 追加 (~30行)
- `src/transcript_corrector.py` プロンプト (§2.6 と統合)

**期待解消率**: ~70%

---

### 2.8 speaker_misattribution — 話者誤帰属

**観察**: 110件 (49 high-severity)。例:
- HLS 境界で次話者の発言が前話者にラベル付け
- 56211 で qa_069 質問者が「川裕一郎」だが実際は「中村はやと」 (Whisper が「中村君」を「長妻君」と誤認識し、speaker_tagger が前話者の長妻昭に帰属)
- 56075 で高市演説 (segment 2) の一部が茂木・片山・城内実に分割される誤帰属

**現コード状態**: PARTIAL FIXED。speaker_tagger 5/5 PASS の改善 + `_split_segment_into_blocks` で委員長指名境界の処理が強化済。Step 4.5+ で 1/2 resolved。

**採用方針**: 現状維持 + §2.2 A1 連動 (metadata.speakers 拡充により speaker_tagger の context が改善)。追加で:
- speaker_tagger プロンプトに「委員長による呼名 (`○○君。`) の直後は新話者」のルール明示 (既に R1 で実装済、再確認)
- HLS audio 分割の境界精度向上は本刷新では対応しない (要別途調査、将来課題)

**実装箇所**:
- `src/speaker_tagger.py` プロンプト確認・微調整 (~20行)
- §2.2 A1 と統合

**期待解消率**: ~60%

---

### 2.9 role_label_error — role フィールドの誤分類

**観察**: 74件 (23 high-severity)。例:
- 「石田真敏」(臨時委員長) が全発言 `role=質疑者` (56078)
- 「森英介」(議長) の開会宣言が `role=質疑者` (56075)
- 事務総長 (築山信彦) → 質疑者
- 副大臣・政務官 → 質疑者

**現コード状態**: PARTIAL FIXED。`scrapers/_role.py:derive_role` で affiliation から決定論的に派生済。Step 5.5 normalizer が補正。ただし「臨時委員長」「事務総長」「副大臣」「政務官」等の特殊ケースは現 `derive_role` が捕捉できず質疑者扱いになる。

**採用方針**: **`derive_role` の特殊ケース拡張**:
- `affiliation == "事務総長"` → `role=委員長相当` (進行役)
- `affiliation` に「臨時委員長」を含む → `role=委員長`
- `affiliation` に「副大臣」「政務官」「副議長」「事務総長」を含む → `role=答弁者` (質疑者ではない)
- 一般議員でも発言テキストの先頭が「日程第○、議事を…」「○○君。」(指名) で始まれば臨時委員長とみなす (heuristic)

**実装箇所**:
- `src/scrapers/_role.py:derive_role` 拡張 (~30行)
- `src/normalizer.py` heuristic role 上書き (~20行)

**期待解消率**: ~70%

---

### 2.10 content_missing — segment 全体が qa_pairs から欠落

**観察**: 85件 (45 high-severity)。例:
- 56075 で片山さつき財政演説 3,588字が qa_pairs に1件もない
- 56211 で中村はやとのQ&A完全欠落 (`川裕一郎` への誤帰属で全件吸収された結果)
- 8967 segment 4 (司隆史) の Q&A が完全欠落
- 56074 で議長選挙・副議長選挙の qa_001/qa_002 が消失

**現コード状態**: PARTIAL FIXED。`_split_segment_into_blocks` + QA密度リトライ実装済。`_INPUT_CHAR_LIMIT=20000` のハードカットあり (TODO comment で sub-block ベースに置換予定と記載)。Step 4.5+ で 1/5 resolved + 1件 NA_BY_DESIGN + リグレッション発生 (8967 segment 3 が 10→1 ペアに激減)。

**採用方針**: **§2.1 utterance_indices schema と統合**:
- `_INPUT_CHAR_LIMIT` 撤廃。代わりに `_split_segment_into_blocks` で必ず質疑者単位に分割し、ブロックごとに LLM 呼び出し
- session_kind = `floor_speech` でも、所信表明・施政方針演説等は **summary は生成、qa_pairs はスキップ** という現挙動を維持しつつ、`utterances` のテキストから直接 `topics` / `key_topics` を生成する経路を追加 (QA非依存 summary)
- LLM リトライ条件強化: ブロック内の QA 件数が話者数の半分未満なら警告 + リトライ

**実装箇所**:
- `src/structurer.py:_INPUT_CHAR_LIMIT` 撤廃 (`structurer.py:412-422`)
- `src/structurer.py` ブロック分割後の QA密度チェック強化 (~30行)
- `src/structurer.py:_extract_pairs_from_response` (340-380) の drop 条件に **`q_full_text == ""` の追加** (旧 `ISSUES2.md §1-2` 由来。`a_full_text` のみで判定していたため、空質問が混入していた問題)
- `src/structurer.py:_assemble_full_text_from_sentences` (94-100) の範囲外 indices 比率を計測 → 50% 超なら WARN ログ
- `src/structurer.py:_extract_pairs_from_response` 末尾に受理/drop 統計サマリの 1行ログ追加
- 新規: `generate_topics_without_qa()` (utterances ベース、~50行)
- `src/pipeline.py:_run_step6` の floor_speech 分岐拡張

**期待解消率**: ~70%

---

### 2.11 summary_qa_divergence — summary と qa_pairs の内容乖離

**観察**: 70件。例:
- `summary.session_summary` が qa_pairs にない事実を言及 (56074 で「PM指名」「副議長選挙」等)
- `summary.key_commitments` の `speaker` が qa_pairs と不一致 (高市/片山の取り違え)
- `qa_id` が存在しない値を参照
- key_topics が qa_pairs から外れたトピックを含む

**現コード状態**: PARTIAL FIXED。`structurer.py:794-805` で `qa_id` バリデーション (不正IDを drop) 実装済。commitments プロンプト V5 (F1=100%)。ただし `speaker` フィールドの一致確認は未実装で誤記リスク残る。Step 4.5+ で 1/4 resolved + 2件 NEW_ISSUE 発生 (退行)。

**採用方針**: **post-validation + リトライ機構**:
- summary 生成後、`key_commitments` の `(qa_id, speaker)` ペアが qa_pairs と一致するか検証
- 不一致なら該当ペアを drop (既存 qa_id バリデーションと同様)、削除後に件数が不足なら 1回リトライ
- session_summary テキストが qa_pairs にない固有名詞 (人名・法案名) を含む場合は警告ログ + リトライ
- `key_topics` が `topics.json` の `topics[].name` と完全一致するか検証

**実装箇所**:
- `src/structurer.py:generate_session_summary` post-validation 追加 (~50行)
- `src/structurer.py:generate_key_commitments` speaker 検証追加 (~30行)
- `src/prompts.py:SESSION_SUMMARY_SYSTEM_PROMPT` に「qa_pairs に存在する事実のみ言及せよ」を追加

**期待解消率**: ~70%

---

### 2.12 schema_inconsistency — null↔空文字混在、表記ゆれ

**観察**: 137件 (90% セッション)。例:
- `committee_id: null` と `duration: ""` の混在 (片や None、片や "")
- 同一人物の表記ゆれ (`城内` vs `城内大臣`、`斎藤` vs `斉藤`)
- `(N)` 連番の不整合 (segment4 の whisper_segment id が 0 始まり、他は 1 始まり)

**現コード状態**: PARTIAL FIXED。Step 5.5 normalizer で utterances 内の表記統一が実装済。ただし `metadata.speakers` 内の表記は scraper が決めるため、TV サイトの表記に依存。null/空文字は Pydantic Field のデフォルト値次第で混在。Step 4.5+ で 2/3 resolved。

**採用方針**: **null/空文字統一規約のモデル定義レベル明文化** + 現状の normalizer 維持:
- `models.py` で「未取得値は None、空文字列は意図的に空」を規約として明文化 (docstring)
- 数値型: `int | None = None` (現状維持)
- 文字列型: 必須なら `str = ""`、任意なら `str | None = None` (慎重に判断)
- 同名異字 (`斎藤` vs `斉藤`) は metadata.speakers の表記を正解として normalizer で統一 (既存実装)

**実装箇所**:
- `src/models.py` docstring 追記 (~20行コメント)
- 検証スクリプト追加: `scripts/validate_data_schema.py` で全セッションのスキーマ整合性をチェック (~50行)

**期待解消率**: ~85%

---

### 2.13 timestamp_inconsistency — start_seconds と start_time のズレ・video_url 精度

**観察**: 27件 + 旧 `ISSUES.md §1-8` 由来。例:
- `start_seconds=2050.3` と `start_time=12:14` が90分以上乖離 (8978: HLS 開始が 10:10 JST)
- `start_time` (`HH:MM` 形式) と `start_seconds` (HLS秒数) が異なる基準系
- `video_url` の `time=` パラメータが他話者の値
- **同一セグメント内の全 Q&A ペアが同じ `video_url` を持ち、ペア単位のタイムスタンプ精度がない** (`ISSUES.md §1-8` Low: utterance 単位の `start_seconds` を活用すべき)

**現コード状態**: PARTIAL FIXED。`detect_leading_silence` + offset 補正で 30秒超のズレは補正される (`pipeline.py:175-193`)。Step 4.5+ で 1/1 resolved。`video_url` のペア単位精度向上は未実装。

**採用方針**: 現状維持 + 補強:
- `detect_leading_silence` の閾値 (現 30秒超) を **5秒超** に下げる
- `start_time` と `start_seconds` の不整合を pipeline 終盤で検出 → 警告ログ
- `video_url` 生成時に **Q&A ペアの開始 utterance の `start_seconds` を使う** (現在のセグメント単位ではなくペア単位)
- 将来的には Whisper word-level timestamps 活用で更に高精度化 (本刷新スコープ外、§7 未解決論点)

**実装箇所**:
- `src/pipeline.py:175-193` 閾値調整 (1行)
- `src/pipeline.py` 終盤に整合性チェック追加 (~20行)
- `src/structurer.py` qa_pairs 生成時、各ペアの `video_url` を `seg.utterances[utterance_indices[0]].start_seconds` から派生 (~10行)
- `src/models.py` `QAPair` の `video_url` フィールドが既に存在する想定 (要確認)

**期待解消率**: ~80%

---

### 2.14 other — その他

**観察**: 32件。主に:
- `follow_up_ids` 全件空配列 (フォローアップ追跡未実装)
- 参議院 `video_url` の `www.` 欠落 (`webtv.sangiin.go.jp` のまま、CLAUDE.md と矛盾)
- `related_law_ids` の集計が summary.related_laws に正しく反映されないケース
- topics の qa_id 帰属漏れ (1割のペアがどの topic にも属さない)

**現コード状態**: NOT FIXED。Step 4.5+ で UNCHANGED。

**採用方針**:
- **`follow_up_ids` 実装**: structurer で同一質疑者・連続 utterance の質問は前ペアの follow_up_ids に追加 (~50行)
- **video_url の `www.` 修正**: `speaker_tagger.py:208` で `https://www.webtv.sangiin.go.jp/...` に変更 (1行)
- **topics の qa_id 帰属漏れ**: topics 生成後、未帰属 qa_id があれば「その他」topic に集約 (~20行)
- **related_law_ids の集計**: `build_summary_related_laws` で qa_pairs.pairs[].related_law_ids を集計 (実装確認)

**実装箇所**:
- `src/structurer.py` follow_up_ids 生成 (~50行)
- `src/speaker_tagger.py:208` video_url 修正 (1行)
- `src/structurer.py:generate_topics_and_key_topics` 未帰属対応 (~20行)

**期待解消率**: ~80%

---

### 2.15 パイプライン堅牢性 — ffmpeg / LLM 応答ハンドリング

`docs/ISSUES.md` および `docs/ISSUES2.md` から取り込み。データ品質の category にはないが、生成パイプラインの reliability に直接影響するため本刷新スコープに含める。

**観察**:
- ffmpeg `subprocess.run` 全箇所 (`src/audio/extractor.py:91, 260, 317, 356, 379`) で `timeout=` 未指定 (旧 `ISSUES2.md §1-1` High)。HLS 配信が途中で停滞すると無限ハング、ingest ジョブの 180分 `timeout-minutes` でしか救えない
- `speaker_tagger.py` の `json.loads(content)` が try/except なしで残存しており `structurer.py` 側と粒度が揃っていない (旧 `ISSUES.md §1-7` Partial)。malformed JSON で例外伝播

**現コード状態**: NOT FIXED (ffmpeg) / PARTIAL FIXED (json.loads は `structurer.py` のみ対応済)。`publisher.py:65-71` の `_run_git` は既に `timeout=120` を使っており、パターンは確立済み。

**採用方針**:
- ffmpeg コマンドに用途別 timeout を設定:
  - HLS 直接 DL: `timeout=1800` (30分)
  - セグメント連結等の短命: `timeout=120`
  - メタ取得 (`_get_audio_duration`): `timeout=30`
  - `subprocess.TimeoutExpired` を捕捉して上位伝播 or フォールバック
- `speaker_tagger.py` の `json.loads` を try/except で囲み、`structurer.py:340-343, 683-686` と同等のエラー処理を実装

**実装箇所**:
- `src/audio/extractor.py:91, 260, 317, 356, 379` timeout 追加 (~10行)
- `src/speaker_tagger.py` `json.loads` ラップ (~10行)

**期待解消率**: ハング回避 100%、JSON parse エラー耐性向上

---

### 2.16 スクレイパー堅牢性 — DOM 依存・委員会推定・日付フォールバック

`docs/ISSUES.md` および `docs/ISSUES2.md` から取り込み。

**観察**:
- 衆議院スクレイパーの speaker 抽出が `<a href=re("time=")>` → 5階層上の `<tr>` という DOM 走査に依存。HTML レイアウト変更で即座に壊れる (旧 `ISSUES.md §3-1` Medium)
- 参議院スクレイパーで日付解析失敗時に `"unknown"` が返り、`data/sangiin/unkn/ow/n/` のような不正パスが生成される (旧 `ISSUES.md §3-3` Low)
- `find_committee_in_body` が下位タグまで全文走査し、本文に含まれる「○○委員会」言及で誤検知し得る (旧 `ISSUES2.md §4-2` Low)

**現コード状態**: NOT FIXED。

**採用方針**:
- DOM 期待構造のバリデーション関数を追加。期待タグ階層が見つからなければ WARNING ログ + `SessionNotReadyError` で再試行可能化
- HTML フィクスチャを `tests/fixtures/scraper_html/` に保存し、定期的に実サイトと比較するスモークテスト追加
- 日付解析失敗時は `RuntimeError` で stop (silent `"unknown"` フォールバック禁止)
- `find_committee_in_body` を `<title>` / `<h1>` / 上位 metadata DOM に限定 (本文走査の禁止)

**実装箇所**:
- `src/scrapers/shugiin.py` / `sangiin.py` DOM バリデーション追加 (~30行)
- `src/scrapers/sangiin.py` 日付解析の例外化 (~5行)
- `src/scrapers/shugiin.py:find_committee_in_body` スコープ制限 (~10行)
- `tests/fixtures/scraper_html/` HTML スナップショット (新規ディレクトリ)
- `tests/test_scrapers_smoke.py` 構造変化検出テスト (~50行)

**期待解消率**: DOM 構造変更検出 100% (silent failure を禁止)、誤検知 ~80% 削減

---

### 2.17 法案タグ精度検証

`docs/ISSUES.md §6-2` から取り込み。

**観察**: `tag_related_laws` による自動タグ付けの精度を検証する仕組みがない。誤タグ・タグ漏れが起きても気付けない。

**現コード状態**: NOT FIXED (検証手段未整備)。

**採用方針**:
- 手動アノテーション CSV を `tests/fixtures/laws_groundtruth.csv` に整備 (例: 20-30 セッション × 各3-5法案、合計 100件程度)
- `scripts/eval_law_tagging.py` で自動タグ付け結果と CSV を突合し、precision/recall/F1 を出力
- F2/F3 検証フェーズの go/no-go ゲートに「法案タグ F1 ≥ 0.6」を追加 (§3.2 検証ゲートに統合)

**実装箇所**:
- `tests/fixtures/laws_groundtruth.csv` 新規 (手動キュレーション ~100件)
- `scripts/eval_law_tagging.py` 新規 (~80行)
- `docs/STRUCTURER_REWRITE.md §3.2` 検証ゲートに F1 閾値追加

**期待解消率**: 検証可能性 0% → 100% (精度自体は別途改善対象)

---

## 3. 段階的検証戦略

修正後にいきなり全件再生成せず、サンプル → 検証 → ゴーサインの順で進める。

### 3.1 検証フェーズ

| フェーズ | サンプル | 主目的 | 進む条件 | 戻る条件 |
|---|---|---|---|---|
| **F0: smoke** | 1セッション (56074、最小) | パイプライン起動・I/O 確認 | exit 0 + 6ファイル出力 | クラッシュ |
| **F1: 既知問題サンプル** | 4セッション (56074, 56075, 56211, 8967) | 既存検証と同じセッションで改善確認 | 各セッション resolved ≥ 50%、新規 NEW_ISSUE = 0 | resolved < 30% or 新規退行 |
| **F2: 多様性サンプル** | 12セッション (タイプ別 1-2件) | 未調査セッションで未知問題 | finding 平均 ≤ 5件/セッション、未確認カテゴリ unchanged ≤ 2件 | 新カテゴリ多発 (3+) |
| **F3: 中規模スケール** | 30セッション | コスト・速度・並列度・横断統計 | F1/F2 整合、エラー率 < 5%、コスト/セッション < $0.5 | エラー率高、コスト過大 |
| **F4: 全件** | 156セッション | 本番再生成 | — | — |

### 3.2 検証ゲート (各フェーズで実施)

```
1. JSON妥当性: jq -e '.' で全ファイル parse 可能
2. スキーマ整合性: scripts/validate_data_schema.py 全パス
3. 既知 finding 解消率: 比較サブエージェント実行 → resolved 比率がフェーズ目標値以上
4. 新規 finding 件数: 各カテゴリで unchanged → resolved への遷移を確認、逆遷移ゼロ
5. リグレッション検出: 前フェーズで OK だった項目の再悪化チェック
6. コスト/時間/エラー: API 使用量、wall-clock、エラー率の閾値内
7. 法案タグ精度: `scripts/eval_law_tagging.py` の F1 ≥ 0.6 (§2.17、F2 以降のみ)
```

### 3.3 サンプル選定ルール

**F1 サンプル** (固定): 監査と Step 4.5+ 検証を両方やった既存サンプル。比較ベースラインがある。
- `shugiin/2026/02/18/56074_本会議` (議長/副議長選挙、role_label, summary_div)
- `shugiin/2026/02/20/56075_本会議` (施政方針、whisper_loop 6904回、speaker_misattrib)
- `shugiin/2026/04/24/56211_内閣委員会` (content_missing 中村、speaker_misattrib)
- `sangiin/2026/04/21/8967_内閣委員会` (whisper_misrecognition、schema_empty 多発)

**F2 サンプル** (12件、層化抽出):
- 本会議 / 委員会 / 特別委員会 各2-3件
- 衆議院 / 参議院 各6件
- 長尺 (3+ 時間) / 短尺 (~1時間) 各6件
- 公述人質疑あり / なし (公述人 high-impact カテゴリのため必須含)
- 「不明」フォルダのもの (56083_不明、56150_不明等の問題セッション)
- 監査未実施セッション優先 (Batch 10-16 の 66セッションから)

**F3 サンプル** (30件):
- F1 + F2 の 16件 + 新規 14件
- カバレッジ: 全 13カテゴリで少なくとも 3セッション

### 3.4 比較サブエージェント仕様

各フェーズで `docs/regen-comparison/` 形式の JSON を出力:
- 各 finding に対し RESOLVED / PARTIAL / UNCHANGED / NEW_ISSUE / NA_BY_DESIGN
- new_only_issues (旧監査になかった問題)
- summary.overall_improvement (high / medium / low / regression)

ゲート判定は集約スクリプトで自動実行 (`scripts/aggregate_regen_comparison.py`)。

---

## 4. 改修依存グラフと PR 構成

### 4.1 PR 一覧 (実装順序)

```
[並列 PR group 1: 独立改修]
  PR1: scraper dedup (§2.4)              — scrapers/{shugiin,sangiin}.py +20行
  PR2: video_url 修正 (§2.14)            — speaker_tagger.py +1行
  PR3: derive_role 拡張 (§2.9)           — scrapers/_role.py +30行
  PR4: schema 規約明文化 (§2.12)         — models.py +20行コメント
  PR5: 拡張閣僚リスト (§2.6)             — transcriber.py +30行 + cabinet.json

[Step 5↔5.5 機構]
  PR6: metadata enrichment (§2.2/2.3)    — pipeline.py + metadata_enricher.py +120行
       ※ PR1, PR3 マージ後

[transcript_corrector 強化]
  PR7: corrector 安全チェック緩和 (§2.5) — transcript_corrector.py +30行
  PR8: corrector 禁止事項強化 (§2.6/2.7) — transcript_corrector.py +20行

[structurer 全面書き換え — 大]
  PR9: utterance_indices schema (§2.1)   — structurer.py + prompts.py 全面
       ※ Appendix A 詳細
  PR10: content_missing 対策 (§2.10)     — structurer.py +80行
        ※ PR9 マージ後
  PR11: floor_speech 用 summary 経路 (§2.10) — structurer.py +50行
        ※ PR10 マージ後

[structurer 検証強化]
  PR12: summary post-validation (§2.11)  — structurer.py +80行
        ※ PR9, PR11 マージ後
  PR13: follow_up_ids 実装 (§2.14)       — structurer.py +50行
        ※ PR9 マージ後

[timestamp]
  PR14: leading_silence 閾値調整 (§2.13) — pipeline.py 1行 + 整合性チェック +20行

[検証ツール]
  PR15: schema validator (§2.12)         — scripts/validate_data_schema.py +50行
  PR16: 比較サブエージェント仕様統合     — docs/REGEN_VERIFICATION.md

[ISSUES から取り込んだ堅牢性改修]
  PR17: ffmpeg subprocess timeout (§2.15) — audio/extractor.py +10行
  PR18: speaker_tagger json.loads ラップ (§2.15) — speaker_tagger.py +10行
  PR19: スクレイパー DOM 検証 + 日付例外化 + find_committee 制限 (§2.16) — scrapers/*.py +45行 + tests/fixtures/scraper_html/ + tests/test_scrapers_smoke.py +50行
  PR20: 法案タグ精度検証 (§2.17) — tests/fixtures/laws_groundtruth.csv + scripts/eval_law_tagging.py +80行
```

### 4.2 依存グラフ

```
PR1 (dedup) ──┐
              ├──> PR6 (enrichment) ──┐
PR3 (role) ───┘                       │
                                      ├──> F1 検証 → F2 → F3 → F4
PR9 (utterance schema) ───────────────┤
              ├──> PR10 (content_missing) ──┐
              ├──> PR12 (summary validate)   │
              └──> PR13 (follow_up)          │
                                             │
PR5 (cabinet list) ──> PR7 (corrector loop)  │
PR8 (corrector facts) ───────────────────────┘

PR2, PR4, PR11, PR14, PR15, PR16, PR17-20: 独立、いつでもマージ可
PR20 (法案タグ精度) は F2 ゲート前にマージ要 (検証ゲート §3.2 #7)
```

### 4.3 想定実装期間

- PR1-5: 並列実装 1-2日
- PR6: 単独実装 2-3日 (新規ファイル + テスト)
- PR7-8: 1日
- PR9: 4-5日 (大規模、§Appendix A)
- PR10-13: 並列 2-3日
- PR14-16: 1日
- PR17-19: 並列 1-2日 (ISSUES 取り込み)
- PR20: 1-2日 (groundtruth キュレーション含む)
- 統合検証 F0-F4: 5-7日 (修正の手戻り含む)

合計: **4-5週間**。並列開発と修正手戻りで前後する。ISSUES 取り込み分 (PR17-20) を含めた更新。

---

## 5. 削除→検証→再生成 運用フロー

```
[Day 1-3] PR1-5 実装・マージ
[Day 4-7] PR6 実装・マージ → F0/F1 試走
   F1 結果でゲート判定。問題あれば PR1-6 を改修してリトライ
[Day 8-14] PR7-13 実装・マージ
   インクリメンタルに F1 を再走らせ、各 PR の効果を確認
[Day 15] PR14-16 マージ
[Day 16-17] F2 (12セッション) 実行・検証
[Day 18] F3 (30セッション) 実行・検証
[Day 19] F4 (全156セッション) 全削除 → 全件再生成
[Day 20] サイトビルド・Pagefind 再インデックス・公開
```

### 5.1 全削除手順 (F4 直前)

```bash
cd /Users/michitomo/git/kokkaidb
git tag pre-f4-snapshot
rm -rf data/shugiin data/sangiin
rm -rf data/search-index
rm -f site/public/api/search-index.json
rm -f kokkai-transcriber/state.db
git add -A && git commit -m "chore: full reset before F4 regeneration"
```

### 5.2 全件再生成 (F4)

```bash
cd kokkai-transcriber
source .venv/bin/activate
python -m src.batch --chamber shugiin --since 2026-02-01 --workers 4 --no-push
python -m src.batch --chamber sangiin --since 2026-04-01 --workers 4 --no-push

# 完了後、コミット → push
cd ..
git add data/
git commit -m "data: full regeneration after pipeline rewrite"
git push origin main
```

### 5.3 失敗時のロールバック

各フェーズで重大な退行を検出した場合:
- F4 失敗時: `git reset --hard pre-f4-snapshot`
- F1-F3 失敗時: 該当 PR を revert、原因調査、追加 PR で対処、該当フェーズから再走

---

## 6. 設計判断ログ

### Q: なぜ post-processing で既存データを修正する案を採用しなかったか

post-processing 案の最大の利点は「LLM 再呼び出し不要で既存データを救える」ことだった。しかし**全データ再生成を品質改善目的で行う前提**であり、その利点が消滅する。

再生成前提なら、LLM への入力トークン削減・20000文字制限の自然解消・LLM 失敗モード低減・コード単純化など、すべての観点で utterance ベーススキーマが優位。

### Q: なぜ LLM に utterance_indices だけ返させず anchor も持たせるか

99% のペアで anchor は不要 (`null`)。ただし代表質問・所信表明 (1%、208件観測) は1人の答弁者が長大な utterance で複数のテーマを連続で話すケースがあり、これを単純に utterance 単位で扱うと「同じ full_text を持つ複数ペア」が生まれてしまう。anchor 方式で LLM に「このペアは utterance のどこから始まるか」を sentence 番号で明示させ、コードが境界を計算することで、共有 utterance も穴なく分割される。

### Q: なぜ summary プロンプトは変更しないか

現状の `prompts.py` で `summary` は「実質的な問いかけ内容のみ (挨拶・背景不要)」と指示済みで、これはユーザー要件と一致している。`full_text` の方針だけが要件と逆向きだったので、`full_text` の組み立てだけを変える。ただし §2.11 で post-validation を追加。

### Q: なぜ Step 4.5+ 再実行ではなく完全再生成を選ぶか

Step 4.5+ 再実行検証 (4セッション、47 findings) で resolved は 19% (9/47) のみ、UNCHANGED が 60%、リグレッションも 2セッション発生した。主因は:
- `metadata.speakers` が scraper レベルで貧弱なまま下流に流れる構造的限界
- 旧 raw_transcript.json の Whisper V1 prompt 由来のループが残存
- transcript_corrector の早期 return (`if corrected: return`) により再補正が発生しない

完全再生成 (Step 2-6 全実行) によって V2 prompt とすべての改修を全データに適用する。コスト ($15-30) は許容範囲、wall-clock も並列で数時間。

### Q: A1 enrichment の同名異人問題はどう扱うか

`metadata_enricher.py` で speaker_tagger 出力から答弁者を補完する際、既存 speakers と name 一致するエントリは **追加せず既存をそのまま使う** (上書きしない)。affiliation が空の既存エントリには enrichment 結果の affiliation を流し込む (片方向 merge)。完全な同名異人 (実在する複数の鈴木大臣など) は本刷新では対処せず、将来課題とする。

### Q: 拡張閣僚リストの維持運用は

第221回国会の閣僚は16名。内閣改造があれば更新が必要。`src/cabinet.json` または `prompts.py` 内のリストとして管理し、毎国会 (約年1回) の手動更新を CLAUDE.md に明記する。今後 API 自動取得が望ましいが本刷新では手動。

### Q: follow_up_ids の判定基準

同一質疑者の連続発言は通常 1 質疑ブロックに含まれるが、答弁を挟んだ「再質問」「再質疑」は別ペアとなる。同一 segment 内で同一質疑者の qa_pairs が時系列順で 2件以上ある場合、後者の `follow_up_ids` に前者の `id` を入れる。複数答弁者にまたがる追及は本刷新では対象外 (将来課題)。

### Q: LLM モデルの使い分け方針

各ステップで使うモデルは **「Gemma で足りないとわかった箇所だけ Gemini Flash に上げる」** が原則。

| ステップ | モデル | 理由 |
|---|---|---|
| Step 4.5 corrector | `google/gemma-4-31b-it` | 入力が 2-3k tokens 程度の校正タスク。Gemma で品質上の問題なし |
| Step 5 speaker_tagger | `google/gemma-4-31b-it` | JSON splits の出力は小さく、Gemma で十分 |
| Step 6 **QA gen** | `google/gemini-3-flash-preview` | `split_anchor_sentence_idx` の正確な指定が重要で Gemma だと1ペアズレが頻発 (F2 再々々走で確認)。Flash に切り替え |
| Step 6 summary/topics/commitments | `google/gemma-4-31b-it` | 自由記述生成は Gemma で品質上の問題なし |
| Step 6 metrics | `google/gemma-4-31b-it` | 構造化スコアリングは Gemma で十分 |

**判定基準**: F2 以降の検証で特定ステップの `schema_inconsistency` や `content_missing` が `likely_systemic` かつ改善されない場合に、そのステップを `google/gemini-3-flash-preview` へ切り替えることを検討する。Flash は Gemma 比 1.5〜2.3倍のコストなので、品質問題が確認されてから切り替える。

実装箇所: `src/structurer.py:QA_MODEL` / `STRUCTURER_MODEL` / `_METRICS_MODEL`、`src/transcript_corrector.py:CORRECTOR_MODEL`、`src/speaker_tagger.py` (import `LLM_MODEL` from `api_client`)。

---

## 7. 未解決の論点 (実装着手時に再検討)

- [ ] サブ番号付き utterance (`(s120)` 形式) を LLM が安定してパース・参照できるか、実プロンプトで検証必要
- [ ] 単一答弁が複数 utterance に分かれるケース (chair が割り込んで答弁者が再開、など) の扱い
- [ ] 旧 `sentence_indices` 形式のテストコード・スナップショットの破棄 vs 新規書き起こし
- [ ] `score_qa_pairs_metrics` (V4) が `full_text` を直接読むため、`full_text` が長くなることでスコア分布が変動する可能性。閾値再キャリブレーションの要否
- [ ] HLS audio 分割の境界精度向上 (speaker_misattribution の物理限界、本刷新では対象外)
- [ ] 同名異人の完全な解決 (将来課題)
- [ ] 国会会議録 API (`kokkai.ndl.go.jp`) との突合による metadata 補強 (将来課題)

---

## Appendix A: utterance_indices schema 詳細 (§2.1 実装仕様)

### A.1 設計原則

1. **utterance を質疑応答の最小単位とする**。utterance はもともと話者タグ付け済みで、1人の話者が連続して話した塊なので、Q&Aペアの自然な単位として整合する。
2. **`full_text` は LLM が組み立てない**。コードが `seg.utterances[i].text` を連結するだけ。LLM の判断ミスで途中欠落が原理的に起きない構造にする。
3. **`summary` は LLM が独立生成** (現状通り、プロンプトで「挨拶・背景不要」と指示済み)。
4. **複数ペアが共有する utterance (代表質問・所信表明、全体の1%) には sentence-level anchor で境界を明示**させる。

### A.2 新スキーマ

LLM の Q&A 抽出レスポンス形式:

```json
{
  "pairs": [
    {
      "topic": "年収の壁支援強化パッケージの執行状況と評価",
      "question": {
        "utterance_indices": [12],
        "split_anchor_sentence_idx": null,
        "summary": "- 年収の壁支援強化パッケージの執行状況の確認\n- 106万の壁対策の評価",
        "intent": "information_request"
      },
      "answer": {
        "utterance_indices": [14],
        "split_anchor_sentence_idx": null,
        "summary": "- キャリアアップ助成金の支給額は令和6年度31.8億円\n- 令和7年7月に拡充し、労働者1人当たり最大75万円を助成\n- 周知広報に一層取り組む方針"
      }
    }
  ]
}
```

フィールド説明:

| フィールド | 必須 | 内容 |
|--|--|--|
| `utterance_indices` | ✓ | このペアの Q または A を構成する utterance 番号の配列。通常1個、まれに連続する複数。 |
| `split_anchor_sentence_idx` | △ | 同じ utterance を**他のペアと共有する**場合のみ設定。このペアが utterance 内のどの文から始まるかをグローバル sentence index で指定。99%のペアでは `null`。 |
| `summary` | ✓ | 「- 」箇条書き2〜4項目。挨拶・背景は不要。 |
| `intent` | ✓ (Q側のみ) | fact_check / policy_proposal / accountability / information_request / other |

### A.3 LLM への入力プロンプト形式

utterance単位で番号付け、長文 utterance のみ内部に sentence サブ番号を併記:

```
セグメント発言者: 浜地雅一（中道改革連合・無所属）

[U10] [質疑者] 浜地雅一:
  なぜ周知が必要かというと、この年収の壁支援強化パッケージが...
  ...御答弁をいただきたいと思います。

[U11] [委員長] 大串正樹:
  田中雇用環境均等局長。

[U12] [政府参考人] 田中雇用環境均等局長:
  お答えいたします。年収の壁支援強化パッケージの先ほど言及のありました...
  ...周知広報に一層取り組んでまいりたいと考えております。

[U13] [質疑者] 浜地雅一:
  ありがとうございます。私も手元にデータがあるんですけど...
```

代表質問・所信表明のような長文 utterance のみ:

```
[U5] [答弁者] 高市早苗:
  (s120) 内閣総理大臣高市早苗君。
  (s121) 先般の総選挙の結果を受け、首班指名をいただき...
  (s122) 重要な政策転換を何としてもやり抜いていけ...
  ...
  (s230) 量子、航空、宇宙、コンテンツ、創薬などの17の戦略分野については...
```

LLM は `[{utterance_indices: [5], split_anchor_sentence_idx: 120}, {utterance_indices: [5], split_anchor_sentence_idx: 145}, ...]` のように同じ utterance を複数ペアで共有しつつ、各ペアの開始位置を anchor で示す。

### A.4 コード側の `full_text` 組み立てロジック

```python
def assemble_full_text(seg, pair_group):
    """1つの utterance を共有する複数ペアの full_text を構築。
    pair_group: 同じ utterance を共有するペア群 (ソート済み by anchor)
    """
    if len(pair_group) == 1:
        # 単独ペア: utterance全文をそのまま使う
        pair = pair_group[0]
        utts = [seg.utterances[i] for i in pair.utterance_indices]
        return "\n".join(u.text for u in utts)
    else:
        # 複数ペア共有: anchor で境界分割
        u_idx = pair_group[0].utterance_indices[0]
        utt = seg.utterances[u_idx]
        sentences = split_sentences(utt.text)
        anchors = [p.split_anchor_sentence_idx for p in pair_group]
        boundaries = sorted(set(anchors + [len(sentences)]))
        for i, pair in enumerate(sorted(pair_group, key=lambda p: p.split_anchor_sentence_idx or 0)):
            start = pair.split_anchor_sentence_idx or 0
            end = boundaries[boundaries.index(start) + 1]
            pair.full_text = "".join(sentences[start:end])
```

これにより:
- 単独ペア (99%): 挨拶・前置き含む utterance 全文が `full_text` に入る
- 共有ペア (1%): 各ペアは utterance 内の連続スライスを担当し、全 sentence は必ずどこかのペアに属する (穴ができない)

### A.5 旧 `sentence_indices` 方式の廃止

現状の `_split_sentences`, `_build_sentence_map`, `_assemble_full_text_from_sentences`, `_build_sentence_to_utterance_map` は新方式では不要 (または大幅縮小)。`_split_segment_into_blocks` (委員長指名による質疑ブロック分割) は引き継ぎ、新方式でも使用する。

---

## Appendix B: 監査・検証データソース

| ファイル | 内容 |
|---|---|
| `docs/QUALITY_AUDIT_FORMAT.md` | 監査フォーマット仕様 |
| `docs/audit-results/*.json` | 90セッション監査結果 (各 finding が JSON で記録) |
| `docs/PIPELINE_FIX_STATUS.md` | データ生成時 → 現コードの差分分析 (57コミット) |
| `docs/regen-comparison/*.json` | Step 4.5+ 再実行検証結果 (4セッション、47 findings) |
| `docs/ISSUES.md` | 既知問題ログ |
| `docs/data-review/06-qa-extraction.md` | qa_pairs 既知問題詳細 |

---

## 1.5 観測された transcript_truncation の典型例

セッション `data/shugiin/2026/04/24/56209_厚生労働委員会` の qa_022 (浜地雅一質問・田中雇用環境均等局長答弁):

**正規の議事録での全文** (抜粋):
> お答えいたします。年収の壁・支援強化パッケージの…キャリアアップ助成金です…令和七年七月にこれを拡充いたしまして、労働者一人当たり最大七十五万円を助成…周知広報に一層取り組んでまいりたいと考えております

**現状の `answer.full_text`**:
> 社会保険適用時処遇改善コースということで実施をしておりましたが…この助成金につきましては、より多くの企業にご活用いただきたいというふうに考えております。

→ 冒頭の「お答えいたします。年収の壁支援強化パッケージの…キャリアアップ助成金です。」と、末尾の「令和3年度末で終了…令和7年7月に拡充…75万円を助成…周知広報に一層取り組んでまいりたい」が完全に欠落。

`utterances.json` には完全な発言が保存されている (Whisper・話者タグ付けは正常)。問題は `structurer.py` の Q&A ペア組み立て段階で発生している。これが §2.1 の出発点。
