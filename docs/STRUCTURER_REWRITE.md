# Structurer 完全刷新計画 — utterance ベーススキーマへの移行

> **作成日**: 2026-05-10
> **ステータス**: 計画段階（実装前）
> **対象**: `kokkai-transcriber/src/structurer.py` および `src/prompts.py:QA_SEGMENT_SYSTEM_PROMPT`
> **影響範囲**: `qa_pairs.json` の `question.full_text` / `answer.full_text` の組み立てロジックと、それに依存する下流処理（summary, topics, key_commitments, law_tagging, metrics）

---

## ⚠️ 実装前提：全生成済みセッションの削除

**この計画を実装する前に、`data/shugiin/` および `data/sangiin/` 配下の生成済みセッションを全削除し、ゼロから再生成する**。

理由:
- スキーマ変更により旧データとの互換性が無くなる
- 既存データには既知の品質問題が複数存在しており（後述）、部分的なマイグレーションでは品質が揃わない
- 全データ再生成のコストは許容範囲（138セッション × DeepInfra 料金）

実行手順:
```bash
# バックアップ（必要なら）
cp -r data/ data.backup-2026-05-10/

# 全削除
rm -rf data/shugiin data/sangiin data/search-index
rm -f site/public/api/search-index.json

# 状態DBもリセット
rm kokkai-transcriber/state.db  # 必要に応じて

# 新パイプラインで再生成
cd kokkai-transcriber
python -m src.batch --chamber shugiin --since 2026-02-01 --workers 4
python -m src.batch --chamber sangiin --since 2026-02-01 --workers 4
```

---

## 1. 問題の背景

### 1.1 観測された症状

ユーザーから「Q&Aペアの答弁が途中で切れている」との指摘。具体例:

セッション `data/shugiin/2026/04/24/56209_厚生労働委員会` の qa_022（浜地雅一質問・田中雇用環境均等局長答弁）:

**正規の議事録での全文**:
> お答えいたします。年収の壁・支援強化パッケージの、先生御言及のありました対応策の一つとして実施をしておりましたキャリアアップ助成金です。社会保険適用時処遇改善コースということで実施をしておりましたが、その執行状況、令和六年度の支給額三十一・八億円となってございます。…（中略）…**この社会保険適用時処遇改善コースにつきましては令和三年度末で終了ということにいたしまして、壁を意識せず働いていただける環境づくりを一層支援するという観点から、令和七年七月にこれを拡充いたしまして、労働者一人当たり最大七十五万円を助成ということで制度を改善をしております。できる限り多くの企業にこの助成金を活用いただけますように、周知広報に一層取り組んでまいりたいと考えております**

**現状の `answer.full_text`**:
> 社会保険適用時処遇改善コースということで実施をしておりましたが、その執行状況、令和6年度の支給額31.8億円となってございます。…（中略）…この助成金につきましては、より多くの企業にご活用いただきたいというふうに考えております。

→ **冒頭の「お答えいたします。年収の壁支援強化パッケージの…キャリアアップ助成金です。」と、末尾の「令和3年度末で終了…令和7年7月に拡充…75万円を助成…周知広報に一層取り組んでまいりたい」が完全に欠落**している。

なお `utterances.json` には完全な発言が保存されている（Whisper・話者タグ付けは正常）。問題は `structurer.py` の Q&A ペア組み立て段階で発生している。

### 1.2 全データでの定量分析

衆議院138セッション・5,770ペアでの集計:

| 指標 | 数値 |
|--|--|
| 答弁の同一utterance内で末尾切れ | **21.1%**（1,220ペア） |
| 質問の同一utterance内で末尾切れ | **52.5%**（3,104ペア） |
| utteranceが1ペアにのみ属する | 38.1%（7,848件 / 20,580件） |
| utteranceが複数ペアに属する | **1.0%**（208件） — 代表質問・所信表明 |
| utteranceがどのペアにも属さない | 60.9%（≒委員長指名・点呼など手続き発言） |
| `_INPUT_CHAR_LIMIT=20000` で切り捨てられる長セグメント | 33セグメント |

### 1.3 根本原因

現状の設計:

1. `structurer.py` は LLM に **sentence_indices**（utterance内の文番号配列）を返させ、コードでその文を連結して `full_text` を組み立てる。
2. `prompts.py:QA_SEGMENT_SYSTEM_PROMPT` で **「挨拶・自己紹介・感謝は除外し、背景説明・問題提起は含める」** と明示指示している。
3. 入力プロンプトでは135個の文に逐一 `(N)` 番号を付与しており、長セグメントでは20000文字制限に引っかかる。

これにより:

- **設計通りの挙動**: 挨拶・前置きが `full_text` から除外される（プロンプトが指示している通り）
- **設計通りでないバグ**: LLM が「実質的内容」と「結論」の判別を誤り、本筋の答弁を途中で打ち切る（21〜52%）
- **副次的バグ**: 20000文字制限に達した長セグメントは末尾の発言が完全に LLM から見えなくなる

### 1.4 ユーザー要件の変化

> 基本的にはあいさつや前置きを含め、全ての発言がペアに登録されていて欲しいです。ただし、生成される要約にはそれを含んでほしくないです。

つまり:
- `full_text` には**挨拶・前置きを含む全発言**を入れたい
- `summary` は**実質的内容のみ**（現状通り）

これは、現状のプロンプト設計思想（「full_text からも挨拶を除外する」）とは逆向きの要件。設計レベルの方針転換が必要。

---

## 2. 採用する解決策：utterance ベーススキーマへの全面移行

### 2.1 設計原則

1. **utterance を質疑応答の最小単位とする**。utterance はもともと話者タグ付け済みで、1人の話者が連続して話した塊なので、Q&Aペアの自然な単位として整合する。
2. **`full_text` は LLM が組み立てない**。コードが `seg.utterances[i].text` を連結するだけ。LLM の判断ミスで途中欠落が原理的に起きない構造にする。
3. **`summary` は LLM が独立生成**（現状通り、プロンプトで「挨拶・背景不要」と指示済み）。
4. **複数ペアが共有する utterance（代表質問・所信表明、全体の1%）には sentence-level anchor で境界を明示**させる。

### 2.2 新スキーマ

LLM の Q&A 抽出レスポンス形式:

```json
{
  "pairs": [
    {
      "topic": "年収の壁支援強化パッケージの執行状況と評価",
      "question": {
        "utterance_indices": [12],
        "split_anchor_sentence_idx": null,
        "summary": "- 年収の壁支援強化パッケージの執行状況の確認\n- 106万の壁対策の評価",
        "intent": "information_request"
      },
      "answer": {
        "utterance_indices": [14],
        "split_anchor_sentence_idx": null,
        "summary": "- キャリアアップ助成金（社会保険適用時処遇改善コース）の支給額は令和6年度31.8億円\n- 令和7年7月に拡充し、労働者1人当たり最大75万円を助成\n- 周知広報に一層取り組む方針"
      }
    }
  ]
}
```

フィールド説明:

| フィールド | 必須 | 内容 |
|--|--|--|
| `utterance_indices` | ✓ | このペアの Q または A を構成する utterance 番号の配列。通常1個、まれに連続する複数。 |
| `split_anchor_sentence_idx` | △ | 同じ utterance を**他のペアと共有する**場合のみ設定。このペアが utterance 内のどの文から始まるかをグローバル sentence index で指定。99%のペアでは `null`。 |
| `summary` | ✓ | 「- 」箇条書き2〜4項目。挨拶・背景は不要（現状プロンプトと同じ方針）。 |
| `intent` | ✓ (Q側のみ) | fact_check / policy_proposal / accountability / information_request / other |

### 2.3 LLM への入力プロンプト形式

現状はセグメント内の全文に通し番号を振っていたが、新方式では**utterance単位で番号付け**し、長文 utterance のみ内部に sentence サブ番号を併記:

```
セグメント発言者: 浜地雅一（中道改革連合・無所属）

[U10] [質疑者] 浜地雅一:
  なぜ周知が必要かというと、この年収の壁支援強化パッケージが...
  ...御答弁をいただきたいと思います。

[U11] [委員長] 大串正樹:
  田中雇用環境均等局長。

[U12] [政府参考人] 田中雇用環境均等局長:
  お答えいたします。年収の壁支援強化パッケージの先ほど言及のありました...
  ...周知広報に一層取り組んでまいりたいと考えております。

[U13] [質疑者] 浜地雅一:
  ありがとうございます。私も手元にデータがあるんですけど...
```

代表質問・所信表明のような長文 utterance のみ:

```
[U5] [答弁者] 高市早苗:
  (s120) 内閣総理大臣高市早苗君。
  (s121) 先般の総選挙の結果を受け、首班指名をいただき...
  (s122) 重要な政策転換を何としてもやり抜いていけ...
  ...
  (s230) 量子、航空、宇宙、コンテンツ、創薬などの17の戦略分野については...
```

このとき LLM は `[{utterance_indices: [5], split_anchor_sentence_idx: 120}, {utterance_indices: [5], split_anchor_sentence_idx: 145}, ...]` のように同じ utterance を複数ペアで共有しつつ、各ペアの開始位置を anchor で示す。

### 2.4 コード側の `full_text` 組み立てロジック

```python
def assemble_full_text(seg, pair_group):
    """1つの utterance を共有する複数ペアの full_text を構築。
    pair_group: 同じ utterance を共有するペア群（ソート済み by anchor）
    """
    if len(pair_group) == 1:
        # 単独ペア: utterance全文をそのまま使う
        pair = pair_group[0]
        utts = [seg.utterances[i] for i in pair.utterance_indices]
        return "\n".join(u.text for u in utts)
    else:
        # 複数ペア共有: anchor で境界分割
        u_idx = pair_group[0].utterance_indices[0]  # 共有utterance
        utt = seg.utterances[u_idx]
        sentences = split_sentences(utt.text)
        # 各ペアの開始 sentence_idx を取得（anchor が None なら utterance 先頭=0）
        anchors = [p.split_anchor_sentence_idx for p in pair_group]
        # 連続スライス割り当て
        boundaries = sorted(set(anchors + [len(sentences)]))
        for i, pair in enumerate(sorted(pair_group, key=lambda p: p.split_anchor_sentence_idx or 0)):
            start = pair.split_anchor_sentence_idx or 0
            end = boundaries[boundaries.index(start) + 1]
            pair.full_text = "".join(sentences[start:end])
```

これにより:

- 単独ペア（99%）: 挨拶・前置き含む utterance 全文が `full_text` に入る
- 共有ペア（1%）: 各ペアは utterance 内の連続スライスを担当し、全 sentence は必ずどこかのペアに属する（穴ができない）

### 2.5 旧 `sentence_indices` 方式の廃止

現状の `_split_sentences`, `_build_sentence_map`, `_assemble_full_text_from_sentences`, `_build_sentence_to_utterance_map` は新方式では不要（または大幅縮小）。

ただし `_split_segment_into_blocks`（委員長指名による質疑ブロック分割）は引き継ぎ、新方式でも使用する。

---

## 3. 副次的に解決される既存課題

`docs/data-review/` で既出の問題のうち、本刷新で同時に解消されるもの:

| 既存課題 | 解消理由 |
|--|--|
| 06-qa-extraction §A: 答弁が空のペア（217件） | utterance_indices が空の答弁ペアは出力時に弾く構造に。プロンプトでも明示。 |
| 06-qa-extraction §B: 質問が極端に短い（44件） | utterance ベースなら「趣旨説明定型句」の独立 utterance はペア化されず、自然に除外される。 |
| `_INPUT_CHAR_LIMIT = 20000` 制限（33セグメント） | utterance 単位の番号付けで入力トークンが大幅減少。20000制限を撤廃するか引き上げ可能。 |
| 過去計画ドキュメント（ISSUES.md §1-1, §1-2）の `sentence_indices` が空配列問題 | 新スキーマには `sentence_indices` 自体が無い。 |

---

## 4. 影響範囲と移行計画

### 4.1 コード変更箇所

| ファイル | 変更内容 |
|--|--|
| `src/prompts.py:QA_SEGMENT_SYSTEM_PROMPT` | 全面書き換え（utterance_indices + split_anchor 形式の指示） |
| `src/structurer.py` | `_extract_pairs_from_response`, `_generate_qa_for_segment`, `_build_sentence_map` 周辺の全面書き換え。`_split_segment_into_blocks`, `_resolve_speaker_*`, `_resolve_answerer_*` は引き継ぎ。 |
| `src/models.py` | `QuestionDetail` / `AnswerDetail` のスキーマ確認・調整（`full_text` フィールドは残すが LLM 出力には含まれない） |
| `src/pipeline.py` | 影響なし想定 |
| `_INPUT_CHAR_LIMIT` | 撤廃または60000程度に引き上げ |

### 4.2 下流処理の影響

以下は `qa_pairs.json` を入力として動作するため、`full_text` の内容変化に対する影響を確認:

- `generate_session_summary` — `full_text` 短縮 → 完全になることでサマリー品質は向上するはず
- `generate_topics_and_key_topics` — トピック抽出は `summary` ベースなので影響軽微
- `generate_key_commitments` — `summary` ベースなので影響軽微
- `tag_related_laws` — `summary` ベースなので影響軽微
- `score_qa_pairs_metrics` — `full_text` を直接見るため、評価指標は変動する。V4 メトリクスのキャリブレーションを再確認する必要あり。

### 4.3 サイト側の影響

`site/` 配下のコンポーネントは `full_text` をそのまま表示しているだけなので、機能影響は無い。ただし表示テキストが長くなる可能性があるため、レイアウト確認は必要:

- `QAPairCard.astro` — full_text 折り畳み表示の高さ調整が必要かも
- `[chamber]/[year]/[month]/[day]/[slug].astro` — 全文表示は問題なし
- `search.astro` — Pagefind 再インデックス必要（自動化済み）

### 4.4 検証手順

実装後、以下を順に確認:

1. **単体テスト**: `tests/` 配下に新スキーマのパース・assemble ロジックのユニットテストを追加
2. **dry-run で 1 セッション再生成**: `2026/04/24/56209_厚生労働委員会` で qa_022 が完全な答弁を含むか目視確認
3. **代表質問セッションで dry-run**: `2026/02/20/56075_本会議` で高市答弁が複数ペアにきれいに分割され、かつ冒頭の「内閣総理大臣高市早苗君。先般の総選挙…」が qa_002 に含まれるか確認
4. **全 QA ペア数の比較**: 旧データと比較してペア数が極端に増減していないか
5. **サマリー品質の目視確認**: 数セッションで `summary` が挨拶を含んでいないか、内容が要約として妥当か

### 4.5 実装順序

1. プロンプト草案 (`QA_SEGMENT_SYSTEM_PROMPT_V2`) を作成
2. `structurer.py` 新版を書く（旧版は一時的に併存させても良い）
3. ユニットテスト追加
4. 手元の単一セッションで dry-run、目視確認
5. 5〜10セッションで dry-run、QA ペア数とサマリー品質の比較
6. **全生成済みセッション削除**（このドキュメント冒頭の手順）
7. 全データ再生成
8. サイトビルド・Pagefind 再インデックス
9. 旧コード（`_split_sentences` 等）削除

---

## 5. 設計判断のログ

### Q: なぜ post-processing で既存データを修正する案を採用しなかったか

post-processing 案（`docs/data-review/06-qa-extraction.md` 等で言及されていた既存方針の延長）の最大の利点は「LLM 再呼び出し不要で既存データを救える」ことだった。しかし**全データ再生成を別の品質改善目的で行う予定があり、その利点が消滅する**。

再生成前提なら、LLM への入力トークン削減・20000文字制限の自然解消・LLM 失敗モード低減・コード単純化など、すべての観点で utterance ベーススキーマが優位。

### Q: なぜ LLM に utterance_indices だけ返させず anchor も持たせるか

99% のペアで anchor は不要（`null`）。ただし代表質問・所信表明（1%、208件観測）は1人の答弁者が長大な utterance で複数のテーマを連続で話すケースがあり、これを単純に utterance 単位で扱うと「同じ full_text を持つ複数ペア」が生まれてしまう（過去にコミット `8f122f6` で発生した既知問題、`docs/ISSUES.md §1-1` 参照）。

anchor 方式で LLM に「このペアは utterance のどこから始まるか」を sentence 番号で明示させ、コードが境界を計算することで、共有 utterance も穴なく分割される。

### Q: なぜ summary プロンプトは変更しないか

現状の `prompts.py` で `summary` は「実質的な問いかけ内容のみ（挨拶・背景不要）」と指示済みで、これはユーザー要件と一致している。`full_text` の方針だけが要件と逆向きだったので、`full_text` の組み立てだけを変える。

### Q: 既存の `_resolve_answerer_from_sentences`（議員→大臣補正）は引き継ぐか

引き継ぐ。これは「議員が答弁者として誤解決された場合に、同範囲の非議員に置き換える」という防御で、新方式でも同様のロジックが必要。`sentence_indices` を使っていたインターフェースを `utterance_indices` に置き換えるのみ。

---

## 6. 未解決の論点

実装着手時に再検討する事項:

- [ ] サブ番号付き utterance（`(s120)` 形式）を LLM が安定してパース・参照できるか、実プロンプトで検証が必要
- [ ] 単一答弁が複数 utterance に分かれるケース（chair が割り込んで答弁者が再開、など）を `utterance_indices: [12, 14]` のように扱う場合、間の utterance（chair の発言）を明示的に skip する指示をプロンプトに含めるか
- [ ] 旧 `sentence_indices` 形式のテストコード・スナップショットの扱い（破棄するか新規書き起こし）
- [ ] `score_qa_pairs_metrics` (V4) が `full_text` を直接読むため、`full_text` が長くなることでスコア分布が変動する可能性。閾値再キャリブレーションの要否
