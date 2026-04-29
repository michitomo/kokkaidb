# 09. 関連法案タグ（related_laws）の網羅性

## 9.1 設計の良いところ

- **`laws.json` を事前ビルド**（`laws_builder.py`）：CLB と Gian の 2 つの公式ソースから
  diet_session を絞って取得し、重複排除する。**人手介入なしの再現可能ビルド**。
- **`laws_compact.txt` という LLM 向けフォーマット**を別途生成：1 行 1 法案で law_id と
  タイトル・提出理由（200 字に切り詰め）を載せる。LLM プロンプトに丸ごと注入できる。
- **法案 ID を `law_001` のような連番**にしている（`laws_builder.py:85`）：CLB の `clb-5149` 型 ID は
  人間/LLM ともに読みにくいので、`laws_compact.txt` のスコープ内で連番に振り直すのは妥当。
  ただし `laws.json` の方は元 ID を保持しているのでミスマッチ（後述）。

## 9.2 観測されている問題

### A. 関連法案タグが全くついていないセッションが 67%（94/140）

```bash
$ find data/shugiin -name summary.json -exec jq '.related_laws | length' {} \; | sort | uniq -c
     94 0   ← 67%
     15 1
     20 2
      6 3
      3 4
      2 5
```

法案直接審議のセッションでも 0〜2 件にとどまる：

| ファイル | related_laws 数 | session_summary（冒頭）|
|---------|----------------|---------------------|
| 56142_厚生労働委員会 (4/3) | **0** | 「健康保険法」明記 |
| 56159_厚生労働委員会 (4/10) | **0** | 「医療・介護制度」議論 |
| 56174_厚生労働委員会 (4/15) | 1 | 「健康保険法等の一部を改正する法律案」明記 |
| 56189_厚生労働委員会 (4/17) | 2 | 「健康保険法」明記 |
| 56196_厚生労働委員会 (4/22) | 2 | 「健康保険法」明記 |
| 56194_厚生労働委員会 (4/21) | 2 | 「健康保険法」明記 |
| 56209_厚生労働委員会 (4/24) | 2 | 「健康保険法」明記 |
| 56142_厚生労働委員会 (4/3) | **0** | 「労働者災害補償保険法」議論 |

**全部 1〜2 件しか付いていない**のは異常。
本会議の代表質問で 7 法案が議論されているケースもあるはず。

### B. 原因の推察

1. **プロンプトの保守性が高すぎる**：`structurer.py:122`
   ```
   - 確信度が低いものは含めない（明らかに関連するもののみ）
   ```
   この「確信度が低いものは含めない」が強すぎて、LLM が conservative すぎる出力をする。

2. **75 件の法案を一度に注入するのが多すぎる**：`laws_compact.txt` は現在 75 行。
   LLM はその中から「明らかに関連するもの」を選ぶので、検索範囲が広い分、保守的になる。

3. **`law_id` 形式の不一致**：`laws_compact.txt` は `law_001` 形式だが、`laws.json` の
   `id` は `clb-5149` 形式。site/scripts/generate-api.ts でどちらの ID を最終 API に
   埋め込んでいるかによって、site と LLM 出力の橋渡しが壊れている可能性がある。
   実際 `site/public/api/laws.json` を見ると `id: "law_001"` 形式なので、LLM 出力と一致する
   ように調整されているが、内部の二重 ID 管理が混乱を生む。

4. **同一セッションで Step 6a と Step 6b が分離している**：Step 6a は qa_pairs を生成、
   Step 6b は qa_pairs を読んで関連法案を判定。**Step 6b の入力には qa_pairs.summary しか含まれない**
   （`structurer.py:683-685`）。詳細な full_text や sentence は失われているので、
   関連法案を見つけるのに必要な「具体的な法案名の言及」が見えない。

### 改善案

**(1) 関連法案タグを Step 6c として独立**

Step 6a の qa_pairs と元の utterances から、各 Q&A ペアごとに関連法案を判定：

```python
def tag_laws_per_pair(qa_pair: QAPair, utterances: SegmentUtterances, laws_text: str) -> list[str]:
    # qa_pair.question.full_text + qa_pair.answer.full_text + 周辺 utterances を入力
    # 「この Q&A は law_001..law_075 のどれと関連するか」を聞く
```

ペア単位で問い合わせれば、LLM は限定された範囲（1 ペアの内容）から関連法案を選ぶので、
精度が上がる。コストは増えるが（6,308 ペア × 1 LLM call ≒ 6,308 calls）、
DeepInfra の Gemma レート ($0.10/M token) で全体 10 ドル以下に収まる。

**(2) 法案リストを 2 段階フィルタする**

委員会別に法案を予選すれば、LLM の選択肢が大幅に減る。
例: 厚生労働委員会セッションでは、所管省庁が「厚生労働省」または submitter が
「厚生労働省」の法案 14 件のみを LLM プロンプトに注入する。

これは `laws.json` の `submitter` と `metadata.committee` を join するだけ：

```python
def get_relevant_laws(committee: str, all_laws: list[Bill]) -> list[Bill]:
    committee_to_ministry = {
        "厚生労働委員会": ["厚生労働省"],
        "財務金融委員会": ["財務省", "金融庁"],
        ...
    }
    ministries = committee_to_ministry.get(committee, [])
    return [b for b in all_laws if b.submitter in ministries] or all_laws
```

委員会と所管省庁が必ずしも 1 対 1 ではないので、マッチしない場合は全リストにフォールバック。

**(3) プロンプトの「確信度」表現を緩める**

`structurer.py:122` を：
```
- 法案名がtopicに含まれる場合だけでなく、質疑の内容・文脈から関連する法案を幅広く判断する
- 確信度が低いものは含めない（明らかに関連するもののみ）
```
↓
```
- 法案名が topic、question.summary、answer.summary に **明示的または暗黙的に** 含まれる場合、
  関連法案として登録する
- 「言及されているが、議論の中心ではない」場合も登録する（後段でフィルタする）
```

LLM 段階では recall を上げ、後段（site 側 or QA レビュー）で precision を整える。

**(4) qa_id 単位でなくセッション単位に集約しているのを見直す**

現状 `summary.related_laws[].qa_ids` は「このセッション全体でその法案に言及している qa」。
**Q&A ペアごとに `related_law_ids` フィールドを追加**する方が、サイトのフィルタも
分析もしやすい：

```json
{
  "id": "qa_005",
  ...
  "related_law_ids": ["law_026", "law_028"]
}
```

`summary.related_laws` は集計ビューとしてサイト側で派生させれば良い。

---

### C. `laws_compact.txt` のサイズが大きい

```bash
$ wc -c data/laws/laws_compact.txt
35821  # 約 36KB
```

75 法案 × 平均 480 字 ≒ 36KB。`generate_summary_and_topics` のプロンプト全体に
これが追加されるので、入力 token は約 12,000 token 増える。
`max_tokens=8192` は **入力ではなく出力** の制限なので問題ないが、料金的には増える。
2 段階フィルタで 14 件に絞れば 6,000 tokens 削減できる。

---

### D. 法案の状態（`status: "成立"`）が全く活用されていない

`laws.json` には `status: "成立"|"審議中"|"廃案"` のような状態が入っているが、
LLM プロンプトには注入されていない。

**改善案**: 「成立した法案」と「審議中の法案」を分けて見せる。
サイトのフィルタでも「審議中の法案」だけを表示する選択肢が欲しい
（UI/UX レビュー [10-future-features.md](../uiux-review/10-future-features.md) の「審議中法案ウォッチ」と接続）。

---

## 9.3 改善案サマリー

- [ ] **[P0]** 関連法案タグを Q&A ペア単位で生成（Step 6c 独立）
- [ ] **[P0]** 委員会 → 所管省庁マッピングで法案リストを予選
- [ ] **[P1]** プロンプトの保守性を緩め、recall を上げる
- [ ] **[P1]** `qa_pairs[].related_law_ids` フィールドを追加（既存の `summary.related_laws` は派生）
- [ ] **[P2]** 法案の `status` をプロンプトに含める＋サイトフィルタに反映
- [ ] **[P2]** `law_001` と `clb-5149` の二重 ID 管理を整理
