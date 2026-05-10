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
| PR1 | scraper dedup (§2.4) | 🟢 小 | ☐ | | | (#4 batch) |
| PR2 | video_url www. 修正 (§2.14) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | speaker_tagger.py:208 + test 強化 |
| PR3 | derive_role 拡張 (§2.9) | 🟢 小 | ☐ | | | (#4 batch) |
| PR4 | schema 規約明文化 (§2.12) | 🟢 小 | ✅ | michitomo/structurer-rewrite-plan | 2026-05-10 | models.py モジュール docstring に規約追記 |
| PR5 | 拡張閣僚リスト (§2.6) | 🟢 小 | ☐ | | | (#5 batch) |
| PR6 | metadata enrichment (§2.2/2.3) | 🟡 中 | ☐ | | | (#4 batch、PR1+PR3 依存) |
| PR7 | corrector 安全チェック緩和 (§2.5) | 🟢 小 | ☐ | | | (#5 batch) |
| PR8 | corrector 禁止事項強化 (§2.6/2.7) | 🟢 小 | ☐ | | | (#5 batch) |
| PR9 | utterance_indices schema (§2.1) | 🔴 **大** | 🔄 | michitomo/structurer-rewrite-plan | 2026-05-10 (前半完了) | prompts.py V2 + structurer.py 雛形完了。後半は #3 で assemble_full_text の anchor テスト+F1検証 |
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
| **F1 既知問題** | 4 (56074, 56075, 56211, 8967) | resolved ≥ 50%、新規 NEW_ISSUE = 0 | ☐ | |
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
