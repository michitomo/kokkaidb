# 07. 要約・トピック・コミットメント・関連法案（Step 6b: summary.json + topics.json）

## 7.1 設計の良いところ

- **同じ入力（qa_pairs）から派生する 4 種の出力をひとまとめにする発想**自体は理にかなっている。
  4 回 LLM を呼ぶより 1 回で済む方が安上がりに見える。
- **`SummaryAndTopics` 系のデータモデル**は site 側でも素直に扱いやすい
  （`SummaryOutput` と `TopicsOutput` に分けて保存する設計）。
- **法案リストを LLM に注入する仕組み**（`structurer.py:691-692`）は、laws_compact.txt が
  事前ビルドできる前提なので決定的・冪等的で良い。

## 7.2 観測されている問題

### A. `topics.json` が空のセッションが 21 件（15%）

**観測**：

```bash
$ find data/shugiin -name topics.json -exec sh -c 'n=$(jq ".topics | length" "$1"); if [ "$n" = "0" ]; then echo "$1"; fi' _ {} \; | wc -l
21
```

例: `data/shugiin/2026/03/03/56092_財務金融委員会/topics.json` は
```json
{"topics": []}
```
なのに、同じセッションの `summary.json` には：
```json
{
  "key_topics": [
    "責任ある積極財政",
    "令和8年度予算および税制改正",
    "物価高対策と所得税課税最低限の引き上げ",
    "資産運用立国の推進と金融戦略の策定",
    "税関行政の強化と不公正貿易への対応"
  ],
  "key_commitments": [...]
}
```
が入っている。

### 原因

`structurer.py:665-768` の `generate_summary_and_topics` は単一 LLM 呼び出しで
**5 種類の出力**を要求する：

```json
{
  "session_summary": "...",       // 文字列
  "key_topics": ["..."],            // 文字列配列
  "key_commitments": [{...}],       // オブジェクト配列
  "topics": [{...}],                // オブジェクト配列（最も大きい）
  "related_laws": [{...}]           // オブジェクト配列
}
```

`max_tokens=8192` の制限内で Gemma が長い `topics` を書ききれず途中でストップしている可能性が高い。
あるいは `topics` のキー名混乱（key_topics と topics が紛らわしい）で空配列を返している可能性も。

### 改善案

**Step 6b を 3 個の独立した LLM 呼び出しに分割**：

| ステップ | 出力 | スキーマの規模 |
|---------|------|---------------|
| 6b-1 (summary) | `session_summary`（文字列） | 〜 500 字 |
| 6b-2 (topics) | `key_topics` + `topics`（広域＋詳細） | 〜 5 トピック |
| 6b-3 (commitments) | `key_commitments` | 〜 10 項目 |

加えて `related_laws` は [09-law-tagging.md](09-law-tagging.md) で別ステップ化を提案。

詳細プロンプト設計の議論は [11-prompts-and-models.md](11-prompts-and-models.md) を参照。

---

### B. `key_topics`（summary 側）と `topics.name`（topics 側）が同じセッションで違う語彙

**観測**：56149_本会議（4/9）：

```
key_topics:
  健康保険法改正案の趣旨と持続可能な社会保障
  OTC類似薬の保険給付見直しと患者への配慮
  出産費用の現物給付化と周産期医療体制の維持
  高額療養費制度の所得区分見直しとセーフティーネット
  後期高齢者医療における応能負担（金融所得の反映）
  中東情勢に伴う医療物資の安定供給確保
  医療現場のDX推進と業務効率化支援

topics names:
  医療保険制度の持続可能性と負担の適正化
  周産期医療体制の整備と出産・妊婦支援
  OTC類似薬の保険適用見直しと患者負担
  医療現場のDX推進と業務効率化
  医療物資の安定供給と経済安全保障
  健康づくりと福祉的アプローチ
  少子化対策と子育て政策の審議体制
```

7 個ずつあるが、**同じテーマでも語彙が違う**：
- 「OTC類似薬の保険給付見直しと患者への配慮」 vs 「OTC類似薬の保険適用見直しと患者負担」
- 「医療現場のDX推進と業務効率化支援」 vs 「医療現場のDX推進と業務効率化」

LLM が **同じ Step の中で同じ概念を 2 回別々に名付けている**。
トピック単位の集計（site/dashboard 側）が壊れる。

### 改善案

- 単一 LLM 呼び出しで「**同じ trim 名のトピックを内部で 2 通り作らない**」を強制する
  プロンプト
- 構造的には `topics[i].name` と `key_topics` を **重複させない**：`key_topics` は
  `topics[i].name` のサブセットだけを保持する（参照型）

これが UI/UX レビュー
[02-cross-cutting-issues.md](../uiux-review/02-cross-cutting-issues.md) で指摘された
「広域トピック vs 狭域トピック」問題と同根。

---

### C. `topics.related_qa_ids` が空のトピックが多い

**観測**: トピック合計のうち、`related_qa_ids: []` のトピックが多数。
特に `qa_pairs.pairs == []` のセッション（22 件）では 100% 空。

例: `56114_原子力特別委員会/topics.json`：
```json
{
  "name": "震災復興と原子力防災",
  "description": "震災復興の進捗と原子力防災体制の強化に関する議論。",
  "related_qa_ids": []  ← qa_pairs.pairs が空
}
```

トピックは生成されているが、それを支える Q&A が無い。
**トピックの根拠が空**ということは、サイトでクリックしても何も出てこない。

### 改善案

- `qa_pairs.pairs == []` のセッションでは `topics.json` を生成しない（または別スキーマで生成）
- `related_qa_ids: []` のトピックは出力時に drop
- トピックは「Q&A ペアから派生する」契約を明確にする

---

### D. `related_qa_ids` が存在しない qa_id を参照する可能性

**観測**: 56149_本会議 では `topics[].related_qa_ids` の和集合が `pairs[].id` と一致していた。
しかしこれは **LLM がたまたま正しく書けた** だけで、保証は無い。

`structurer.py:683-684` で qa_pairs 一覧を LLM に渡す形式：

```python
qa_text = "\n".join(
    f"[{p.id}] トピック: {p.topic}\n  質問者: ...\n  回答要旨: {p.answer.summary}"
    for p in qa_pairs.pairs
)
```

LLM はこの ID 文字列をプロンプトから読み取って `related_qa_ids` に書き込む必要がある。
ID が `qa_001`〜`qa_042` のように連番なら混乱しないが、長いセッションではエラーが起きうる。

### 改善案

- 出力後 `topics[].related_qa_ids` を validate し、存在しない qa_id は除去
- もしくは LLM に index（`0, 1, 2, ...`）を返させてコード側で qa_id にマップ
  （Step 6a と同じ方針）

---

### E. `key_commitments` の質が低い

**観測**: 実データを眺めると、`key_commitments[].text` が
「適切に検討してまいります」「真摯に受け止めて対応します」といった
**具体性のないコミットメント**を拾っているケースがある。

これは Step 6a の `commitment_text` 問題（[06-qa-extraction.md §F](06-qa-extraction.md#g-has_commitment--commitment_text-の整合性)）と同根。
`generate_summary_and_topics` は qa_pairs から `key_commitments` を抽出するので、
入力の質が低ければ出力も低い。

### 改善案

- Step 6a で `commitment_strength` を導入し、`specific` のみを `key_commitments` に通す
- もしくは `key_commitments` 用に独立したプロンプトで「期日 / 数量 / 具体的行動を含むもののみ」と
  強制

---

### F. `session_summary` の長さが揃わない

**観測**: `session_summary` の文字数を集計すると、

- 平均 200 字程度
- 短いもの 50 字、長いもの 600 字

サイト一覧で表示する場合、長さがバラバラだと UX が悪化する。

### 改善案

プロンプトで「3〜5 文、各文 60〜100 字」のような制約を強める。
あるいは `summary_short`（一覧用、80 字）と `summary_long`（詳細ページ用、300 字）の
2 種を生成する。

## 7.3 改善案サマリー

- [ ] **[P0]** Step 6b を 3 LLM 呼び出しに分割
- [ ] **[P0]** `qa_pairs == []` のセッションでは `topics.json` 生成をスキップ
- [ ] **[P0]** `key_topics` を `topics[].name` のサブセットとして再定義
- [ ] **[P1]** `topics[].related_qa_ids` を validate し、無効 ID を除去
- [ ] **[P1]** `key_commitments` に `commitment_strength` を導入
- [ ] **[P2]** `session_summary` の長さを制約（一覧用と詳細用に分割）
