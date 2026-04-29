# 99. 優先順位ロードマップ

各章の改善案を優先度別に整理する。**P0 は本格稼働前に着手すべき**。

## P0 — クリティカル（本格稼働の前提条件）

### 1. セッション種別を一級概念にする
- `SessionDetail.session_kind: Literal["regular_qa", "representative_questions", "floor_speech", "procedural", "expert_hearing"]` を追加
- スクレイパー段階で議事記録の見出しから判定（衆議院 TV ページに「趣旨説明」「討論」「採決」の文言あり）
- Step 6 の挙動を `session_kind` で分岐させる：
  - `floor_speech` / `procedural` は Q&A 抽出スキップ
  - `representative_questions` は冒頭の趣旨説明セグメントをスキップ
- **効果**：22 セッションの「Q&A 0 件」、217 件の「答弁空ペア」、回避度 1.0 のスパイクをまとめて解消
- **章**: [02](02-cross-cutting-issues.md#21-セッション種別が一級概念になっていない), [06](06-qa-extraction.md), [03](03-pipeline-architecture.md)

### 2. Step 6b（要約・トピック）を 3 LLM 呼び出しに分割
- 6b-1: `session_summary` のみ
- 6b-2: `topics` + `key_topics`（key_topics は topics.name のサブセットに）
- 6b-3: `key_commitments`
- 関連法案タグは独立 6c へ
- **効果**：21 セッションの `topics.json` 空問題が解消。出力 token も短くなり安定する
- **章**: [02 §2.6](02-cross-cutting-issues.md#26-構造化-llm-呼び出しの-全部入り-json-が事故源), [07](07-summary-topics.md), [11](11-prompts-and-models.md)

### 3. 関連法案タグを Q&A ペア単位＋委員会×省庁プリフィルタで再設計（Step 6c）
- 委員会名と所管省庁から法案リストを 75 → 14 件程度に予選
- Q&A ペアごとに関連法案を判定（recall 重視）
- `qa_pairs[].related_law_ids` フィールドを追加
- **効果**：94 セッションの `related_laws=0` 問題が解消。サイトの法案フィルタが機能する
- **章**: [09](09-law-tagging.md)

### 4. 発言者名・役職の正規化レイヤを Step 5.5 として新設
- `metadata.json` の speakers を ground truth として、`utterances.json` 内の speaker を必ず正規化
- `〇〇大臣` の role は `答弁者` に強制変換
- `Utterance.role` を `Literal[...]` 型に
- `_fuzzy_lookup` の曖昧マッチを警告ログ化
- **効果**：高市・赤澤・林などの表記揺れ解消、UI/UX レビューの「発言者分析」破綻を直接的に修復
- **章**: [08](08-name-normalization.md), [05](05-speaker-tagging.md), [10](10-schema-and-contracts.md)

### 5. スクレイパーの委員会名抽出を 3 段階フォールバックに
- 既存 2 段階に加え、speakers の `affiliation` 末尾が `委員長` なら `委員会` に置換して採用
- **効果**：`committee="不明"` 5 セッション、`"特別委員会"` 4 セッションが復旧
- **章**: [02 §2.2](02-cross-cutting-issues.md#22-スクレイパーの委員会名抽出が壊れている)

### 6. `SpeakerInfo.role` を `affiliation` から自動派生で必ず埋める
- スクレイパーで `_derive_role()` を呼んで、`委員長` / `答弁者` / `政府参考人` / `参考人` / `質疑者` を判定
- **効果**：1367/1367 の `role=""` 問題が解消。Step 5 のプロンプトに事前情報を渡せる
- **章**: [02 §2.3](02-cross-cutting-issues.md#23-speakerinforole-が一切埋められていない)

### 7. 答弁テキスト 30 字未満のペアを生成・出力時に drop
- `_extract_pairs_from_response` でフィルタ
- プロンプトの「禁止事項」セクションに明示
- **効果**：217 件の「答弁空 + 回避度 1.0」ノイズが消える
- **章**: [02 §2.4](02-cross-cutting-issues.md#24-答弁が無いものを-qa-ペアにしてしまう失敗の連鎖), [06](06-qa-extraction.md)

### 8. site/scripts に参照整合性 validation を追加
- `topics.related_qa_ids` / `summary.key_commitments[].qa_id` / `summary.related_laws[].qa_ids` /
  `summary.related_laws[].law_id` の参照先存在チェック
- 違反は警告ログに残し、build を fail させる選択肢も
- **効果**：壊れた参照がサイトに反映されることを防止
- **章**: [10 §10.3](10-schema-and-contracts.md#103-ファイル間の参照整合性が保証されていない)

---

## P1 — 高優先度（本格稼働後すぐに）

### 9. プロンプトに「禁止事項」セクションを追加
- Step 6a / 6b に明確な禁止リスト
- 「漏らさず」を「Q&A 構造があるもののみ漏らさず」に修正
- 「同じ答弁を複数のペアに使わない」を追記
- **章**: [11 §11.2.E](11-prompts-and-models.md#e-プロンプトのペナルティ表現が一部弱い)

### 10. Step 4.5 を 2 段階に分割
- 4.5a: 句読点・改行・フィラー除去（表層編集、軽量モデル）
- 4.5b: 固有名詞・同音異義語修正（意味理解、強いモデル）
- もしくは「介護保険 ↔ 国民皆保険」のような頻出文脈依存ルールは正規表現＋窓関数で決定論的に
- **章**: [04](04-transcription.md), [03](03-pipeline-architecture.md)

### 11. `evasion_score` を `Optional[float]` に変更
- 答弁が空 / 測定不能なケースは `None`
- プロンプトに「回避度の判定は答弁が存在する場合のみ」を明示
- **章**: [10 §10.2](10-schema-and-contracts.md#c-answerdetailevasion_score-の生成条件不明), [06](06-qa-extraction.md)

### 12. `commitment_text` の null/empty/「適切に検討」混在を解消
- `has_commitment=False` のとき `commitment_text=None` で固定（Pydantic validator）
- `commitment_strength: "specific" | "vague" | "none"` の 3 値を追加
- **章**: [06 §G](06-qa-extraction.md#g-has_commitment--commitment_text-の整合性), [10](10-schema-and-contracts.md)

### 13. 答弁の重複検出・マージ
- 同一セグメント内で `a_indices` の overlap 90%+ のペアは `follow_up_ids` でマージ
- **章**: [06 §E](06-qa-extraction.md#e-答弁の重複同一テキストが複数ペアに入る)

### 14. Step 6 の密度リトライをセッション種別に応じて無効化
- `floor_speech` / `representative_questions` では Q&A 密度の判定を行わない
- **章**: [03 §3.3](03-pipeline-architecture.md), [06](06-qa-extraction.md)

### 15. `_fuzzy_lookup` の曖昧マッチを警告ログ＋deterministic化
- 1 文字姓で複数候補があれば warning、最も登場順が早い speaker を採用
- 1 文字マッチを廃止し、Step 5 のプロンプトで「フルネーム必須」を要求
- **章**: [08 §8.4](08-name-normalization.md), [05](05-speaker-tagging.md)

### 16. `qa_id` をセッション横断ユニークに
- `{session_id}-qa_NNN` 形式に変更
- もしくは互換用に `global_id` フィールドを追加
- **章**: [02 §2.5](02-cross-cutting-issues.md#25-セッションごとに-qa_id-がリセットされる横断-id-不在), [10](10-schema-and-contracts.md)

### 17. `corrected` フラグを `CorrectionStatus` 型に拡張
- 棄却数・全体成功率・モデル名を保存
- **章**: [10 §10.5](10-schema-and-contracts.md#105-corrected-フラグの設計)

---

## P2 — 中優先度

### 18. 整合性チェックステップ（Step 7）を新設
- バッチ実行後にレポート出力
- CI で違反数を可視化
- **章**: [03 §3.2.C](03-pipeline-architecture.md), [10 §10.3](10-schema-and-contracts.md)

### 19. プロンプトキャッシュを意識した user prompt 構造
- Step 5 / 6 で speaker_list などの定型部を prefix に分離
- **章**: [11 §11.2.C](11-prompts-and-models.md#c-プロンプトキャッシュの活用が不十分)

### 20. LLM 並列度を 80 → 20 に下げて安定性向上
- Rate limit リスクとリトライ頻度を実測してから決める
- **章**: [03 §3.5](03-pipeline-architecture.md#35-並列度の考え方)

### 21. `whisper_segments` を別ファイルに分離
- `raw_transcript.json` のサイズ削減、site の I/O 改善
- **章**: [10 §10.4](10-schema-and-contracts.md#104-ファイル分割の妥当性)

### 22. `processing_history.json` を追加
- モデル世代管理、再実行時の差分追跡
- **章**: [10 §10.6](10-schema-and-contracts.md#106-processed_at-の運用)

### 23. intent enum の見直し
- 現状 `information_request` が 60% で識別力なし
- 例: `factual_query / position_clarification / oversight / proposal / declaration / other`
- **章**: [06 §F](06-qa-extraction.md#f-intent-の分布偏り)

### 24. 法案の `status`（成立/審議中/廃案）をプロンプトとサイトに反映
- 審議中法案の watch list が機能する
- **章**: [09 §D](09-law-tagging.md#d-法案の状態status-成立-が全く活用されていない)

---

## P3 — 低優先度・将来構想

### 25. WhisperX / pyannote diarization の検証
- セグメント内話者分離をモデル側で
- **章**: [11 §11.2.B](11-prompts-and-models.md)

### 26. ダッシュボードで「自動文字起こしの不確かさ」を可視化
- Whisper の `no_speech_prob` / `compression_ratio` をサイトに公開
- **章**: [04 §4.4](04-transcription.md#44-改善案)

### 27. 参考人質疑（expert_hearing）専用のスキーマ
- 参考人ロールの発言を質問・答弁として扱うのは無理がある
- **章**: [02 §2.1](02-cross-cutting-issues.md)

### 28. 「分野（broad_topic）」の Closed vocabulary 化
- 30 個程度の事前定義カテゴリから LLM に選ばせる
- 関連法案タグと同じ vocabulary に統合する選択肢も
- **章**: [06 §C](06-qa-extraction.md#c-topic-の粒度がセッション議員テーマで不揃い), [09](09-law-tagging.md)

---

## まとめ

P0 の 8 項目を実装すると：

| 解消する問題 | 件数 |
|------------|------|
| `qa_pairs.json` 空のセッション | 22 → ほぼ 0 |
| `topics.json` 空のセッション | 21 → ほぼ 0 |
| `related_laws=0` セッション | 94 → 多数解消（推定 30 以下）|
| `committee="不明"` セッション | 5 → 0 |
| `committee="特別委員会"` 修飾語欠落 | 4 → 0 以下 |
| 答弁空＋回避度 1.0 のペア | 217 → 0 |
| 全 metadata で `role=""` | 1367/1367 → 0 |
| 発言者名表記揺れ（高市・赤澤・林等） | 多数 → 0（正規化）|

サイト閲覧時の「明らかに失敗してる」感のうち、**8〜9 割は P0 の作業範囲で解消**できる見込み。

P1 まで完了すれば、生成パイプラインは概ね「再現可能・冪等・整合性検証あり・一級概念分離済み」
の標準的な ETL システムとして機能する。それ以降の P2 / P3 は質改善・拡張機能の領域。
