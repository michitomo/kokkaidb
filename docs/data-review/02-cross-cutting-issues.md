# 02. 横串の致命的問題

特定のステップではなくパイプライン全体に跨る問題、または複数ステップが連鎖して
失敗を引き起こすパターン。**ここでカバーする問題は、個別ステップで局所的に直しても
直らない**。アーキテクチャや責務分担の見直しが必要。

## 2.1 「セッション種別」が一級概念になっていない

### 観測

- `metadata.json` のスキーマ（`models.py:SessionDetail`）には `committee` / `session_number`
  しかなく、**そのセッションが何の議事をやっているか**を表す情報がない。
- 衆議院本会議だけでも実態は多種：
  - **趣旨説明 + 代表質問**（例: 56149_本会議, 4/9）→ 質疑応答ペアが成立する
  - **解任決議案の提案理由＋討論**（例: 56124_本会議, 3/13）→ 一方向の演説のみ
  - **法案の趣旨説明のみ**（例: 56132_本会議, 3/30）→ Q&A 構造なし
  - **採決のみ**（数分のセッション）
- どれも同じパイプラインを通っており、結果として後者 3 種は `qa_pairs.pairs=[]` になるか、
  もしくは無理矢理 Q&A 化されて「**質問テキストあり / 答弁テキスト空 / 回避度 1.0**」の
  ノイズペアを乱発する。

### 結果として現れる失敗

| 失敗モード | 件数 | 例 |
|-----------|------|-----|
| `qa_pairs=[]` | 22 セッション (15.7%) | 56142_厚生労働委員会(4/3), 56132_本会議(3/30) |
| 答弁空 + 回避度 1.0 のペア | 217 件 | 56124_本会議(3/13) qa_001〜qa_021 |
| `topics.json` 空 | 21 セッション (15%) | 56092_財務金融委員会(3/3), 56130_本会議(3/19) |

これら 3 つは原因が**同じ**：「Q&A 抽出が成立しない／意味のないセッション」を Step 6 で
無理に処理している。LLM が困って空・無意味な出力を返す。

### 改善案

- **`SessionDetail.session_kind` を追加**：
  - `regular_qa`（常任委員会の通常質疑、参考人を除く）
  - `representative_questions`（本会議の趣旨説明＋代表質問）
  - `floor_speech`（本会議の討論・決議案・所信表明、Q&A 構造なし）
  - `procedural`（採決・委員長選任など事務的）
  - `expert_hearing`（参考人質疑、Q&A は成立するが質問→答弁のフローが緩い）
- スクレイパー段階で **議事記録の見出し** から判定する（衆議院 TV のページに「趣旨説明」
  「討論」「採決」の文言が含まれている）。LLM 1 回 / セッションでも良い。
- パイプラインで `session_kind != "regular_qa"` のセッションでは Q&A 抽出をスキップし、
  代わりに `floor_speech_summary.json` のような別スキーマを生成する。

---

## 2.2 スクレイパーの委員会名抽出が壊れている

### 観測

5 セッションで `committee="不明"` が確定している：

```
data/shugiin/2026/04/22/56200_不明/
data/shugiin/2026/04/16/56183_不明/
data/shugiin/2026/04/09/56150_不明/
data/shugiin/2026/02/20/56083_不明/
data/shugiin/2026/04/23/56206_不明/
```

加えて `committee="特別委員会"`（修飾語抜けで具体名なし）が 4 セッション。
URL パスに `_不明` が出るのでサイト閲覧時に直接見える（例: `/shugiin/2026/04/22/56200_不明/`）。

### 原因

`scrapers/shugiin.py:212` の `_extract_session_metadata`：

```python
match = re.search(r"[一-鿿]+委員会", text)
```

ページに **`〇〇委員会`** という文字列が直接含まれていれば取れるが、
**`〇〇委員長`** しかないページでは正規表現が反応しない。

`56200_不明` の metadata.json を見ると：

```json
"speakers": [
  {
    "name": "山下貴司",
    "affiliation": "内閣委員長",
    ...
  }
]
```

「内閣委員長」のスピーカーが先頭にいるのに、委員会名は `不明`。
速記者の所属から `〇〇委員長` を `〇〇委員会` に変換すれば 100% 救えるはず。

### 改善案

スクレイパーの委員会名抽出を 3 段階フォールバックに：

```python
def _extract_committee(soup, speakers):
    # 1. ページ内の "〇〇委員会" パターン（既存）
    # 2. <title> 内の "本会議" など特殊カテゴリ
    # 3. NEW: speakers の affiliation 末尾が "委員長" "理事" の場合、
    #    "〇〇委員長" → "〇〇委員会" に変換して採用
    for sp in speakers:
        if sp.affiliation.endswith("委員長"):
            return sp.affiliation[:-3] + "委員会"
    # 4. それでも無ければ "不明"
```

これだけで 5/5 の `不明` セッションは復旧する見込み。同じく `特別委員会`
（具体名前置詞欠落）の 4 件は別途、`特別` の手前にプレフィックスを補う必要がある
（例: `災害対策特別委員会` の "災害対策" が抜けるパターン）。

---

## 2.3 `SpeakerInfo.role` が一切埋められていない

### 観測

```bash
$ find data/shugiin -name metadata.json | xargs jq -r '.speakers[].role' | sort | uniq -c
   1367  ""    # 空文字のみ
```

全 1367 名の speaker で `role=""`。

### 原因

`models.py:8` の `SpeakerInfo.role: str = ""`（デフォルト空文字）。
`scrapers/shugiin.py:_extract_speakers` は `role` を一切セットしない。

ところが下流の `speaker_tagger.py:117` ではこれを使っている：

```python
役割: {segment_speaker.role or "質疑者"}
```

つまり全員が「質疑者」扱いされてプロンプトに渡される。**委員長・大臣・政府参考人かどうかの
事前情報が LLM に届いていない**。これが Step 5 の役割誤分類の遠因の 1 つ。

### 改善案

スクレイパーの `_extract_speakers` で `affiliation` から自動派生する：

```python
def _derive_role(affiliation: str) -> str:
    if affiliation.endswith("委員長"): return "委員長"
    if affiliation.endswith("議長") or affiliation.endswith("副議長"): return "委員長"  # 議事進行
    if "大臣" in affiliation: return "答弁者"
    if "局長" in affiliation or "部長" in affiliation or "審議官" in affiliation: return "政府参考人"
    if "参考人" in affiliation: return "参考人"
    if affiliation in _PARTY_KEYWORDS or any(p in affiliation for p in _PARTY_KEYWORDS):
        return "質疑者"
    return ""
```

これで `metadata.json` 段階で 90% 以上の speaker に正しい role が入り、
Step 5 のプロンプトに事前情報を渡せる。

---

## 2.4 「答弁が無いものを Q&A ペアにしてしまう」失敗の連鎖

### 観測

`evasion_score == 1.0` のペアは **249 件**。その内 **217 件（87%）が answer.full_text 5 字未満**。

```bash
$ find data/shugiin -name qa_pairs.json -exec jq -r '.pairs[] | select((.answer.full_text | length) < 5) | .answer.evasion_score' {} \; | sort | uniq -c
    217 1.0
      1 0.0
```

ほぼ全件が「答弁が無い」のに「最大回避度」をつけられている。
`structurer.py:80` のプロンプト記述：

```
evasion_scoreの目安:
- 0.9-1.0: 完全に回避、「答えられない」等
```

これに引きずられて LLM が「答弁本文が空 ≒ 完全回避」と短絡している。

### 影響

- ダッシュボードの「回避度ランキング」が破綻（`docs/uiux-review/05-evasion-score.md` の指摘と
  直結）。
- 質問者の発言を「最大回避された質問」として晒してしまう。**メディアに引用されたら
  名誉毀損リスク**がある。
- `qa_pairs.json` のフィルタ機能で「回避度 0.9 以上」を選ぶと、9 割がノイズ。

### 改善案

複数層での対策が望ましい：

1. **生成時点での破棄**：`structurer.py:_extract_pairs_from_response` で
   `len(a_full_text) < 30 and a_indices == []` のペアを drop。**質問しか書かれていないペアは
   そもそも Q&A ペアではない**。
2. **プロンプトのルール追加**：
   `「答弁が含まれていない発言（質問・演説のみ）からは Q&A ペアを作らない」`
   を `QA_SEGMENT_SYSTEM_PROMPT` の禁止事項に追加。
3. **`evasion_score` の前提条件**：プロンプトに
   `「answer.full_text が 30 字未満の場合は、そのペアを返さない」`
   を強く書く。LLM の癖として「フィールドを空で埋めてくる」傾向があるので、
   そもそもペアを返させない方が信頼できる。
4. **type=`no_answer` の別フィールド**：演説や所信表明の発言は `floor_speech` として
   別ファイルに保存する（[2.1 改善案](#21-セッション種別が一級概念になっていない) と統合）。

---

## 2.5 セッションごとに qa_id がリセットされる（横断 ID 不在）

### 観測

`qa_pairs.json` の `id` は `qa_001`, `qa_002`, ... とセッション内連番。
セッションをまたぐと **必ず重複する**。

例えば、`56149_本会議/qa_001` と `56150_不明/qa_001` は別物だが ID が同じ。
ダッシュボードや一覧で「Q&A をクロスセッションで参照／ブックマーク」ができない。

### 影響

- URL に Q&A の永続リンクを作るには `{chamber}/{date}/{session_id}/{qa_id}` の
  4-tuple が必要だが、site 側でそれを安定的に組み立てる契約が無い。
- Pagefind 等で Q&A 単位の検索結果リンクを生成しづらい
  （実際 `a797276 feat(search): index Q&A cards individually` でやっているが、
  その実装は session_id を URL に埋め込んでいる）。

### 改善案

**Q&A の "site-wide id" を導入する**。`{session_id}-qa_NNN` 形式にすれば、`qa_pairs.json` を
読み込むだけでグローバルにユニーク。`structurer.py:658` の id 付番ロジックを：

```python
pair.id = f"qa_{pair_counter:03d}"  # ローカル
```
↓
```python
pair.id = f"{session_id}-qa_{pair_counter:03d}"  # グローバル
```

互換性が必要ならば、ファイル内には従来形式を残し、`global_id` フィールドを追加する手もある。

---

## 2.6 構造化 LLM 呼び出しの "全部入り JSON" が事故源

### 観測

`structurer.py:665` の `generate_summary_and_topics` は **1 LLM 呼び出しで 5 種類の出力**を
要求している：

```json
{
  "session_summary": "...",
  "key_topics": [...],
  "key_commitments": [{...}],
  "topics": [{...}],
  "related_laws": [{...}]
}
```

`max_tokens=8192` の制約下で、Gemma が後段（`topics`, `related_laws`）を欠落させる事故が
頻発している（21/140 で `topics=[]`）。

### なぜ "全部入り" にしたのか（推察）

- `daa1321` のベンチマーク履歴を見ると、当初 DeepSeek-V3.2 を Step 6 全体に使っていたが、
  `9207913 perf: reduce LLM token usage in step 4.5 and step 6b` でトークン削減を狙って
  統合したと思われる。
- しかし削減対象は **入力プロンプト** の重複であって、**出力 JSON** の統合ではない。
  入出力のキャッシュヒット率と、出力スキーマの単純化はトレードオフではない。

### 改善案

**Step 6 を 3 つに分割する**：

| ステップ | 入力 | 出力 | モデル候補 |
|---------|------|------|-----------|
| 6a | `utterances.json`（セグメント単位） | `qa_pairs.json` | gemma-4-31B（現状維持）|
| 6b | `qa_pairs.json` | `summary.json`（session_summary, key_topics, key_commitments のみ） | gemma-4-31B 又は DeepSeek |
| 6c | `qa_pairs.json` + `laws_compact.txt` | `topics.json` + `related_laws` | gemma-4-31B（topic と law は同列の語彙タグ）|

それぞれ出力 JSON が 2KB〜4KB で 8192 token 内に収まる。詳細は
[07-summary-topics.md](07-summary-topics.md) と [11-prompts-and-models.md](11-prompts-and-models.md)。

---

## 改善案サマリー

- [ ] **[P0]** `SessionDetail.session_kind` を追加し、Step 6 を分岐させる
- [ ] **[P0]** スクレイパーで `affiliation` ベースの委員会名フォールバック
- [ ] **[P0]** スクレイパーで `SpeakerInfo.role` を必ず派生
- [ ] **[P0]** Step 6 を 3 LLM 呼び出しに分割
- [ ] **[P1]** 答弁空ペアは生成時点で破棄
- [ ] **[P1]** Q&A ID をセッション横断ユニークに
