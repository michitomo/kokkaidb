# 08. 発言者名・役職の正規化（横串）

## 8.1 問題の本質

`metadata.json` の `speakers[]` は衆議院TV から確定的に取得される ground truth。
**この name と affiliation を、下流ステップで一切変えてはいけない**はず。

ところが実際は：

- Step 4.5（校正）が発言冒頭に「（自由民主党・無所属の会）」と所属を加筆する
- Step 5（話者タグ）が `高市早苗` の代わりに `高市内閣総理大臣` を返す
- Step 6（構造化）が `林` という 1 文字姓だけを返して、コード側で fuzzy lookup した結果
  別人にマッチする

ground truth から派生したはずのデータが LLM 経由で **「別の表記」に変質**している。

## 8.2 観測されている表記揺れ（再掲・詳細）

`utterances.json` の `utterances[].speaker` を集計：

```
高市早苗:       399
高市内閣総理大臣: 21
高市早苗内閣総理大臣: 3
高市総理大臣:     1
高市:             2
                 ← 「高市」だけだと姓 1 文字マッチ依存

上野賢一郎:     171
上野厚生労働大臣: 126
上野厚労大臣:     2  ← 略称
上野大臣:         2
上野:             3

赤澤亮正:       179
赤澤大臣:        80
赤澤経済産業大臣:  5
赤澤国家公安委員長: 2  ← 役職誤認識
赤澤防災大臣:     1  ← 役職誤認識

茂木敏充:       151
茂木外務大臣:    52
茂木大臣:         9
茂木初等中等教育局長: 4 ← 役職完全に誤り
茂木敏充外務大臣:  1

林芳正:         130
林総務大臣:      33
林拓海:          37  ← 別人（自民党衆議院議員 林拓海）
林鉄兵:           7  ← 別人（または誤認識）
林水管理・国土保全局長: 5  ← 部署名を人名扱い

平口洋:          66
平口法務大臣:    25
平口大臣:         1
平口刑事局長:     1  ← 役職誤り（平口は法務大臣）
```

サイトの「発言者一覧」では同じ大臣が 3〜5 個の別カードとして表示される。
集計（発言時間、回避度平均など）が分散して、UI/UX レビュー
[04-dashboard.md](../uiux-review/04-dashboard.md) で指摘された
「発言者分析の 83% が `totalAnswers < 5`」の遠因の 1 つ。

## 8.3 役職表記揺れ

`role` フィールドの揺れ：

| 出現 | 件数 | 規約準拠 |
|------|------|--------|
| 質疑者 | 8117 | ✓ |
| 委員長 | 6549 | ✓ |
| 答弁者 | 4609 | ✓ |
| 政府参考人 | 1806 | ✓ |
| 参考人 | 495 | ✓ |
| その他 | 36 | ✓ |
| 法務大臣 | 8 | ✗ → 答弁者 |
| 厚生労働大臣 | 8 | ✗ |
| 文部科学大臣 | 6 | ✗ |
| 総務大臣 | 5 | ✗ |
| 農林水産大臣 | 3 | ✗ |
| 国土交通大臣 | 1 | ✗ |

合計 **31 件** で規約違反の `role` が出力されている。
影響範囲は限定的だが、Pydantic の `Literal` 型で防げる。

## 8.4 既存実装の問題点

### `_fuzzy_lookup` の決定性の欠如

`structurer.py:182-203`：

```python
def _fuzzy_lookup(name: str, speakers_lookup: dict[str, SpeakerInfo]) -> SpeakerInfo | None:
    if name in speakers_lookup:
        return speakers_lookup[name]
    best_match: SpeakerInfo | None = None
    best_prefix_len = 0
    for prefix_len in (2, 1, 3):
        ...
        prefix = name[:prefix_len]
        for key, info in speakers_lookup.items():
            if key.startswith(prefix) and prefix_len > best_prefix_len:
                best_match = info
                best_prefix_len = prefix_len
        if best_match is not None:
            return best_match
    return None
```

問題点：

1. **`prefix_len > best_prefix_len` の比較が `>=` でない**ので、同じ prefix_len で複数マッチした場合、
   **辞書 iteration order に依存して "最後にマッチしたもの"** ではなく "最初にマッチしたもの" が
   `best_match` になり続ける（`>` なので更新しない）。一見確定的に見えるが、`speakers_lookup`
   が dict なので Python 内部実装に依存。
2. **`for prefix_len in (2, 1, 3)`** の順序：2 文字優先、次に 1 文字（特定姓のみ）、最後に 3 文字。
   `林芳正` を 2 文字 `林芳` で探すと一致しない（speakers の key は `林芳正` なので
   `startswith("林芳")` は true）。実装は動くが、優先順位の意味が分かりにくい。
3. **同姓複数議員の検出ロジックがない**。例えば `林芳正` と `林拓海` が両方 speakers にいた場合、
   prefix_len=1, prefix=`林` で両方にマッチする。`>` 比較なので最初に見つかった方しか
   `best_match` に入らないが、それが「正しい林」かは保証されない。

### 改善案

```python
def _fuzzy_lookup(name: str, speakers_lookup: dict[str, SpeakerInfo]) -> tuple[SpeakerInfo | None, int]:
    """名前の解決を試みる。返り値は (matched, n_candidates)。

    n_candidates > 1 なら複数候補があり警告すべき。
    """
    if name in speakers_lookup:
        return speakers_lookup[name], 1

    # 全長一致 → 2 文字 → 3 文字 → 1 文字 の順
    for prefix_len in (None, 2, 3, 1):
        if prefix_len is None:
            continue
        if prefix_len == 1 and name[0] not in _SINGLE_CHAR_SURNAMES:
            continue
        prefix = name[:prefix_len]
        candidates = [info for key, info in speakers_lookup.items() if key.startswith(prefix)]
        if len(candidates) == 1:
            return candidates[0], 1
        if len(candidates) > 1:
            logger.warning("Ambiguous name '%s' (prefix=%s): %d candidates: %s",
                           name, prefix, len(candidates), [c.name for c in candidates])
            return candidates[0], len(candidates)  # 暫定: 先頭を返すが警告
    return None, 0
```

## 8.5 「正規化レイヤ」を新設すべき

現状、Step 4.5 / 5 / 6 がそれぞれ LLM に名前を出力させており、
**ground truth との差分検出と書き戻しがどこにも無い**。

提案: パイプラインに正規化フェーズを 2 箇所追加：

### Step 4.6（仮称: 正規化 in 校正テキスト）

`raw_transcript.json` の `text` フィールドに対して、speakers 一覧から派生する正規表現で
変換する：

```python
# 例
text = re.sub(r"高市総理(?:大臣)?", "高市早苗総理", text)
text = re.sub(r"上野(?:厚労|厚生労働)大臣", "上野賢一郎厚生労働大臣", text)
```

これは Whisper の生テキストではなく、**校正後** に行う方が安全（Whisper は時々
`高市早苗` を `高市三苗` のように誤認識するので、それは Step 4.5 で先に直されている前提）。

### Step 5.5（仮称: 正規化 in utterances）

`utterances.json` の `utterances[].speaker` と `role` に対して、
`metadata.json` の speakers と照合して書き戻す：

```python
def normalize_utterances(utt: UtterancesOutput, metadata: SessionDetail) -> UtterancesOutput:
    # 1. role の正規化（〇〇大臣 → 答弁者 など）
    # 2. speaker 名の正規化（fuzzy lookup → 必ず metadata.speakers の name に戻す）
    ...
```

このレイヤを通せば、`utterances.json` の speaker 名は **必ず metadata.speakers のいずれか** に
正規化される（マッチしないものは raw 名を保持し、`unmatched: true` フラグを立てる）。

## 8.6 改善案サマリー

- [ ] **[P0]** Step 5.5（utterances 正規化）を新設
- [ ] **[P0]** `_fuzzy_lookup` の曖昧マッチを警告ログ化
- [ ] **[P0]** Pydantic `Literal[...]` 型で `role` の値を強制
- [ ] **[P1]** Step 4.6（raw_transcript 正規化）を追加（任意、効果未測定）
- [ ] **[P1]** Step 5 のプロンプトに「フルネーム必須・metadata の表記を使う」を追記
- [ ] **[P2]** 同姓複数議員の事前検出ヘルパーを `metadata.json` 段階で計算しておく
      （別途 `_ambiguous_surnames` フィールド）
- [ ] **[P2]** サイト側で発言者集計するときに、表記揺れを `metadata.speakers.name` で
      クラスタリングする（バックフィルとして）
