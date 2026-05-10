# パイプライン刷新 進捗管理

`docs/STRUCTURER_REWRITE.md` で計画した完全刷新の実装進捗を追跡する。
別セッションでも本書を起点に状態を把握 → 未着手の依存解消済み PR を着手 → 完了したら本書を更新、というループで進める。

---

## 採用方針: D + B ハイブリッド

1. **第1セッション (smoke)**: 小規模 PR 3-4個を一気に実装し、F0 で動作確認 → 「土台が動く」ことを早期確認
2. **第2-3セッション (リスク先行)**: PR9 (utterance_indices schema、最大リスク) に集中。F1 サンプル4件で動作確認
3. **第4セッション以降 (ブロック消化)**: PR9 が機能すれば残りをブロック単位で並列消化
4. **最終2-3セッション (検証)**: F2 → F3 → F4 で段階検証 → 全件再生成

詳細な PR 内容・実装箇所・期待解消率は `docs/STRUCTURER_REWRITE.md §2-§5` を参照。

---

## セッション計画 (D+B ハイブリッド)

| セッション# | スコープ | 含む PR | 期待アウトプット |
|---|---|---|---|
| **#1 smoke** | 独立小規模 PR + F0 | PR2, PR4, PR14, PR15 (規約のみ) | F0 通過、開発サイクル動作確認 |
| **#2 schema-1** | utterance schema 設計+試作 | PR9 前半 (prompts.py V2、structurer.py 雛形) | 単一セッションで dry-run 通過 |
| **#3 schema-2** | utterance schema 完成 | PR9 後半 (assemble_full_text、テスト) + F1 サンプル4件で検証 | F1 通過、resolved ≥ 50% |
| **#4 enrichment** | metadata enrichment | PR1, PR3, PR6 | metadata.speakers が答弁者を含む |
| **#5 corrector+content** | corrector 強化 + content_missing 対策 | PR5, PR7, PR8, PR10, PR11 | F1 で whisper_loop 解消、content_missing 改善 |
| **#6 structurer 検証強化** | summary validation + follow_up | PR12, PR13 | F1 で summary_qa_divergence 改善 |
| **#7 ISSUES 取り込み** | 堅牢性改修 | PR17, PR18, PR19, PR20 | F1 通過維持 |
| **#8 検証 F2** | 多様性12件で再生成 + 比較 | (実装なし) | F2 ゲート通過 |
| **#9 検証 F3** | 中規模30件で再生成 + 比較 | (実装なし) | F3 ゲート通過 |
| **#10 全件 F4** | 全156件削除 + 再生成 + サイトビルド | (実装なし) | 公開 |

合計 **約10セッション**、3-4週間。各セッションは半日〜1日を想定。

---

## PR チェックリスト

ステータス凡例: ☐ todo / 🔄 in-progress / ✅ done / ❌ blocked / ⏭ skipped

| PR | 内容 (§参照) | サイズ | ステータス | ブランチ | 完了日 | メモ |
|---|---|---|---|---|---|---|
| PR1 | scraper dedup (§2.4) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | (name, affiliation) で dedup、duration 合算、start_seconds 最小、両院 + 9 unit テスト |
| PR2 | video_url www. 修正 (§2.14) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | speaker_tagger.py:208 + test 強化 |
| PR3 | derive_role 拡張 (§2.9) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | 事務総長/臨時委員長/副議長 を委員長扱い、複合 affiliation の substring 検出、テスト +6件 |
| PR4 | schema 規約明文化 (§2.12) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | models.py モジュール docstring に規約追記 |
| PR5 | 拡張閣僚リスト (§2.6) | 🟢 小 | ☐ | | | (#5 batch) |
| PR6 | metadata enrichment (§2.2/2.3) | 🟡 中 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | metadata_enricher.py 新規、Step 5.25 として pipeline 挿入、委員長指名文 + speaker 名末尾の役職抽出、テスト 29件、F1 で 56211 role 充足率 1.4→52.8%、8967 0→26.3% |
| PR7 | corrector 安全チェック緩和 (§2.5) | 🟢 小 | ☐ | | | (#5 batch) |
| PR8 | corrector 禁止事項強化 (§2.6/2.7) | 🟢 小 | ☐ | | | (#5 batch) |
| PR9 | utterance_indices schema (§2.1) | 🔴 **大** | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | 前半 #2: prompts.py V2 + structurer.py 雛形 / 後半 #3: anchor + 共有 utterance テスト 15件 + F1 4件全 exit 0 |
| PR10 | content_missing 対策 (§2.10) | 🟡 中 | ☐ | | | (#5 batch、PR9 依存) |
| PR11 | floor_speech summary 経路 (§2.10) | 🟡 中 | ☐ | | | (#5 batch、PR10 依存) |
| PR12 | summary post-validation (§2.11) | 🟡 中 | ☐ | | | (#6 batch、PR9+PR11 依存) |
| PR13 | follow_up_ids 実装 (§2.14) | 🟢 小 | ☐ | | | (#6 batch、PR9 依存) |
| PR14 | leading_silence 閾値調整 (§2.13) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | pipeline.py offset 30s → 5s |
| PR15 | schema validator スクリプト (§2.12) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | scripts/validate_data_schema.py 追加、現 data/ 156件全 parse 成功 |
| PR16 | 比較サブエージェント仕様 (§3.4) | 🟢 小 | ☐ | | | (#1 smoke or 必要時) |
| PR17 | ffmpeg subprocess timeout (§2.15) | 🟢 小 | ☐ | | | (#7 batch) |
| PR18 | speaker_tagger json.loads ラップ (§2.15) | 🟢 小 | ☐ | | | (#7 batch) |
| PR19 | スクレイパー堅牢性 (§2.16) | 🟡 中 | ☐ | | | (#7 batch、テスト含む) |
| PR20 | 法案タグ精度検証 (§2.17) | 🟡 中 | ☐ | | | (#7 batch、F2 ゲート前必須) |

---

## 検証フェーズ チェックリスト

| フェーズ | サンプル数 | ゲート条件 | ステータス | 結果ノート |
|---|---:|---|---|---|
| **F0 smoke** | 1 (56074) | exit 0 + 6ファイル出力 | ✅ | 2026-05-10: Step 4.5+ 再実行 122s、qa=1/topics=1、6ファイル全て生成 (PR14 は Step 3 のため smoke カバー外、コード差分のみ確認) |
| **F1 既知問題** | 4 (56074, 56075, 56211, 8967) | resolved ≥ 50%、新規 NEW_ISSUE = 0 | 🔄 | 2026-05-10 (PR1+PR3+PR6 後): 4件全 exit 0 (56075=103.9s/qa=0、56211=312.5s/qa=72、56074=165.8s/qa=2、8967=233.5s/qa=57)。**PR6 metadata enrichment の効果検証** — 56211 で metadata.speakers 12→48 (答弁者 0→11、政府参考人 0→25 補完)、answer.role 充足率 **1.4% → 52.8% (+51.4pt)**。8967 で speakers 9→34 (答弁者 0→10、政府参考人 0→15)、role 充足率 **0% → 26.3% (+26.3pt)**。56074 (本会議) は speakers 不変だが role 充足率 75% → 100%。委員長指名文での affiliation 推定に加え、speaker 名末尾の役職タイトル抽出 ("松本大臣" → "大臣"、"内閣府宇宙開発戦略推進事務局長" → 全文を affiliation) のフォールバックが効いた。Step 5.25 ステップ追加コストは無視できる (1-3ms/セッション)。残カテゴリは PR9 後と同様、他 PR 担当のため UNCHANGED 想定通り。LLM ベース全件比較は #5-#7 で実施 |
| **F2 多様性** | 12 (層化抽出) | 平均 ≤ 5件/セッション、未知カテゴリ unchanged ≤ 2 | ☐ | |
| **F3 中規模** | 30 | F1/F2 整合、エラー率 < 5%、コスト < $0.5/sess | ☐ | |
| **F4 全件** | 156 | — | ☐ | |

ゲート詳細: `docs/STRUCTURER_REWRITE.md §3.2`

---

## ブランチ戦略

- **ベースブランチ**: `michitomo/structurer-rewrite-plan` (既存、本書もこのブランチ)
- **PR 単位の feature branch**: `michitomo/pr<N>-<short-name>` 形式 (例: `michitomo/pr1-dedup`)
- **マージポリシー**:
  - 小規模 (🟢) PR は base にそのまま push (review 不要なら)
  - 中・大規模 (🟡🔴) PR は feature branch で実装後、PR を作成して self-review してマージ
- **F4 直前 タグ**: `pre-f4-snapshot` (rollback 用、`docs/STRUCTURER_REWRITE.md §5.1` 参照)

---

## F1 検証の頻度

- **F1 必須実施 PR**: PR9 (#3 セッション末)、PR6 (#4 セッション末)、PR10/PR11 (#5 セッション末)、PR12 (#6 セッション末)
- **その他**: ブロック完了時 (1セッションの最後) に diff 確認のみ
- **F2 直前**: 全 PR1-20 マージ済を確認、F1 で resolved ≥ 50% を満たすことを確認

---

## 別セッション開始時のテンプレ prompt

新しい Claude セッションを開始するときは、以下を冒頭に貼る:

```
このリポジトリでパイプライン刷新を進めています。引き継ぎ手順:

1. docs/REWRITE_PROGRESS.md を読み、未着手・着手中・完了の PR 状況を把握
2. 「セッション計画」表で次のセッションのスコープを特定 (もしくは ID を指定)
3. 該当 PR について docs/STRUCTURER_REWRITE.md §2.X (該当セクション) を読み、
   実装箇所・期待解消率・依存 PR を確認
4. 依存 PR が全て完了 (✅) していることを REWRITE_PROGRESS.md で確認
5. 必要なら CLAUDE.md でプロジェクト規約再確認
6. 実装 → tests → 動作確認 → commit → push
7. REWRITE_PROGRESS.md を更新:
   - 該当 PR を ✅ にする (担当ブランチ・完了日・メモを記入)
   - 「セッションログ」に当セッションのサマリ追記
8. F1 検証必須 PR の場合は /tmp/regen_test.py に倣って F1 サンプル4件で
   動作確認、結果を REWRITE_PROGRESS.md の F1 行に記録

注意:
- 全データ削除前提だが、F4 直前まで data/ は触らない (F0-F3 は /tmp/regen-test/ 出力)
- DEEPINFRA_API_KEY は /Users/michitomo/git/kokkaidb/.env に設定済
- 検証は Sonnet 並列サブエージェントで実施 (docs/QUALITY_AUDIT_FORMAT.md 形式)
```

---

## セッションログ

完了したセッションのサマリを下から追記。

### 2026-05-10 (準備セッション)
- 90セッション監査実施 (`docs/audit-results/`)
- 4セッションで Step 4.5+ 検証 (`docs/regen-comparison/`)
- データ生成時↔現コード差分分析 (`docs/PIPELINE_FIX_STATUS.md`)
- `docs/STRUCTURER_REWRITE.md` を全カテゴリ網羅版に拡張 (312→887行)
- ISSUES.md / ISSUES2.md からデータ生成起因項目を `STRUCTURER_REWRITE.md` §2.15-§2.17 に移管
- 本書 `REWRITE_PROGRESS.md` を作成、D+B ハイブリッド方針を採用

### Session #1 (smoke) — 2026-05-10 完了
- 実装:
  - PR2: `speaker_tagger.py:208` の参議院 video_url を `www.webtv.sangiin.go.jp` に修正
  - PR4: `models.py` モジュール docstring に null/空文字統一規約 (§2.12) を明文化
  - PR14: `pipeline.py` の offset 補正閾値を 30s → 5s に (§2.13)
  - PR15: `kokkai-transcriber/scripts/validate_data_schema.py` 新規作成。data/ 配下を Pydantic で parse + speaker 整合チェック
- 検証:
  - `tests/test_speaker_tagger.py::TestBuildVideoUrl` 3件 pass
  - validator 現 data/ 156件 全 Pydantic parse 成功 / 115件で speaker 整合 warning (§2.3、PR6 で対応予定)
  - F0 smoke: `/tmp/regen_smoke.py` で 56074 を Step 4.5+ 再実行、122s、6ファイル出力 OK
- メモ:
  - PR14 (Step 3 閾値) は Step 4.5+ 再実行ではカバー外。フルパイプライン smoke は次セッション以降で機会があれば
  - validator の speaker 不整合 warning は PR6 metadata enrichment で大幅減少見込み

### Session #4 (enrichment) — 2026-05-10 完了
- 実装:
  - **PR1** (`scrapers/{shugiin,sangiin}.py:_extract_speakers`): `(name, affiliation)` キーで dedup。既存と同じキーが現れたら `start_seconds` は最小、`duration_minutes` を合算、`start_time` は最若スロットを保持。元の出現順は維持。両院共通実装で同形式。
  - **PR3** (`scrapers/_role.py:derive_role`): 委員長相当の判定を `endswith` だけでなく substring 検出に拡張、`事務総長` を新規追加。「臨時委員長」「衆議院事務総長」「副議長」「複合 affiliation (空白区切り等)」を捕捉。
  - **PR6** 新規モジュール `src/metadata_enricher.py` (~140行):
    - `_NOMINATION_PATTERN`: 委員長 utterance 内の「(役職タイトル)<人名>君|氏|さん|議員|委員」を抽出。タイトルキーワード18種を長い順に試行 (内閣総理大臣 → 副大臣 → 大臣 ...)
    - `_extract_affiliation_from_name`: speaker_tagger が「松本大臣」「内閣府宇宙開発戦略推進事務局長」のような役職込み name を返すケースのフォールバック。prefix が「省/府/院/庁/局/部/委員会/会議/事務」を含めば name 全体を affiliation に、そうでなければ末尾 keyword だけを affiliation に。
    - `enrich_metadata_from_utterances`: 全 utterance を走査、role∈{答弁者, 政府参考人} かつ既存 speakers と fuzzy 一致しない名前を候補化。affiliation 推定は (1) 委員長指名文、(2) name 末尾、の優先順。元 speakers は破壊的編集しない。
  - **Pipeline 統合** (`pipeline.py`): Step 5↔5.5 間に `Step 5.25: enrich_metadata_from_utterances` を挿入。新規 speaker が追加されたら `metadata.json` を上書き保存し、Step 5.5 normalizer は拡張済 speakers でマッチング → answer.role に affiliation が伝播。
  - **F1 検証スクリプト更新** (`/tmp/regen_test.py`): Step 5.25 enrichment を追加、metadata 上書きも再現。
- 検証:
  - unit tests:
    - `test_role_derivation.py`: 23 → **29 件 pass** (+6 件: 臨時委員長/事務総長/衆議院事務総長/参議院事務総長/副議長/複合 affiliation)
    - `test_shugiin_scraper.py::TestExtractSpeakersDedup`: **5 件追加 pass** (同名同所属 dedup、別所属非 dedup、3 スロット合算、未ソート最小化、順序保持)
    - `test_sangiin_scraper.py::TestExtractSpeakersDedup`: **4 件追加 pass** (同様)
    - `test_metadata_enricher.py`: **29 件新規 pass** (NominationPattern 7、ExtractAffiliationFromName 6、ChairNominationMap 3、EnrichMetadataFromUtterances 13)
  - 全 unit (-m "not integration"): pre-existing 10 failure (3 scraper baseline + 7 ffmpeg 不在環境) のみ、新規 regression なし
  - **F1 サンプル4件 全 exit 0**:
    - 56075 本会議 (floor_speech): 103.9s, qa=0/topics=0 (skipped by design)
    - 56211 内閣委員会: 312.5s, qa=72/topics=2、speakers **12 → 48** (答弁者 +11、政府参考人 +25)、**answer.role 充足率 1.4% → 52.8% (+51.4pt)**
    - 56074 本会議: 165.8s, qa=2/topics=1、role 充足率 **75% → 100%**
    - 8967 内閣委員会: 233.5s, qa=57/topics=2、speakers **9 → 34** (答弁者 +10、政府参考人 +15)、role 充足率 **0% → 26.3% (+26.3pt)**
- ノート:
  - 期待解消率 ~85% に対し実績は 56211 で 52.8%、8967 で 26.3% — 残ギャップは structurer.py `_resolve_answerer_from_utterances` が議員名を答弁者として返すケース (segment 内に非議員候補が見つからない、または speaker_tagger が短い surname を返してリソースとマッチしない) と、affiliation が "(空)" のまま enriched される候補 (短い surname e.g. "上野", "佐々木") に起因。これらは PR8 (corrector 強化) や PR9 のリトライ条件改善で部分解消見込み
  - Step 5.25 のオーバーヘッドは 1-3ms、無視できるコスト
  - V4 metrics の `'date'` literal_error は Session #2 から継続 (15 件失敗 / 8967)、別 PR で修正
- 残作業 (Session #5 へ):
  - PR5 (拡張閣僚リスト)、PR7 (corrector 安全チェック緩和)、PR8 (corrector 禁止事項強化)、PR10 (content_missing 対策)、PR11 (floor_speech summary 経路)

### Session #3 (schema-2) — 2026-05-10 完了
- 実装 (PR9 後半):
  - `tests/test_structurer.py` に共有 utterance + anchor シナリオの単体テストを追加:
    - `TestAssembleFullTextForPair` 5件追加 (anchor 単独、anchor+boundary、anchor=0、範囲外フォールバック、anchor + 後続 utterance)
    - `TestComputeShareBoundaries` 8件: 空・anchor なし・単独共有・2/3 ペア共有 (順不同入力含む)・q/a 独立・None 除外・別 head 非共有
    - `TestSharedUtteranceEnd2End` 1件: `_extract_pairs_from_response` 経由で anchor=1 と anchor=5 の 2 ペアが utterance を分割共有し、全文を穴なく分配することを検証
  - 構造的に `_compute_share_boundaries` (anchor 昇順 → 次 anchor を境界、最後は None) と `_assemble_full_text_for_pair` の anchor + boundary 連携を合計 14 件で固める
- 検証:
  - unit tests: structurer 47/47 pass (PR9 前半 32 + PR9 後半 15)
  - 全 unit (-m "not integration"): 245 pass / pre-existing 10 failure (3 scraper baseline + 7 ffmpeg 不在環境)
  - F1 サンプル4件 全 exit 0 (`/tmp/regen-test/_summary.json` 参照):
    - 56075 本会議 (floor_speech): 92.9s, qa=0/topics=0 (skipped by design)
    - 56211 内閣委員会: 394.9s, qa=73/topics=2
    - 56074 本会議: 133.5s, qa=2/topics=1
    - 8967 内閣委員会: 317.3s, qa=58/topics=2
  - **PR9 が target する transcript_truncation の改善検証** (`/tmp/f1_compare.py`):
    - 8967 平均 Q 文字数 199 → **381** (+90%)、平均 A 文字数 322 → 367 (+15%)
    - 8967 NEW Q 非句点終わり 10.3% は truncation ではなく **次話者名 (e.g. "小山審議官") が末尾に混入する Whisper 特性** に起因 (utterance 全文を取り込んだ副作用)
    - 56211 NEW Q/A 非句点終わり 2.7%/2.7%、Q/A 文字数も大幅増
- ノート:
  - F1 ゲート (resolved ≥ 50%) は LLM ベースの個別 finding 比較が必要だが、現状の `docs/audit-results/` の findings はほぼ PR9 が target しないカテゴリ (whisper_hallucination, role_empty, speaker_misattribution 等) のため、PR9 単独では UNCHANGED 想定通りで意味が薄い。他 PR 完了後 (Session #5/#6 末尾) に LLM 比較を一括実施する判断
  - V4 metrics の `'date'` literal_error は Session #2 から継続 (15 件失敗 / 8967)、別 PR で修正
  - 56075 (floor_speech) の旧 qa=32 → NEW qa=0 は `_FLOOR_LIKE_KINDS` skip に由来、PR9 と無関係
- 残作業 (Session #4 へ):
  - PR1, PR3, PR6 (metadata enrichment) — 答弁者 metadata 補完 → role 充足率改善

### Session #2 (schema-1) — 2026-05-10 完了
- 実装 (PR9 前半):
  - `src/prompts.py` `QA_SEGMENT_SYSTEM_PROMPT` を V2 に全面書き換え (utterance_indices + 任意 split_anchor_sentence_idx)
  - `src/structurer.py` 雛形:
    - 旧 `_build_sentence_map` / `_assemble_full_text_from_sentences` / `_build_sentence_to_utterance_map` / `_resolve_*_from_sentences` を削除
    - 新 `_SegmentLayout` dataclass + `_compute_segment_layout` / `_build_utterance_map` (`[U0]`...形式、長文 utterance のみ `(sN)` 併記) を追加
    - 新 `_assemble_full_text_for_pair` (anchor 対応、共有 utterance の boundary 計算は `_compute_share_boundaries`)
    - `_resolve_speaker_from_utterances` / `_resolve_answerer_from_utterances` を utterance_indices ベースに刷新
    - `_extract_pairs_from_response` 新スキーマ対応
    - `_INPUT_CHAR_LIMIT = 20000` の暫定切り捨てを撤廃 (代わりに 50000 char 警告ログ)
  - `tests/test_structurer.py` 更新: 削除された helper のテストを新 helper 用に書き換え、mock data を `utterance_indices` ベースに移行
- 検証:
  - unit tests: 32/32 pass (`tests/test_structurer.py`)
  - 全 unit (除く integration / ffmpeg依存): 226 pass / 3 pre-existing scraper failure
  - F0 dry-run #1: 56074 (本会議, procedural-only) — exit 0、6ファイル、qa=0/topics=0 (旧 qa=1 はおそらく hallucination、新プロンプトはより厳格に「往復必須」を要求)
  - F0 dry-run #2: 56211 (内閣委員会, 実 QA) — exit 0、6ファイル、qa=74/topics=17
    - first question.full_text=966 chars、answer.full_text=679 chars (utterance 全文連結が機能)
    - 句点終わり: question 2/74 (2.7%)、answer 5/74 (6.8%) — **旧スキーマの 52.5%/21.1% から大幅改善**
    - 「おはようございます。」「ご答弁いただきまして…」等の挨拶も full_text に保持される (新方式の意図通り)
- 残作業 (Session #3 へ):
  - 共有 utterance + anchor の単体テスト追加
  - F1 サンプル4件 (56074, 56075, 56211, 8967) で resolved ≥ 50% 検証
  - `_INPUT_CHAR_LIMIT` 撤廃の影響確認 (極端に長いセグメントの分割品質)
  - V4 metrics の `date` 型 literal_error (19/74 ペア失敗) は別 PR (pre-existing)

(以下、セッション完了ごとに追記)

---

## クイックリファレンス

| 何を見るか | パス |
|---|---|
| 全体計画 | `docs/STRUCTURER_REWRITE.md` |
| 進捗状態 (本書) | `docs/REWRITE_PROGRESS.md` |
| 監査結果データ | `docs/audit-results/*.json` (90件) |
| 既存検証データ | `docs/regen-comparison/*.json` (4件) |
| 現コード差分分析 | `docs/PIPELINE_FIX_STATUS.md` |
| 監査フォーマット | `docs/QUALITY_AUDIT_FORMAT.md` |
| プロジェクト規約 | `CLAUDE.md` |
| 比較スクリプト | `/tmp/regen_test.py` (F1 用テンプレ、要更新) |

---

## 主要意思決定の記録

(別セッションで方針変更が必要になったらここに追記)

- **2026-05-10**: D+B ハイブリッドで進める。総10セッション・3-4週間想定
- **2026-05-10**: PR9 を最大リスクとして #2-#3 で集中、その結果次第で残り PR の進め方を再評価
- **2026-05-10**: F1 検証は PR6/9/10/11/12 完了時のみ実施、他はブロック完了時の差分確認
