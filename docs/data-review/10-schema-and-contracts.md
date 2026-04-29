# 10. データの持ち方・スキーマ・契約

## 10.1 全体スキーマの俯瞰

`models.py` で定義された Pydantic モデルが事実上の正本：

| モデル | ファイル | 主な属性 |
|--------|---------|---------|
| SpeakerInfo | metadata.json 内 | name, affiliation, role, start_seconds, ... |
| SessionDetail | metadata.json | chamber, session_id, date, committee, hls_url, speakers[] |
| WhisperSegment | raw_transcript.json 内 | id, start, end, text, no_speech_prob |
| SegmentTranscript | raw_transcript.json 内 | segment_index, speaker_name, text, whisper_segments[] |
| RawTranscript | raw_transcript.json | session_id, corrected, segments[] |
| Utterance | utterances.json 内 | speaker, role, text |
| SegmentUtterances | utterances.json 内 | segment_index, segment_speaker, utterances[], video_url |
| UtterancesOutput | utterances.json | segments[] |
| QuestionDetail | qa_pairs.json 内 | speaker, party, summary, full_text, intent |
| AnswerDetail | qa_pairs.json 内 | speaker, role, summary, full_text, evasion_score, has_commitment, commitment_text |
| QAPair | qa_pairs.json 内 | id, segment_index, topic, question, answer, follow_up_ids, video_url |
| KeyCommitment | summary.json 内 | speaker, role, text, topic, qa_id |
| RelatedLawTag | summary.json 内 | law_id, qa_ids[] |
| SummaryOutput | summary.json | session_summary, key_topics[], key_commitments[], related_laws[] |
| Topic | topics.json 内 | name, description, related_qa_ids[], related_speakers[] |
| TopicsOutput | topics.json | topics[] |

## 10.2 観測されている契約違反

### A. `SpeakerInfo.role` が常に空（100%）

[02-cross-cutting-issues.md §2.3](02-cross-cutting-issues.md#23-speakerinforole-が一切埋められていない) で詳述。
モデル定義 `role: str = ""`（デフォルト空）が事実上の挙動になっており、
1367 名すべて `role=""`。**スキーマは存在するが運用されていない**。

### B. `Utterance.role` の規約違反

`speaker_tagger.py:37` のシステムプロンプト：

```
roleは以下のいずれかを使用: 委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他
```

実データは規約外の値を 31 件含む（`〇〇大臣`）。
Pydantic で `Literal[...]` を使えば パース時に弾けるが、現状は `role: str` なので
何でも入る。

### C. `AnswerDetail.evasion_score` の生成条件不明

`models.py:114`:

```python
evasion_score: float = Field(ge=0.0, le=1.0)
```

`0.0 ≤ x ≤ 1.0` の制約はあるが、**「答弁が空の場合」の値**は規定されていない。
[06-qa-extraction.md §A](06-qa-extraction.md#a-答弁が空のペアが大量に生成される217-件) の通り、
`answer.full_text == ""` のとき `evasion_score = 1.0` がデフォルトのように
なっているが、これは **「Q&A ペアではないもの」** に最大値を割り振る動作。

### 改善案

- `evasion_score: float | None = None` にして、
  「測定不能なケース」を表現できるようにする
- または `AnswerDetail` に `is_actual_answer: bool` フィールドを追加

### D. `commitment_text` の型が `str | None | ""` で不統一

`models.py:116`:

```python
commitment_text: str | None = ""
```

実データを眺めると：
- `null` のケース
- `""` のケース
- 「適切に検討してまいります」のような実質意味のない文字列のケース

**3 通りの「コミットなし」表現**が混在している。

### 改善案

- `has_commitment=False` のとき `commitment_text=None` で固定
- `has_commitment=True` のとき `commitment_text` は必須（Pydantic validator で）
- 既存データのバックフィル（migration script）も書く

### E. `qa_id` がセッション内連番（横断ユニーク性なし）

[02-cross-cutting-issues.md §2.5](02-cross-cutting-issues.md#25-セッションごとに-qa_id-がリセットされる横断-id-不在) で詳述。
ID 設計を `{session_id}-qa_NNN` に変更すべき。

### F. `committee` が「不明」「特別委員会」（具体名欠落）の値も許容している

`SessionDetail.committee: str` には何でも入る。スクレイパーが失敗した場合の
プレースホルダ `"不明"` がそのまま保存され、URL パスに `_不明` が出る。

### 改善案

- スクレイパーで救済（[02-cross-cutting-issues.md §2.2](02-cross-cutting-issues.md#22-スクレイパーの委員会名抽出が壊れている)）
- もしくは `committee_resolution_status: "confirmed" | "ambiguous" | "unknown"` のようなフィールドを
  追加してサイト側で表示制御

## 10.3 ファイル間の参照整合性が保証されていない

### 観測される整合性問題

| ソース | 参照先 | 整合性 |
|-------|--------|--------|
| `topics.related_qa_ids` | `qa_pairs.pairs[].id` | LLM 出力依存（保証なし）|
| `summary.key_commitments[].qa_id` | `qa_pairs.pairs[].id` | LLM 出力依存（保証なし）|
| `summary.related_laws[].qa_ids` | `qa_pairs.pairs[].id` | LLM 出力依存（保証なし）|
| `summary.related_laws[].law_id` | `laws.json bills[].id` | LLM 出力依存（保証なし）|
| `qa_pairs.pairs[].segment_index` | `utterances.segments[].segment_index` | コード保証あり |
| `qa_pairs.pairs[].follow_up_ids` | `qa_pairs.pairs[].id` | 現状空配列のみ |

LLM 出力依存の参照が **4 種** ある。
これらが site のビルド時に検証されていないので、壊れたデータがそのままサイトに反映される。

### 改善案

パイプライン末尾、または `site/scripts/generate-api.ts` の入力検証で、
**すべての参照を validate** する：

```python
def validate_session_outputs(output_dir: Path) -> list[str]:
    """セッションの出力ファイル群の整合性をチェック。違反のリストを返す。"""
    qa = QAPairsOutput.model_validate_json(...)
    summary = SummaryOutput.model_validate_json(...)
    topics = TopicsOutput.model_validate_json(...)

    qa_ids = {p.id for p in qa.pairs}

    issues = []
    for t in topics.topics:
        for ref_id in t.related_qa_ids:
            if ref_id not in qa_ids:
                issues.append(f"topics: {t.name} → unknown qa_id {ref_id}")

    for c in summary.key_commitments:
        if c.qa_id and c.qa_id not in qa_ids:
            issues.append(f"key_commitments: {c.text[:30]} → unknown qa_id {c.qa_id}")

    for rl in summary.related_laws:
        for q in rl.qa_ids:
            if q not in qa_ids:
                issues.append(f"related_laws: {rl.law_id} → unknown qa_id {q}")
    return issues
```

CI で実行して violation を fail にする。

## 10.4 ファイル分割の妥当性

現状: 1 セッション = 6 ファイル（metadata, raw_transcript, utterances, qa_pairs, summary, topics）。

### 良い点
- ステップごとに責務が分離されており、git diff レビューが楽
- 部分的な再生成（Step 6 だけ走らせ直す）が可能
- 大きな full_text を持つ raw_transcript を、qa_pairs から分離できる
  （site は qa_pairs だけ読めば良い）

### 悪い点

- **ファイルが多すぎる**：1 セッションで 6 ファイル × 140 セッション = 840 ファイル。
  git の object 数が肥大化（実際 `data/` 配下は深いネスト）。
- **`whisper_segments` のサイズ**：`raw_transcript.json` の各 SegmentTranscript に
  `whisper_segments: list[WhisperSegment]` が入っており、`tokens: list[int]` が
  各 segment あたり数十〜数百 token。サイト側では使っていない。
  もし将来も使わないなら `whisper_segments` を別ファイル `whisper_raw.json` に分離する
  選択肢がある（`raw_transcript.json` の `text` だけが site で必要）。

### 観点

git は blob を効率的にデルタ圧縮するので、ファイル数は性能に直接影響しない。
ただし PR レビュー時の見通しと、site 側の I/O（fs.readFileSync × 6 × 140）には影響する。

### 改善案

- 短期: 現状維持
- 中期: `raw_transcript.json` から `whisper_segments` を分離。
  `raw_transcript.json` を「校正後テキストのみ」に絞る
- 中期: 1 セッション 1 ファイル化（`session.json` に全部マージ）も検討。
  ただし生成パイプラインの中間状態を git で見られなくなるトレードオフ

## 10.5 `corrected` フラグの設計

`raw_transcript.json` の `corrected: bool` は **「Step 4.5 を通過したか」** を示すが、
[03-pipeline-architecture.md §3.4](03-pipeline-architecture.md#34-冪等でない副作用) の通り、
チャンク棄却が起きた場合も `corrected=true` になる。

### 改善案

```python
class RawTranscript(BaseModel):
    session_id: str
    correction: CorrectionStatus | None = None  # NEW
    segments: list[SegmentTranscript]

class CorrectionStatus(BaseModel):
    completed_at: str
    fully_corrected: bool                # 全チャンク棄却なし
    rejected_chunks: int                 # 棄却数
    total_chunks: int
    model: str = "deepseek-ai/DeepSeek-V3.2"
```

サイト側で「Step 4.5 が部分失敗したセッション」を区別できるようになる。

## 10.6 `processed_at` の運用

`SessionDetail.processed_at` はメタデータに含まれているが、
`raw_transcript.corrected_at` とは別物。Step 6 の処理日時はどこにも記録されていない。

**改善案**：1 セッションあたり `processing_history.json` を追加：

```json
{
  "scraped_at": "2026-04-29T01:00:00+09:00",
  "transcribed_at": "2026-04-29T01:30:00+09:00",
  "corrected_at": "2026-04-29T01:35:00+09:00",
  "tagged_at": "2026-04-29T01:40:00+09:00",
  "structured_at": "2026-04-29T01:50:00+09:00",
  "models": {
    "whisper": "openai/whisper-large-v3-turbo",
    "corrector": "deepseek-ai/DeepSeek-V3.2",
    "tagger": "deepseek-ai/DeepSeek-V3.2",
    "structurer": "google/gemma-4-31B-it"
  }
}
```

将来モデルを切り替えたとき、データの世代管理ができる。

## 10.7 改善案サマリー

- [ ] **[P0]** `Utterance.role` を `Literal[...]` 型に
- [ ] **[P0]** site/scripts で参照整合性 validation を追加
- [ ] **[P0]** `evasion_score` を `Optional[float]` に変更し空答弁時は None
- [ ] **[P1]** `commitment_text` の null/empty/空文字列の混在を解消
- [ ] **[P1]** `corrected` フラグを `CorrectionStatus` 型に拡張
- [ ] **[P1]** `qa_id` をセッション横断ユニークに（[02-cross-cutting-issues.md §2.5](02-cross-cutting-issues.md#25-セッションごとに-qa_id-がリセットされる横断-id-不在)）
- [ ] **[P2]** `processing_history.json` を追加
- [ ] **[P2]** `whisper_segments` を別ファイルに分離
