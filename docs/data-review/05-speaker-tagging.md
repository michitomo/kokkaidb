# 05. 話者交代検出（Step 5: utterances.json）

## 5.1 設計の良いところ

- **LLM に「文番号 + 話者名」だけ返させる設計**（`speaker_tagger.py:50-64`）：
  ```json
  {"splits": [{"start": 0, "speaker": "高市早苗", "role": "答弁者"}, ...]}
  ```
  本文を返させないので、トークン消費・捏造・タイポリスクが低い。**Step 5 の核となる
  正しい設計判断**。
- **委員長指名と質疑者発言を区別するプロンプト記述**（`speaker_tagger.py:42-48`）：
  「委員長は短く呼びかけ、その後の政策質問は質疑者本人」と明示。
- **`splits[0].start != 0` の自動補正**（`speaker_tagger.py:158-164`）：
  LLM が漏らしても安全側に倒れる。

## 5.2 観測されている問題

### A. 役割（role）の値が規約違反

**観測**：プロンプト（`speaker_tagger.py:37`）で `role` の値を
`委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他` の 6 種に限定しているが、
実データでは：

```
質疑者:       8117
委員長:       6549
答弁者:       4609
政府参考人:   1806
参考人:        495
その他:         36
法務大臣:        8 ← 規約違反
厚生労働大臣:    8
文部科学大臣:    6
総務大臣:        5
農林水産大臣:    3
国土交通大臣:    1
```

合計 **31 件で `role=〇〇大臣`** という規約外の値。少数だが、

- `structurer.py:_is_qa_segment`（399-415）の判定が `role` を使うので、
  `〇〇大臣` を持つセグメントは「答弁者ロールが無い」と判定されて Q&A 抽出から漏れうる。
- サイト側のフィルタが 6 値前提だと表示されない。

**改善案**：
- LLM 出力後に正規化レイヤを挟む（`speaker_tagger.py` 内）：
  ```python
  if role.endswith("大臣") or role.endswith("長官"):
      role = "答弁者"
  if role.endswith("局長") or role.endswith("審議官") or role.endswith("部長"):
      role = "政府参考人"
  if role.endswith("委員長") or role.endswith("議長"):
      role = "委員長"
  ```
  これは「役職の正規化レイヤ」として独立させるべき（[08-name-normalization.md](08-name-normalization.md)）。
- もしくは Pydantic で `Literal[...]` 型にして、規約外の値はパース時にエラーにする。

### B. 話者交代を検出できない（1 セグメント = 1 utterance）セッションがある

**観測**：以下のセッションで全セグメントの 30%以上が単一 utterance：

| セッション | 単一 utterance / 全 segments | 比率 |
|-----------|-----------------------------|------|
| 56124_本会議 (3/13) | 10 / 27 | 37% |
| 56117_外務委員会 (3/11) | 6 / 10 | 60% |
| 56125_外務委員会 (3/13) | 1 / 1 | 100% |
| 56090_議院運営委員会 (3/3) | 3 / 9 | 33% |

`56125_外務委員会` は 1 segment / 1 utterance のミニセッション（國場幸之助のみ）。
これは正しい結果だが、**Q&A 抽出に意味のあるセッションでは無い**ので
スキップ判定（[02-cross-cutting-issues.md §2.1](02-cross-cutting-issues.md#21-セッション種別が一級概念になっていない)）が必要。

`56124_本会議` は討論なので **本来 1 セグメント = 1 発言が正しい**。Step 5 は実は正しく動いている。
問題は Step 6 がこれを Q&A として扱おうとすること。

`56117_外務委員会` は質疑応答セッションのはずなので **Step 5 が話者交代を検出できていない**
可能性がある。`raw_transcript.json` で答弁者の発言が少ない（質疑者の長いブロックの後の答弁を
Whisper が拾えていない、または校正で削られた）ことが疑われる。

### C. 委員長指名のテキストが utterance に残ったままになる

**観測**：プロンプト（`speaker_tagger.py:42-48`）は委員長指名を別 utterance に切り出すよう
指示しているが、実データには：

- 「〇〇君。」（1 文）だけの委員長 utterance が大量にある（6549 件中の相当数）。

これは設計通りだが、サイト側で「発言全文タイムライン」に
**「(委員長) 高階恵美子君。」** のような 1 行ノイズが大量に並ぶ原因。
UI/UX レビュー [07-session-detail.md](../uiux-review/07-session-detail.md) でも指摘されている。

**改善案**：

- データ保存はそのまま（情報が消えると再現不能になる）。
- サイト側で `utterance.role == "委員長" && utterance.text.length < 30` のものを
  自動折りたたみにする。
- または `utterance.kind: "nomination" | "speech" | "procedural"` のタグを付ける。
  Step 5 の段階で `_CHAIR_NOMINATION_RE` を使えば容易に判定できる。

### D. 「答弁者」がフォールバックで誤判定されることがある

**観測**：`structurer.py:_resolve_answerer_from_sentences`（251-294）では、
LLM が「答弁者」として議員（自民党所属の議員）を返した場合に、同じセンテンス範囲で
非議員の発言者を探して入れ替える。これは正しい防御だが、ログに警告が出るだけで
「無理矢理代替を返す」ことはしないので、結果として議員が答弁者に残る。

ベンチマーク（`benchmark2.log:33`）では：

```
REF: [('森英介', '委員長'), ('上野賢一郎', '答弁者'), ('森英介', '委員長')]
gpt-oss: [('質問者', '質疑者'), ('上野賢一郎', '答弁者'), ('森英介', '委員長')]  ← '質問者' という空名前
DeepSeek: [('高階恵美子', '質疑者'), ('森英介', '委員長'), ('上野賢一郎', '答弁者')]  ← 高階を質疑者として加筆
gemma: [('森英介', '委員長'), ('上野賢一郎', '答弁者'), ('森英介', '委員長')]  ← REF と一致
```

DeepSeek（現行 Step 5 モデル）は文脈にいない発言者を加筆する癖がある。
Gemma の方が Step 5 では精度が高そう。

### E. 1 文字姓の議員が混同される（林・森・原など）

`structurer.py:179` の `_SINGLE_CHAR_SURNAMES`：

```python
_SINGLE_CHAR_SURNAMES = {"林", "森", "原", "関", "堀", "岡", "辻", "塚", "柳", "萩", "菅", "泉", "馬"}
```

第 221 国会の発言者を集計すると：

| 姓プレフィックス | 別人とみられる名前数 | 例 |
|------------------|---------------------|------|
| 林 | 5 通り以上 | 林芳正(総務相), 林拓海, 林鉄兵, 林〇〇局長 など |
| 森 | 2 通り | 森英介(議長), 森山〇〇 |
| 原 | 数通り | 原口一博, 原田義昭 など |

`_fuzzy_lookup` の実装：

```python
for prefix_len in (2, 1, 3):
    ...
    if prefix_len == 1 and name[0] not in _SINGLE_CHAR_SURNAMES:
        continue
    prefix = name[:prefix_len]
    for key, info in speakers_lookup.items():
        if key.startswith(prefix) and prefix_len > best_prefix_len:
            best_match = info
            best_prefix_len = prefix_len
    if best_match is not None:
        return best_match
```

**問題**: 同じ prefix_len で複数マッチがあった場合、`>` 比較なので「最後に発見した方」を返す。
辞書の iteration order に依存し、deterministic でない。

たとえばセッション内に `林芳正` と `林拓海` が両方いて、LLM が「林」とだけ返した場合、
どちらが選ばれるかは Python の dict 内部表現次第。

**改善案**：
- 1 文字マッチが複数候補になった場合は、`structurer.py` 側で警告ログを出す
- もしくは「速記者リストでの登場順が早い方」など決定的なルールに変更
- そもそも 1 文字マッチを廃止し、LLM が「林」とだけ返す挙動を Step 5 のプロンプトで
  禁止する（「フルネームを返してください」と明示）

### F. 同じ speaker が複数 segment にまたがるとセグメント間で表記揺れする

[01-overview.md §1.2 Top 4](01-overview.md#top-4-発言者名の表記揺れが-step-5-出力に持ち込まれている) と関連。
LLM はセグメントごとに独立に呼ばれるので、segment 1 では `高市早苗` と返し、
segment 5 では `高市総理大臣` と返すことが起きる。**セッション内で speaker name を**
**正規化するレイヤが今のパイプラインに無い**のが根本原因。

## 5.3 改善案

- [ ] **[P0]** Step 5 出力直後に役職正規化レイヤ（`〇〇大臣` → `答弁者`）を追加
- [ ] **[P0]** Step 5 出力直後に発言者名正規化レイヤ（`metadata.json` の speakers を ground truth）
- [ ] **[P1]** `_fuzzy_lookup` の単一文字マッチを deterministic に
- [ ] **[P1]** プロンプトに「フルネーム必須」「発言者リストにある表記をそのまま使う」を追記
- [ ] **[P1]** `Utterance` に `kind: "nomination" | "speech" | "procedural"` を追加し、
      Step 5 のプロンプトで判定させる
- [ ] **[P2]** ベンチマーク結果に基づき、Step 5 のモデルを Gemma に切り替えることを検討
      （DeepSeek の「加筆癖」を回避）
- [ ] **[P2]** `Pydantic` の `Literal[...]` 型で `role` を強制し、規約外の値はエラーに
