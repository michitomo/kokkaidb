# パイプライン改善状況: 監査結果 vs 現コード

## 比較対象

- **データ生成期間**: 2026-04-16 〜 2026-05-04
- **パイプライン現在**: 57コミット後 (HEAD: d811d5b)
- **主要変更点**:
  - DeepSeek V3.2 → Gemma 4-31B-it 全面移行（Step 4.5/5/6、コミット `df19709`）
  - Whisper プロンプト V2 実装（ループ誘発源を3系統除去、コミット `6e619a7`）
  - transcript_corrector 新規追加（Step 4.5 LLM後処理、コミット `659fab9`）
  - Step 5.5 normalizer 追加（speaker/role 正規化、コミット `a7a8fb9`）
  - speaker_tagger 5イテレーション改善・anti-fragmentation ルール（コミット `1d194f9`）
  - structurer: 出力切断対策、QA密度チェック＋リトライ、委員長指名ブロック分割（コミット `e57c687`）

---

## カテゴリ別判定

### 1. whisper_misrecognition — PARTIAL

**監査での観察**: 269件 (96% / 195 systemic)
- 「木原稔大臣」→「木川田大臣」（sangiin-8966 F002: seg2〜seg8 の10箇所以上）
- 「大槌町」→「大津地町/大津市町/土町」（複数バリアント、sangiin-8973 F003）
- 「高市」→「高井」（shugiin-56075 F008: ws[4]「高井総理」×2）
- 「れいわ新選組」→「令和新選組」（複数セッション）
- 「参政党」→「賛成党/さんせい党」（複数セッション）

**関連コミット/コード**:
- `6e619a7` `transcriber.py:59-81` — Whisper プロンプト V2。ループ誘発源（石井副議長・法律名・出席議員リスト）を除去し、動的サフィックスを `{委員会}。{speaker名}（{所属}）：` に変更。閣僚7名のみ残す
- `659fab9` `transcript_corrector.py:42-128` — Step 4.5 LLM 後処理 (Gemma-4-31B)。発言者リストを「確定情報」として固有名詞修正ルールを明示。「賛成党」→「参政党」など同音誤変換の例示を含む

**現状**:
- **直ったこと**: transcript_corrector が発言者リスト (metadata.speakers) をコンテキストとして渡すため、speakers に登録されている人物の名前誤認識は LLM 後処理で修正される（sangiin-8966 F002 でも「corrected text では木原に修正されている」と監査が認定）
- **残っていること**: (a) metadata.speakers にない政府参考人・局長の氏名誤認識は corrector の文脈情報がなく修正困難。(b) whisper_segments 層には原文が残る（修正は text フィールドのみ）。(c) 聴音区別が困難な人名（「木原」vs「木川田」、「大槌」vs「大津地」）は Whisper モデル自体の限界でコード対処不能。(d) プロンプトには木原稔・林芳正・平口洋・金子恭之など主要閣僚の大半が含まれていない

**判定根拠**: `_WHISPER_PROMPT_BASE` に記載される閣僚は7名（高市・木原・茂木・片山・上野・赤澤・小泉）のみ。第221回国会の閣僚は16名であり、残り9名分の固有名詞バイアスは未解消。transcript_corrector の補正効果が実測で確認されているが、speakers 未登録の政府参考人は補正対象外。

---

### 2. schema_empty_field — NOT FIXED（部分対処のみ）

**監査での観察**: 186件 (100% / 183 systemic)
- `answer.role` が 99% 空文字列（例: sangiin-8978「answer.role が 107/139 ペアで空文字列（木原稔のみ入力済）」）
- `metadata.committee_id` が全セッションで `null`
- `metadata.session_number` が全セッションで `null`
- `metadata.duration` は衆議院で取得、参議院では空のケースあり

**関連コミット/コード**:
- `models.py:160-161` — `committee_id: int | None = None`、`session_number: int | None = None` はデフォルト `None`。スクレイパーは一切値を設定しない
- `structurer.py:152-196` — `_resolve_answerer_from_sentences` は `speakers_lookup` に登録された話者の affiliation を `a_role` として返す。登録外なら `""` を返す（行 172: `candidate_aff = info.affiliation if info else ""`）
- `scrapers/shugiin.py:170-214` および `scrapers/sangiin.py:191-232` — `_extract_speakers` は TV サイトのタイムスタンプリンク（`time=` / `#NNNN` アンカー）から発言者を抽出する。衆参ともに**質疑者のみ**が TV 発言者リストに載っており、答弁する大臣・政府参考人は含まれない

**現状**:
- `answer.role` 空問題の根本原因（政府答弁者が `metadata.speakers` に未登録）は**構造的に未解決**。スクレイパーは TV のタイムスタンプリンクに存在する話者のみを取得する設計のため、委員会に呼ばれた大臣・局長は取得できない
- `committee_id` / `session_number` はスクレイパー側に取得ロジックが存在しない
- `duration` は衆議院では `_extract_duration()` で取得済み（`shugiin.py:163-167`）

**判定根拠**: `scrapers/shugiin.py:181-214` の `_extract_speakers` は `<a href="...time=NNN.N">` のアンカーのみを対象とする。衆議院 TV の発言者リストは質疑者の持ち時間を示すもので、答弁者は含まれない。`session_number`/`committee_id` に設定するコードがどこにも存在しない（`grep` で未ヒット）。

---

### 3. schema_inconsistency — PARTIAL

**監査での観察**: 137件 (90% / 127 systemic)
- 同一人物が「斉藤支援局長」と「斎藤支援局長」の2漢字表記に分散（sangiin-8966 F003）
- 「中村局長」が「中村生育局長/中村政役/中村局長」の3表記（sangiin-8966 F004）
- `null` ↔ 空文字混在（旧データのみ）
- (N) 連番不整合（発言者番号）

**関連コミット/コード**:
- `a7a8fb9` `normalizer.py:24-47` — Step 5.5 で `utterances.json` 全発言を `metadata.speakers` と fuzzy-match し、`speaker` フィールドを正規表記に統一する。`build_lookup`→`find_by_name`（2文字姓→1文字姓の優先順でマッチ）
- `speaker_lookup.py:28-78` — `find_by_name` は完全一致→2文字姓→1文字姓→3文字姓の順でマッチ。`allow_single_char=False`（normalizer）では 1文字姓マッチを無効化
- `structurer.py:103-132` — `_fuzzy_lookup` → `find_by_name`（`allow_single_char=True`）で QA ペア生成時も speaker を解決

**現状**:
- **直ったこと**: `utterances.json` 内の表記ゆれは Step 5.5 で `metadata.speakers` の正規名に統一される。ただし **metadata.speakers に登録されていない**政府参考人・局長は `unmatched=True` になり正規化されない
- **残っていること**: 「斉藤/斎藤」など同音異字の問題は metadata.speakers 側の取得元（TV サイト）の表記に依存。TV サイトが「斎藤」と表記するなら全セグメントで「斎藤」に統一されるが、政府参考人が speakers に未登録なら依然として不統一が発生する。`null` vs 空文字の混在はモデル定義（Pydantic Field の `default`）で制御されており、`Optional` 型には None が、`str` 型には空文字がデフォルトとなる

**判定根拠**: `speaker_lookup.py:19-25` の `build_lookup` は `speakers: list[SpeakerInfo]` を受け取り辞書を作る。スクレイパーが返す `metadata.speakers` に政府参考人が含まれなければ normalizer も QA structurer も正規化できない。

---

### 4. speaker_misattribution — PARTIAL

**監査での観察**: 110件 (73% / 90 systemic)
- HLS 境界で次話者の発言が前話者セグメントに混入（sangiin-8966 F001: qa_033 の質問者が「中村局長」に誤帰属）
- 本会議での発言順逆転（shugiin-56074 F004: segment_index=5 が石井啓一のはずなのに木原稔に帰属）

**関連コミット/コード**:
- `1d194f9` `speaker_tagger.py:26-71` — SYSTEM_PROMPT を5イテレーション改善。R1「指名文」規則（委員長呼名の直後から新話者）、R2「Whisper ラベル行」規則、R3「答弁冒頭定型句」規則を明示。anti-fragmentation ルール（10超の split は統合）
- `speaker_tagger.py:40-41` — R1 の例示: `(0)坂本哲志(委員長), (1)次に西村智奈美君。(2)中道改革連合の西村智奈美です。 → start=0: 坂本哲志(委員長), start=2: 西村智奈美(質疑者)` と明示
- `structurer.py:199-298` — `_split_segment_into_blocks`: 委員長の指名発言を境界として1セグメントを複数の「質疑ブロック」に分割し、ブロック単位で QA 生成することで境界誤帰属を軽減
- `pipeline.py:175-193` — `detect_leading_silence` + offset 補正（10秒超の先頭無音を検出し、全話者の `start_seconds` を補正）

**現状**:
- **直ったこと**: speaker_tagger のプロンプト改善で「指名文の直後から新話者」というルールが明確化された。`_split_segment_into_blocks` によって1セグメント内の複数質疑者が正しく分割される
- **残っていること**: 境界付近の誤帰属（前セグメント末尾の数秒が次セグメントの Whisper に混入）はプロンプトルールでは完全には解消できない。HLS 分割の精度はタイムスタンプ精度に依存しており、leading silence 補正（offset > 30s の場合のみ補正）は小さなズレには対応しない

**判定根拠**: `speaker_tagger.py:61-63` で「通常 2-6 splits/セグメント、10超は統合」という上限ルールが追加された。しかしセグメント間の物理的な音声境界問題（ffmpeg `-ss` / `-to` の精度）はコード対処の範囲外。

---

### 5. content_missing — PARTIAL

**監査での観察**: 85件 (70% / 56 systemic)
- segment_index=10 の複数質疑者（奥田・藤井・小西・松沢・原田・佐々木・宮出）が qa_pairs に未収録（sangiin-8973 F002）
- 平口大臣演説 3,014字が qa_pairs に未収録（sgiin-56069 F001）

**関連コミット/コード**:
- `structurer.py:321-326` — `_MIN_QA_DENSITY = 0.5` (1000文字あたり 0.5ペア)。2000文字以上のセグメントで密度が低い場合は `retry_hint` を付けて1回リトライ（コミット `e57c687`）
- `structurer.py:300-318` — `_is_qa_segment`: `役割=質疑者` がない場合でも `答弁者 + 委員長以外の役割` があれば QA 対象と判定するフォールバック
- `structurer.py:211-298` — `_split_segment_into_blocks`: 委員長の指名で複数質疑者が1セグメントに混在する場合を分割
- `prompts.py:9-24` — `QA_SEGMENT_SYSTEM_PROMPT`: 「roleラベルは誤分類あり、発言内容でQ&Aを判断すること」と明示。`趣旨説明・所信表明（一方的演説）はペア抽出不可`

**現状**:
- **直ったこと**: QA 密度リトライにより単純な見落としは改善。`_split_segment_into_blocks` で複数質疑者セグメントの処理が構造化された
- **残っていること**: `session_kind = "floor_speech"` と判定されたセグメントは `_run_step6` で QA 抽出をスキップ（`pipeline.py:325-328`）。趣旨説明・所信表明の一方的演説は QA ペアなしが正しい挙動だが、一部の本会議セッションで発言内容が演説か質疑か境界が曖昧。また 20,000 文字を超えるセグメントは先頭で切り捨て（`structurer.py:413-422`）るため、長尺セグメントの後半が欠落するリスクが残る

**判定根拠**: `structurer.py:412-422` に `_INPUT_CHAR_LIMIT = 20000` のハードカット。コメントに「TODO: 将来的には _split_segment_into_blocks を利用して sub-block ごとに QA 生成してマージ」と記載されており、未実装の改善点が明示されている。

---

### 6. role_label_error — PARTIAL

**監査での観察**: 74件 (63% / 67 systemic)
- 「石田真敏」（臨時委員長）が全発言 `role=質疑者`（shugiin-56078 F001）
- 「森英介」（議長）の開会宣言が `role=質疑者`（shugiin-56075 F002）
- 「事務総長→質疑者」「副大臣→質疑者」などの誤分類

**関連コミット/コード**:
- `scrapers/_role.py:36-71` — `derive_role(affiliation)`: affiliation から `委員長/議長` → `答弁者` → `政府参考人` → `質疑者` を決定論的に派生。`委員長`, `副議長`, `議長` を含む場合は `委員長` ロールを付与
- `normalizer.py:50-63` — Step 5.5 の `coerce_role`: `matched.role`（scraper 派生済み）を優先、次に `raw が SpeakerRole 値域内`、最後に `derive_role(raw)` で補正
- `speaker_tagger.py:49-56` — ロール定義表（`委員長/質疑者/答弁者/政府参考人/参考人/その他`）をプロンプトに明示
- `speaker_tagger.py:28-36` — 「speaker には必ず人物の実名を使う」「委員長・議長の split でも実名を使う」と明示

**現状**:
- **直ったこと**: `derive_role` による決定論的ロール付与（Step 2 でメタデータに書き込み）と Step 5.5 の coerce_role により、scraper で取得できた発言者については metadata.speakers の role が normalizer により utterances に反映される
- **残っていること**: 「臨時委員長」（affiliation が通常の委員名）は affiliation から `質疑者` と判定され `委員長` に補正されない（`derive_role` が `affiliation.endswith("委員長")` でしか委員長を判定しないため）。発言内容から「委員長職務を行います」を検知する手段がない。事務総長なども専用サフィックスなしでは分類できない

**判定根拠**: `scrapers/_role.py:45-48` の判定条件は `affiliation.endswith(("委員長", "議長", "副議長"))` または集合一致。臨時委員長は通常 `自由民主党` などの政党名が affiliation に入るため `質疑者` に分類される。このケースは依然として誤分類が発生する。

---

### 7. metadata_missing_speaker — NOT FIXED

**監査での観察**: 71件 (73% / 68 systemic)
- 答弁者 12名全員が metadata.speakers に未登録（sangiin-8968 F002: 林芳正・高市早苗・堀内照男など）
- 主要答弁者 3名（高市PM・赤澤・上野）が speakers に未登録（sangiin-8969 F001）

**関連コミット/コード**:
- `scrapers/shugiin.py:181-214` — `_extract_speakers`: `soup.find_all("a", href=re.compile(r"time=[\d.]+"))` で TV 発言者リストのリンク付き話者のみ取得
- `scrapers/sangiin.py:191-232` — `_extract_speakers`: `soup.find_all("a", class_="play2")` で参議院 TV の `play2` クラスリンクのみ取得
- 衆参ともに TV の「発言者リスト」は質疑者（議員側）の持ち時間を示すものであり、答弁者（大臣・政府参考人）のタイムスタンプリンクは TV サイトに存在しない

**現状**:
- **未解決**: 根本原因（TV サイトが答弁者のタイムスタンプを公開していない）はコード変更後も変わっておらず、metadata.speakers から答弁者が欠落する構造は継続している。これは `answer.role` 空問題の直接的原因でもある
- 答弁者を speakers に追加するには、transcript_corrector や speaker_tagger の出力から事後的に抽出するか、外部の国会議員・政府参考人データベースとの突合が必要（未実装）

**判定根拠**: `scrapers/sangiin.py:195-199` の `anchors = soup.find_all("a", class_="play2")` は参議院 TV の HTML 仕様に依存しており、大臣・局長のエントリは `play2` クラスに存在しない。同様に衆議院も `time=` パラメータ付きリンクは質疑者のみ。この制約を克服するコードは現時点で存在しない。

---

### 8. summary_qa_divergence — PARTIAL

**監査での観察**: 70件 (67% / 41 systemic)
- `summary.key_commitments[0]` が `qa_001` を参照するが `qa_001` の答弁者と食い違い（shugiin-56074 F003）
- `summary.session_summary` が `qa_pairs` に存在しない事実を言及

**関連コミット/コード**:
- `structurer.py:793-816` — `generate_key_commitments`: `valid_qa_ids = {p.id for p in qa_pairs.pairs}` で有効 ID を列挙し、LLM が返した `qa_id` が不正な場合は `dropped += 1` して破棄
- `structurer.py:767-784` — `generate_topics_and_key_topics`: `key_topics not in valid_topic_names` なら除去してログ
- `prompts.py:82-90` — `COMMITMENTS_SYSTEM_PROMPT`: 「speakerは入力『回答者:』の実名をそのまま使用」「qa_idは入力のIDをそのまま使用」と明示。V5 では F1 40%→100% を達成（コミット `83b3f1c`）
- `prompts.py:31-35` — `SESSION_SUMMARY_SYSTEM_PROMPT`: 「複数テーマがある場合は全テーマに言及すること」「冒頭の一文に院名・委員会名を必ず明記」と強化

**現状**:
- **直ったこと**: `qa_id` バリデーション（不正 ID は drop）により、存在しない QA ペアへの参照が防止された。commitments プロンプトが V5 に改善されベンチマーク F1 = 100%
- **残っていること**: `session_summary` テキストが qa_pairs から逸脱した事実を含む問題は LLM の生成的挙動に依存しており、コード側での完全制御が困難。また `qa_pairs` が空（`floor_speech` セッション等）の場合の summary 生成品質は低い

**判定根拠**: `structurer.py:794-805` で `qa_id` バリデーションが実装済み。ただし `speaker` フィールドの一致確認（「回答者」と `key_commitments.speaker` が一致するか）はコード検証なしで LLM に委ねており、誤記リスクが残る。

---

### 9. whisper_hallucination_loop — PARTIAL

**監査での観察**: 62件 (48% / 52 systemic)
- 「議長＊小寺君。」6,904回繰り返し（特定セッション）
- 「ご視聴ありがとうございました。」がセグメント全体を占有（sangiin-8969 F004）
- 「最高裁判所で性同一性障害特例法に、国会議員」の文脈外テキスト混入

**関連コミット/コード**:
- `6e619a7` `transcriber.py:26-57` — Whisper プロンプト V2。ループ誘発パターンを3系統除去:
  - 石井啓一副議長（プロンプト末尾に固定配置→本会議でループ最多）
  - 法律名全体（社会福祉法が9件のループを誘発）
  - 出席議員リスト（42件のループを誘発、最多）
- `transcript_corrector.py:56-63` — Step 4.5 で「話者名の2回以上の繰り返し」「文脈に合わない固有名詞の単独出現」「議長＊○○君 のような特殊記号付き挿入句」を除去するよう指示
- `transcript_corrector.py:319-336` — 安全チェック: `……` を含む場合は元テキストを採用、80% 未満に縮んだ場合も棄却

**現状**:
- **直ったこと**: プロンプト V2 でループの主要誘発源 3 系統を除去。transcript_corrector がループ繰り返しを後処理で除去する機能を持つ。発生率は大幅に低下する見込み（V2 の効果はコミットメッセージで「140セッション/62,647セグメント」の分析から根拠付けられている）
- **残っていること**: Whisper の acoustic model の限界（無音区間や低音質区間）によるハルシネーションは完全に排除できない。「ご視聴ありがとうございました。」は Whisper の学習データ起源でプロンプトの影響外。corrector の安全チェックが棄却基準（80%未満）を満たさない場合はループが残存する

**判定根拠**: `transcriber.py:39-43` のコメントに「3. 動的サフィックスを出席議員リストから変更 → 最多ループ誘発源（42件）を解消」と明記。corrector の除去ルールは `transcript_corrector.py:56-63` に明示されているが、6,904回繰り返しのような極端なケースでは corrector が 80% 縮小チェック（行 329-335）で棄却してしまい元の繰り返しテキストが保持される可能性がある。

---

### 10. fact_error — PARTIAL

**監査での観察**: 43件 (44% / 30 systemic)
- 「八潮市」→「八代市」（LLM 補正による地名書き換え）
- 「財政投融資」→「財政投入」
- 参議院セッションが「衆議院において」と summary に誤記（sangiin-8978 F001）
- LLM が括弧注釈を挿入（sangiin-8980 F013）

**関連コミット/コード**:
- `transcript_corrector.py:123-130` — 禁止事項: 「テキストの意味を変えない。要約・省略・追加をしない」「存在しない発言を捏造しない」「発言者リストに記載された名前の表記を勝手に変えない」
- `transcript_corrector.py:319-336` — 安全チェック2: 80% 未満に縮んだチャンクは棄却して元テキストを使用
- `prompts.py:31-35` — `SESSION_SUMMARY_SYSTEM_PROMPT` で「院名・委員会名は入力の『## セッション情報』の値をそのまま使う」と明示
- `pipeline.py:709-725` — `generate_session_summary` に `session_meta` パラメータで `chamber`/`committee` を渡し、`衆議院`/`参議院` を確定情報として LLM プロンプトに注入

**現状**:
- **直ったこと**: 「参議院セッションを衆議院と誤記」問題は `session_meta` の `chamber` を summary プロンプトに注入することで解消。禁止事項の明示により極端な書き換えは抑制された
- **残っていること**: LLM による微妙な事実改変（「八潮市→八代市」など）は禁止事項のプロンプトで一定抑制されるが完全に防止できない。「財政投融資→財政投入」のような専門用語の誤変換は Gemma モデルの語彙力に依存する。括弧注釈挿入も LLM の生成傾向によるもの

**判定根拠**: `structurer.py:709-725` で `chamber_ja = ("衆議院" if chamber_raw == "shugiin" else "参議院" ...)` として `meta_prefix` に確定情報を付与してから LLM に渡す。「参議院→衆議院」誤記問題は構造的に解消。ただし corrector の 80% 縮小チェックは事実改変（縮まずに別の語に置換）を検出しない。

---

### 11. duplicate — NOT FIXED

**監査での観察**: 35件 (37% / 27 systemic)
- metadata.speakers に辰巳孝太郎が 3エントリ、長友・和田・高山が各 2エントリ（sangiin-8986 F003）

**関連コミット/コード**:
- `scrapers/sangiin.py:191-232` — `_extract_speakers` は `anchors = soup.find_all("a", class_="play2")` で全アンカーを取得し、重複チェックなしで `speakers.append(...)` する
- `scrapers/shugiin.py:181-214` — 同様に重複チェックなし
- `speaker_lookup.py:19-25` — `build_lookup` は「同名は最初の登場を残す」（行 22: `if s.name and s.name not in lookup`）ため、lookup レベルでは重複は吸収される。しかし **metadata.json 自体には重複エントリが残る**

**現状**:
- **未解決**: `metadata.speakers` に重複エントリが書き込まれる問題は scraper 側で解消されていない。`speaker_lookup.build_lookup` が重複を吸収するため、downstream の LLM 処理（speaker_tagger、structurer）では影響が出ないが、metadata.json を直接参照する UI や集計処理では同一人物が複数表示される

**判定根拠**: `scrapers/shugiin.py:203-211` と `scrapers/sangiin.py:218-229` の `speakers.append(...)` には重複フィルタが存在しない。scraper が同一発言者のタイムスタンプリンクを複数回見つけた場合（例: 複数回の持ち時間に対して個別リンク）、全てが追加される。

---

### 12. timestamp_inconsistency — PARTIAL

**監査での観察**: 27件 (30% / 26 systemic)
- `start_seconds=2050.3` と `start_time=12:14` が 90分以上乖離（sangiin-8978 F003: HLS ストリーム開始が 10:10 JST）
- `start_time` と `start_seconds` が異なる基準系（休憩後エントリー 20件、shugiin-56078 F001）

**関連コミット/コード**:
- `pipeline.py:175-193` — `detect_leading_silence` + オフセット補正: 先頭無音が 10秒超 かつ `offset > 30.0` の場合に全話者の `start_seconds` を補正し、補正後の値で `metadata.json` を上書き
- `audio/extractor.py:360-390` — `detect_leading_silence`: ffmpeg の `silencedetect` フィルタで先頭無音を検出（閾値 -60dB、最小継続時間 1秒）
- `audio/extractor.py:285-295` — `split_segments` の `_split_one`: `start = speaker.start_seconds`、`end = speakers[i+1].start_seconds`。補正後の `start_seconds` が使われる

**現状**:
- **直ったこと**: HLS 先頭無音（映像開始前のパディング）によるタイムスタンプズレは、`detect_leading_silence` の検出とオフセット補正で対処。`offset > 30.0` の条件（30秒超のズレ）が存在する場合は補正される
- **残っていること**: `start_time`（`HH:MM` 形式、TV が表示する開始時刻）と `start_seconds`（HLS 先頭からの秒数）は異なる基準系であり、完全な同期は HLS ストリームの開始時刻が既知でなければ実現できない。現状は `start_time` を TV サイトから取得（ページの時刻表示）、`start_seconds` を HLS の `time=` パラメータから取得しており、両者の基準が一致しない場合は乖離が残る。30秒未満のズレには補正が効かない

**判定根拠**: `pipeline.py:176` の条件 `if leading_silence > 10.0 and session_detail.speakers:` および `if offset > 30.0:` は大きなズレ（30秒超）のみを補正する。7-20分のズレは通常このケースに該当し補正されるはずだが、offset 計算の精度は `detect_leading_silence` の正確さに依存する。`start_time` vs `start_seconds` の基準系の不一致問題は根本的には未解決。

---

### 13. other — NOT FIXED

**監査での観察**: 32件 (31%)
- `follow_up_ids` が全ペアで空配列
- トピック未分類（全 qa_pairs が 1つのトピックに押し込まれる）
- 参議院 `video_url` が `www.` なしのホスト名

**関連コミット/コード**:
- `models.py:260` — `follow_up_ids: list[str] = Field(default_factory=list)` が定義されているが、`structurer.py` のどこにも `follow_up_ids` を設定するコードが存在しない
- `structurer.py:211-298` — `_split_segment_into_blocks` でブロック分割後に `block_order` でソートするが、ブロック間のフォローアップ関係を追跡するロジックはない
- `speaker_tagger.py:199-211` — `_build_video_url` で参議院の URL を `webtv.sangiin.go.jp`（www なし）で生成している。`CLAUDE.md` では「正規ホスト名は `www.webtv.sangiin.go.jp`」と明記されているが修正されていない

**現状**:
- `follow_up_ids` は設計上の placeholder であり実装は将来の課題
- 参議院 `video_url` の `www.` 欠落は `speaker_tagger.py:208` で未修正
- トピック過剰集約については `prompts.py:38-66` の TOPICS_SYSTEM_PROMPT でグルーピング目安の表と正反例を追加（コミット `1169146`）。ただし少件数のセッションでは依然として過剰集約が発生する可能性がある

**判定根拠**: `speaker_tagger.py:205-210` の `_build_video_url` で `sangiin` の場合に `https://webtv.sangiin.go.jp/...` を返す（`www.` なし）。`models.py:260` に `follow_up_ids` のフィールドはあるが、`structurer.py` 全体で `follow_up_ids` への代入が存在しない（`grep` で未ヒット）。

---

## 全体評価

| 状態 | カテゴリ数 | カテゴリ |
|------|-----------|---------|
| **PARTIAL** | 8 | whisper_misrecognition, schema_inconsistency, speaker_misattribution, content_missing, role_label_error, summary_qa_divergence, whisper_hallucination_loop, fact_error, timestamp_inconsistency |
| **NOT FIXED** | 4 | schema_empty_field(answer.role), metadata_missing_speaker, duplicate, other(follow_up_ids/video_url) |
| **FIXED** | 0 | — |
| **UNKNOWN** | 0 | — |

*注: timestamp_inconsistency はカテゴリ数の都合で PARTIAL に含め 8+1=9 件ですが、表は本来 8 件。*

実際の内訳:
- **PARTIAL**: 9カテゴリ (1〜3, 5〜6, 8〜10, 12)
- **NOT FIXED**: 4カテゴリ (7, 11, 13 に加え 2 の answer.role 部分)

### 再生成価値の評価

**結論: 大幅な品質改善が見込まれる。再生成を推奨する。**

改善が期待できる主要カテゴリ:

1. **whisper_hallucination_loop** (62件): Whisper V2 でループ誘発源 3系統を除去。最多誘発源（出席議員リスト・石井副議長・法律名）が排除されており、監査時データより大幅に発生率低下が見込まれる
2. **whisper_misrecognition** (269件): transcript_corrector（Step 4.5）が発言者リストを参照した固有名詞補正を全セッションに適用。scraper 取得済みの発言者名の誤認識は大半が修正される
3. **speaker_misattribution** (110件): speaker_tagger の5イテレーション改善と `_split_segment_into_blocks` の追加で、委員長指名境界での誤帰属と複数質疑者混在セグメントへの対処が強化された
4. **role_label_error** (74件): Step 5.5 normalizer が metadata.speakers の role（derive_role で決定論的に付与）を utterances 全体に反映。speaker 登録済みの発言者については role が確実に正規化される
5. **summary_qa_divergence** (70件): commitments プロンプト V5（F1 100%）と `qa_id` バリデーションにより、存在しない qa_id への参照が防止された

---

## 残るリスク（再生成後も継続する問題）

1. **metadata.speakers への政府答弁者未登録** (カテゴリ 2, 7 の根本原因): TV サイトが答弁者のタイムスタンプリンクを持たない構造的制約。`answer.role` の空文字問題と metadata の不完全さは再生成後も継続する

2. **scraper 取得外の人物の固有名詞誤認識**: transcript_corrector は `metadata.speakers` にない政府参考人・局長については補正コンテキストを持たず、「木川田大臣」→「木原大臣」の修正は行われない

3. **metadata.speakers の重複エントリ**: 同一人物が複数の持ち時間スロットを持つ場合、scraper が重複エントリを追加する問題が未解決。re-process 後の metadata.json にも重複が残る

4. **HLS セグメント境界での話者混入**: 前セグメント末尾の発言が次セグメントの Whisper テキストに混入する問題。物理的な音声境界問題であり、プロンプト改善だけでは完全解消できない

5. **follow_up_ids の永続的欠落**: 設計上実装されておらず、再生成後も全ペアで空配列となる

6. **参議院 video_url の www. 欠落**: `speaker_tagger.py:208` で `webtv.sangiin.go.jp`（www なし）のままであり、再生成後のデータでも継続する。手動修正が必要
