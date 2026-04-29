# 06. Q&A ペア抽出（Step 6a: qa_pairs.json）

## 6.1 設計の良いところ

- **`sentence_indices` ベースの組み立て**（`structurer.py:46-50`）：
  LLM に `full_text` を返させずに、文番号配列だけ返させてコード側で結合する。
  捏造耐性が高く、トークン消費も抑えられる。**LLM 構造化の手本のような設計**。
- **委員長指名で質疑ブロックを分割**（`structurer.py:299-396`）：
  1 セグメント内に複数質疑者がいるパターン（複数会派の代表質問が連続する本会議）を
  ブロック分割してから個別に LLM に渡す。これは現実の議事構造に合っている。
- **議員 → 大臣の答弁者解決**（`structurer.py:_resolve_answerer_from_sentences` 251-294）：
  「議員が答弁者」というありえない結果を検出して、同じ範囲内の非議員に置き換える防御。
  これも正しい設計判断。
- **fuzzy lookup**（`_fuzzy_lookup` 182-203）：完全一致 → 姓一致でカバー範囲を拡大。
  ただし [05-speaker-tagging.md §5.2.E](05-speaker-tagging.md#e-1-文字姓の議員が混同される林森原など) の通り、
  同姓複数議員の取り違え可能性あり。

## 6.2 観測されている問題

### A. 答弁が空のペアが大量に生成される（217 件）

**観測**：

```bash
$ find data/shugiin -name qa_pairs.json -exec jq -r '.pairs[] | select((.answer.full_text | length) < 5) | .answer.evasion_score' {} \; | sort | uniq -c
    217 1.0
      1 0.0
```

例: `data/shugiin/2026/03/13/56124_本会議/qa_pairs.json` の qa_001〜qa_021：

```json
{
  "id": "qa_002",
  "topic": "物価高騰対策と予算の組み替え提案",
  "question": {"speaker": "...", "full_text": "イラン情勢に伴い..."},
  "answer": {"speaker": "", "role": "", "full_text": "", "evasion_score": 1.0, "has_commitment": false}
}
```

これは討論セッションで答弁者が一人も発言していないのに、Step 6a が無理に Q&A 化したもの。

### 影響

- ダッシュボードの「回避度ランキング」が破綻
  （[01-overview.md §1.2](01-overview.md#top-1) と直結）
- 質問者の発言を「最大回避された質問」として晒すリスク

### 根本原因

- `_is_qa_segment`（`structurer.py:399-415`）は「答弁者ロールが含まれる」を OR 条件で
  ゆるく判定するため、討論セッションでも qa 対象として通してしまう
- プロンプト（`structurer.py:40-81`）に「答弁が無いものはペアにしない」というルールが無い
- リトライ機構（`structurer.py:531-571`）が「ペア数が少ない＝ LLM 失敗」と判定して
  むしろ「無理にペアを増やす」方向に動く

### 改善案

複数層の防御：

1. **Step 6a 入力フィルタ**: セッション種別が `floor_speech` なら全体を Q&A 抽出スキップ。
2. **Step 6a プロンプト追記**: 「answer の sentence_indices が空、または answer.full_text が
   30 字未満になるペアは出力しない」と明示。
3. **Step 6a 出力後フィルタ**: `_extract_pairs_from_response` で
   `len(a_full_text) < 30 and len(a_indices) == 0` のペアを drop。
4. **密度リトライの抑制**: `floor_speech` または `representative_questions` セッションでは
   `_MIN_QA_DENSITY` チェックを無効化。

---

### B. 質問テキストが極端に短いペアが 44 件

**観測**：`question.full_text < 20 字` が 44 件。例：

```json
{
  "id": "qa_001",
  "topic": "健康保険法等の一部を改正する法律案の趣旨",
  "question": {"full_text": "趣旨の説明を求めます。"},
  "answer": {"full_text": "ただいま議題となりました健康保険法等の一部を改正する法律案につきまして..."}
}
```

これは本会議冒頭の **趣旨説明定型句** を質問として扱ったもの。
内容的には「質疑応答」ではなく「趣旨説明」（一方向の情報提供）。
[02-cross-cutting-issues.md §2.1](02-cross-cutting-issues.md#21-セッション種別が一級概念になっていない)
のセッション種別問題と同じ根。

**改善案**: セッション種別 `representative_questions` の冒頭セグメントを
`floor_speech_introduction` として別扱いするか、`question.full_text < 20 字` を
出力時に drop。

---

### C. topic の粒度がセッション・議員・テーマで不揃い

**観測**：`qa_pairs.json` の topic フィールドを集計すると 6,308 ペア中、
**重複は数件のみ**で、ほぼ全ペアが unique なトピック名を持つ。

```
3 高額療養費制度の見直し
2 重要情報活動と外国情報活動への対処の定義
2 設備投資促進税制の政策効果検証
... (ほぼ全て 1 件)
```

これは UI/UX レビュー [02-cross-cutting-issues.md](../uiux-review/02-cross-cutting-issues.md) で
指摘された **「広域トピック vs 狭域トピック」問題** の根本原因。

`structurer.py:42` のプロンプト：

```
重要なルール:
- 質疑者が複数のテーマについて質問した場合、テーマごとに別のQ&Aペアを作成すること
- 1つも漏らさずに抽出すること
```

「テーマごとに別ペア」を強調するため、LLM はトピック名を狭く具体的に書こうとする。
結果として「**OTC類似薬の保険給付見直しと患者負担増加**」のような長く具体的な topic が
生成され、セッションを跨いで集約できない。

**改善案**: トピック粒度を 2 レイヤに：

```json
{
  "topic": "OTC類似薬の保険給付見直しと患者負担増加",  // 狭域（既存）
  "broad_topic": "医療保険制度",                            // 広域（新規）
  ...
}
```

`broad_topic` は事前定義の Closed vocabulary（30 個程度）から LLM に選ばせる。
セッションをまたいで集約可能になり、サイトの「分野別」フィルタが機能する。

[09-law-tagging.md](09-law-tagging.md) の関連法案タグも、この `broad_topic` と組み合わせれば
精度が上がる。

---

### D. answer.speaker が空のペアが 218 件（3.4%）

**観測**：

```bash
$ find data/shugiin -name qa_pairs.json -exec jq '[.pairs[] | select(.answer.speaker == "")] | length' {} \; | awk '{s+=$1} END{print s}'
218
```

ほぼすべて `answer.full_text` も空のペアと重なる（カテゴリ A）。

`structurer.py:_resolve_answerer_from_sentences` が空 indices を受けたとき：

```python
if not valid:
    return "", ""
```

を返すので、speaker と role が両方空に。

このまま `qa_pairs.json` に書き出すのは契約違反気味。
**そもそも答弁が無いペアを生成しない**ことで連動して解消する。

---

### E. 答弁の重複（同一テキストが複数ペアに入る）

**観測**: `data/shugiin/2026/03/13/56127_財務金融委員会/qa_pairs.json` 等で
`answer.full_text` の完全一致重複が 2 件発生（10 セッション程度で同様の重複）。

LLM が同じ答弁を異なる質問に紐付けて 2 つの Q&A ペアとして返している。
重複 31 字以上テキストでカウントすると 9〜10 セッションで発生。

### 影響

- 答弁の集計（`evasion_score` の議員別平均など）でダブルカウント
- サイト閲覧時に「同じ答弁が違うトピックで 2 回出る」違和感

### 改善案

- `_extract_pairs_from_response` でセグメント内の `a_indices` の overlap 率を計算し、
  90% 以上重複するペアは「フォローアップ」として `follow_up_ids` に紐付けて 1 ペアにマージ
- LLM に対して 「**同じ答弁を 2 回返さない**」を明示

---

### F. `intent` の分布偏り

**観測**: `intent` フィールドは 5 値の enum：

```python
fact_check / policy_proposal / accountability / information_request / other
```

実データで集計すると：

```
information_request: 約 60%
accountability:      約 25%
fact_check:          約 10%
policy_proposal:     約 4%
other:               約 1%
```

`information_request` が 6 割を占めており、識別力が低い。
LLM は「具体性のある質問は全部 information_request」と判定しがち。

**改善案**:
- intent の値を見直す。例: `factual_query / position_clarification / oversight / proposal / declaration / other`
- もしくは「question_type」と「primary_intent」の 2 軸に分ける
- 現状の `information_request` は意味的に弱いラベル。サイト側で活用しづらい

---

### G. `has_commitment` / `commitment_text` の整合性

**観測**: 大規模な集計をしたが、`has_commitment=true` でも `commitment_text` が
要約文（answer.summary 由来）になっているケースが多い。

実例（推定）：
```json
{
  "has_commitment": true,
  "commitment_text": "適切に検討してまいります。"  // ← これは「検討する」と言っただけで commitment ではない
}
```

`commitment_text` には「いつまでに何をする」という具体性が必要だが、LLM はそこまで判定できていない。

### 改善案
- プロンプトに「commitment_text は具体的な期日・行動を含むこと。一般論の表明は has_commitment=false」を強調
- LLM 単独では判定が難しいので、`commitment_strength: "specific" | "vague" | "none"` のような
  3 値に拡張する
- ダッシュボードの「約束トラッカー」が実用にならない（UI/UX レビュー
  [04-dashboard.md](../uiux-review/04-dashboard.md) と直結）原因の 1 つ

---

## 6.3 改善案サマリー

- [ ] **[P0]** 答弁テキスト 30 字未満のペアを生成・出力時に drop
- [ ] **[P0]** セッション種別と連動させ `floor_speech` では Step 6a スキップ
- [ ] **[P0]** `broad_topic` フィールドを Closed vocabulary で追加
- [ ] **[P1]** 密度リトライをセッション種別で抑制
- [ ] **[P1]** answer.full_text の重複検出・マージ
- [ ] **[P1]** `commitment_strength: 3 値` への拡張、プロンプトで具体性を要求
- [ ] **[P2]** intent enum の見直し（識別力を持たせる）
- [ ] **[P2]** Q&A ID をセッション横断ユニーク（`{session_id}-qa_NNN`）に
